"""Durable transcript checkpoint, clinician revisions, and single-flight SOAP generation."""
import json
import time

from medflow.domain.enums import Speaker, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import utc_now
from medflow.orchestration import WorkflowAction
from security_guardrails import require_authorized
from security_guardrails.telemetry import collect_provider_events
from app.services.evidence_checks import note_evidence_report
from medflow.medicines import report as medicine_report, clinician_review, check_turn
from app.services.conversation_relevance import report as relevance_report


class ConsultationReviewError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ConsultationReviewStore:
    def __init__(self, database):
        self.database = database

    def initialize(self):
        with self.database.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS consultation_reviews (workflow_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')

    def get(self, workflow_id):
        with self.database.connection() as db:
            row = db.execute('SELECT payload FROM consultation_reviews WHERE workflow_id=?', (workflow_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def change(self, workflow_id, function):
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM consultation_reviews WHERE workflow_id=?', (workflow_id,)).fetchone()
            value = function(json.loads(row[0]) if row else None)
            value['updated_at'] = utc_now().isoformat()
            db.execute('INSERT INTO consultation_reviews VALUES (?,?) ON CONFLICT(workflow_id) DO UPDATE SET payload=excluded.payload', (workflow_id, json.dumps(value)))
        return value


class ConsultationReviewService:
    def __init__(self, container):
        self.c = container
        self.store = ConsultationReviewStore(container.database)

    def context(self, workflow_id, actor):
        workflow = self.c.workflow_orchestrator.get_session(workflow_id, actor=actor)
        require_authorized(actor, 'create_note_draft', workflow.patient_id)
        encounter = self.c.encounter_repository.get(workflow.encounter_id) if workflow.encounter_id else None
        if not encounter or encounter.patient_id != workflow.patient_id:
            raise ConsultationReviewError('PATIENT_MISMATCH', 'This transcript is not attached to the current encounter.')
        return workflow

    def payload(self, workflow_id, actor):
        workflow = self.c.workflow_orchestrator.get_session(workflow_id, actor=actor)
        value = self.store.get(workflow_id)
        if not value or value['status']=='SUPERSEDED' or (not workflow.note_id and workflow.state not in {WorkflowState.DOCUMENTATION_PROCESSING,WorkflowState.TRANSCRIPT_REVIEW,WorkflowState.FAILED}):
            return None
        require_authorized(actor, 'read_notes', workflow.patient_id)
        transcript = self.c.transcript_repository.get(value['transcript_id'])
        if not transcript or transcript.patient_id != workflow.patient_id or transcript.encounter_id != workflow.encounter_id:
            raise ConsultationReviewError('PATIENT_MISMATCH', 'Transcript belongs to a different visit.')
        return {key: value.get(key) for key in ('status', 'revision', 'transcript_id', 'run_id', 'template_id', 'auto_soap', 'last_error', 'note_id', 'updated_at', 'reviewed_by', 'reviewed_at', 'audio_retention')} | {
            'utterances': [self.c.documentation_service.utterance_payload(item, translated=True) for item in transcript.utterances],
            'medicine_report':medicine_report(transcript.utterances),
            'symptom_patterns':transcript.symptom_patterns,
            'relevance_report': relevance_report(transcript.utterances),
            'raw_asr_text':transcript.raw_asr_text}

    def prepare(self, workflow_id, transcript, run_id, template_id, auto_soap):
        return self.store.change(workflow_id, lambda old: {
            'status': 'TRANSLATING', 'revision': 1, 'transcript_id': transcript.transcript_id,
            'run_id': run_id, 'template_id': template_id, 'auto_soap': auto_soap,
            'last_error': '', 'note_id': None, 'audio_retention': None})

    def ready(self, workflow_id, actor):
        workflow = self.context(workflow_id, actor)
        if workflow.state == WorkflowState.DOCUMENTATION_PROCESSING:
            self.c.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.TRANSCRIPT_READY, actor=actor, expected_version=workflow.version)
        self.store.change(workflow_id, lambda row: {**row, 'status': 'TRANSCRIPT_REVIEW', 'last_error': ''})

    def _claim(self, workflow_id, revision, transcript_id, status, allowed):
        token = new_id('OP')
        def update(row):
            if not row:
                raise ConsultationReviewError('TRANSCRIPT_NOT_FOUND', 'No saved transcript is available.')
            if row['revision'] != revision or row['transcript_id'] != transcript_id:
                raise ConsultationReviewError('VERSION_CONFLICT', 'The transcript changed. Reload the latest revision.')
            if row['status'] not in allowed:
                raise ConsultationReviewError('ACTION_IN_PROGRESS', 'Another transcript action is running. Wait for it to finish.')
            return {**row, 'status': status, 'operation_token': token, 'last_error': ''}
        return self.store.change(workflow_id, update)

    def _finish(self, workflow_id, claimed, **changes):
        def update(row):
            if row.get('operation_token') != claimed['operation_token']:
                raise ConsultationReviewError('VERSION_CONFLICT', 'The visit changed during processing.')
            return {**row, **changes, 'operation_token': None}
        return self.store.change(workflow_id, update)

    def _trace_call(self, row, stage, function, artifact, on_event=None):
        event = self.c.process_trace.append(row['run_id'], stage, 'running')
        if on_event: on_event(event)
        started = time.perf_counter()
        with collect_provider_events() as calls:
            try:
                result = function()
            except Exception:
                event = self.c.process_trace.append(row['run_id'], stage, 'failed', artifact={'code': 'PROCESSING_FAILED', 'message': 'This stage failed. Saved transcript is preserved.', 'provider_calls': list(calls)}, duration_ms=(time.perf_counter()-started)*1000)
                if on_event: on_event(event)
                raise
        event = self.c.process_trace.append(row['run_id'], stage, 'complete', artifact={**artifact(result), 'provider_calls': list(calls)}, duration_ms=(time.perf_counter()-started)*1000)
        if on_event: on_event(event)
        return result

    def revise(self, workflow_id, actor, revision, transcript_id, corrections):
        workflow = self.context(workflow_id, actor)
        if workflow.state != WorkflowState.TRANSCRIPT_REVIEW or workflow.note_id:
            raise ConsultationReviewError('INVALID_NOTE_STATE', 'Correct this conversation before generating its SOAP draft.')
        source = self.c.transcript_repository.get(transcript_id)
        if not source or source.patient_id != workflow.patient_id or source.encounter_id != workflow.encounter_id:
            raise ConsultationReviewError('PATIENT_MISMATCH', 'Transcript belongs to a different visit.')
        ids = {item.utterance_id for item in source.utterances}
        changes = {item['utterance_id']: item for item in corrections}
        if not changes or len(changes) != len(corrections) or any(key not in ids for key in changes):
            raise ConsultationReviewError('INVALID_CORRECTION', 'Correct each existing conversation turn at most once.')
        claimed = self._claim(workflow_id, revision, transcript_id, 'EDITING', {'TRANSCRIPT_REVIEW', 'SOAP_FAILED'})
        try:
            new_transcript_id = new_id('TRN')
            turns = []
            for item in source.utterances:
                correction = changes.get(item.utterance_id, {})
                update = {'transcript_id': new_transcript_id}
                if 'original_text' in correction:
                    update.update(original_text=correction['original_text'], clinical_english='')
                if 'speaker' in correction:
                    update.update(speaker=Speaker(correction['speaker']), addressed_to=None, needs_review=correction['speaker']=='UNKNOWN')
                    update['speaker_relation'] = correction.get('speaker_relation') if correction['speaker']=='ATTENDANT' else None
                turns.append(item.model_copy(update=update))
            from medflow.medicine_matching import FRAME_RE,WORD_RE
            turns=[turn.model_copy(update={'medicine_context':index>0 and len(WORD_RE.findall(turn.original_text))<=5
                and bool(FRAME_RE.search(turns[index-1].original_text))}) for index,turn in enumerate(turns)]
            patient = self.c.patient_repository.get(workflow.patient_id)
            def translate_corrected():
                translated = self.c.documentation_service.translate(turns, patient=patient)
                # Store and inspect the final clinician wording, including explicit English edits.
                previous={item.utterance_id:item for item in source.utterances}
                result=[]
                for item in translated:
                    correction=changes.get(item.utterance_id,{})
                    old=previous[item.utterance_id]
                    if not correction:
                        context_changed=(item.medicine_context!=old.medicine_context or
                            item.medicine_suggestions.get('context_fingerprint')!=old.medicine_suggestions.get('context_fingerprint'))
                        update={'transcript_id':new_transcript_id}
                        if context_changed:
                            update.update(medicine_context=item.medicine_context,medicine_review=old.medicine_review if item.medicine_context==old.medicine_context else None,
                                medicine_suggestions=item.medicine_suggestions,
                                medicine_checks=check_turn(old.original_text,old.clinical_english,old.medicine_review,context=item.medicine_context,analysis=item.medicine_suggestions))
                        result.append(old.model_copy(update=update))
                        continue
                    english=correction.get('clinical_english',item.clinical_english)
                    review=old.medicine_review if english==old.clinical_english and item.original_text==old.original_text and item.medicine_context==old.medicine_context else None
                    if correction.get('medicines_reviewed'):
                        try:
                            review=clinician_review(item.original_text,english,correction.get('medicine_spellings',{}),actor.ref,context=item.medicine_context,analysis=item.medicine_suggestions)
                        except ValueError as exc:
                            raise ConsultationReviewError('INVALID_MEDICINE_REVIEW',str(exc)) from exc
                    result.append(item.model_copy(update={'clinical_english':english,'medicine_review':review,
                        'medicine_checks':check_turn(item.original_text,english,review,context=item.medicine_context,analysis=item.medicine_suggestions)}))
                return result
            relevance_only = all(set(k for k, v in c.items() if v is not None and v != {}) <= {'utterance_id', 'relevance_status', 'relevance_reason'} for c in changes.values())
            if relevance_only:
                translated = [t.model_copy(update={'transcript_id': new_transcript_id}) for t in source.utterances]
            else:
                translated = self._trace_call(claimed, 'translation', translate_corrected, lambda result: {'utterances': [self.c.documentation_service.utterance_payload(item, translated=True) for item in result], 'revision': revision+1, 'clinician_corrected_turns': list(changes)})
            from app.services.conversation_relevance import apply_overrides
            try:
                translated = apply_overrides(translated, corrections, actor)
            except ValueError as exc:
                raise ConsultationReviewError('INVALID_RELEVANCE', str(exc)) from exc
            latest = self.context(workflow_id, actor)
            if latest.state != WorkflowState.TRANSCRIPT_REVIEW or latest.note_id:
                raise ConsultationReviewError('VERSION_CONFLICT', 'The visit changed during correction.')
            self.c.documentation_service.save_transcript(transcript_id=new_transcript_id, patient_id=workflow.patient_id, encounter_id=workflow.encounter_id, utterances=translated,
                raw_asr_text=source.raw_asr_text,source_transcript_id=source.source_transcript_id or source.transcript_id)
            self._finish(workflow_id, claimed, status='TRANSCRIPT_REVIEW', revision=revision+1, transcript_id=new_transcript_id)
            self.c.audit_service.record('transcript_review_saved', actor_ref=actor.ref, action='create_note_draft', patient_ref=workflow.patient_id, resource_ref=new_transcript_id, metadata={'revision':revision+1,'changed_turns':len(changes)})
        except Exception as exc:
            self._finish(workflow_id, claimed, status='TRANSCRIPT_REVIEW', last_error='Transcript changes were not saved. Your previous revision is preserved.')
            if isinstance(exc, ConsultationReviewError):
                raise
            raise ConsultationReviewError('TRANSLATION_FAILED', 'Could not prepare the corrected translation. Retry saving your changes.') from exc

    def generate(self, workflow_id, actor, revision, transcript_id, on_event=None):
        workflow = self.context(workflow_id, actor)
        row = self.store.get(workflow_id)
        if row and row['revision'] == revision and row['transcript_id'] == transcript_id and row['status']=='SOAP_READY' and workflow.note_id == row['note_id']:
            return row  # Idempotent replay returns the same saved draft, without a provider call.
        if workflow.state != WorkflowState.TRANSCRIPT_REVIEW or workflow.note_id:
            raise ConsultationReviewError('INVALID_NOTE_STATE', 'Review the saved transcript before generating SOAP.')
        claimed = self._claim(workflow_id, revision, transcript_id, 'GENERATING', {'TRANSCRIPT_REVIEW', 'SOAP_FAILED'})
        try:
            transcript = self.c.transcript_repository.get(transcript_id)
            if not transcript or transcript.patient_id != workflow.patient_id or transcript.encounter_id != workflow.encounter_id:
                raise ConsultationReviewError('PATIENT_MISMATCH', 'Transcript belongs to a different visit.')
            if medicine_report(transcript.utterances)['requires_review']:
                raise ConsultationReviewError('MEDICINE_REVIEW_REQUIRED','Review the flagged medicine turns and correct their English wording before generating SOAP.')
            # Revalidate current recording/AI consent before reusing stored clinical text.
            decisions = self.c.consent_service.latest_decisions(workflow.encounter_id, actor=actor)
            for key in ('AI_TRANSCRIPTION', 'AI_DOCUMENTATION'):
                if not any(str(getattr(kind,'value',kind))==key and value and value.decision for kind,value in decisions.items()):
                    raise ConsultationReviewError('CONSENT_REQUIRED', 'Record the current AI permissions before generating SOAP.')
            self.c.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.GENERATE_DOCUMENTATION, actor=actor, expected_version=workflow.version)
            patient = self.c.patient_repository.get(workflow.patient_id)
            draft = self._trace_call(claimed, 'draft', lambda: self.c.documentation_service.generate_draft(workflow_id=workflow_id, patient=patient, encounter_id=workflow.encounter_id, transcript=transcript, actor=actor, template_id=claimed['template_id']), lambda result: {'note_id':result.note.note_id, 'generation_mode':result.legacy_soap.get('generation_mode','MODEL_VALIDATED'), 'soap':self.c.documentation_service.legacy_soap(result.version.soap)}, on_event=on_event)
            event=self.c.process_trace.append(claimed['run_id'], 'validation', 'running')
            if on_event: on_event(event)
            started = time.perf_counter()
            report = note_evidence_report(draft.version.soap, transcript, state=draft.version.status, version=1, note_id=draft.note.note_id)
            event=self.c.process_trace.append(claimed['run_id'], 'validation', 'complete', artifact={'evidence_report':report,'known_references':not report['counts']['failed'],'claim_count':report['counts']['statements'],'linked_claims':report['counts']['linked'],'warnings':report['warnings'],'missing_information':report['missing_information'],'clinician_approval':'Required','version':1}, duration_ms=(time.perf_counter()-started)*1000)
            if on_event: on_event(event)
            return self._finish(workflow_id, claimed, status='SOAP_READY', note_id=draft.note.note_id, reviewed_by=actor.ref, reviewed_at=utc_now().isoformat())
        except Exception as exc:
            latest = self.context(workflow_id, actor)
            if latest.note_id:
                return self._finish(workflow_id, claimed, status='SOAP_READY', note_id=latest.note_id)
            if latest.state == WorkflowState.DOCUMENTATION_PROCESSING:
                self.c.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.RETURN_TO_TRANSCRIPT, actor=actor, expected_version=latest.version)
            medicine_block=getattr(exc,'code','')=='MEDICINE_REVIEW_REQUIRED'
            self._finish(workflow_id, claimed, status='TRANSCRIPT_REVIEW' if medicine_block else 'SOAP_FAILED', last_error=str(exc) if medicine_block else 'SOAP generation was interrupted. The saved transcript is ready to retry.')
            if isinstance(exc, ConsultationReviewError):
                raise
            raise ConsultationReviewError('SOAP_FAILED', 'SOAP generation failed. Retry from the saved transcript; no new recording is needed.') from exc

    def retry_translation(self, workflow_id, actor, revision, transcript_id):
        workflow = self.context(workflow_id, actor)
        if workflow.note_id or workflow.state != WorkflowState.FAILED or workflow.resume_state != WorkflowState.DOCUMENTATION_PROCESSING:
            raise ConsultationReviewError('INVALID_NOTE_STATE', 'Only an interrupted translation can be retried here.')
        claimed = self._claim(workflow_id, revision, transcript_id, 'TRANSLATING', {'TRANSLATION_FAILED'})
        try:
            self.c.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.RESUME, actor=actor, expected_version=workflow.version)
            source = self.c.transcript_repository.get(transcript_id)
            patient = self.c.patient_repository.get(workflow.patient_id)
            translated = self._trace_call(claimed, 'translation', lambda: self.c.documentation_service.translate(source.utterances, patient=patient), lambda result: {'utterances':[self.c.documentation_service.utterance_payload(item,translated=True) for item in result]})
            self.c.documentation_service.save_transcript(transcript_id=transcript_id,patient_id=workflow.patient_id,encounter_id=workflow.encounter_id,utterances=translated)
            self._finish(workflow_id, claimed, status='TRANSCRIPT_REVIEW')
            self.ready(workflow_id, actor)
        except Exception as exc:
            latest = self.context(workflow_id, actor)
            if latest.state == WorkflowState.DOCUMENTATION_PROCESSING:
                self.c.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.MARK_FAILED, actor=actor, expected_version=latest.version,error_code='TRANSLATION_FAILED')
            self._finish(workflow_id, claimed,status='TRANSLATION_FAILED',last_error='Translation interrupted. The saved original conversation is preserved.')
            raise ConsultationReviewError('TRANSLATION_FAILED','Translation failed. Retry this stage or record again.') from exc

    def recover_interrupted(self):
        """Called once at server startup, before any current worker can own a lease."""
        with self.c.database.connection() as db:
            rows = [(row[0],json.loads(row[1])) for row in db.execute('SELECT workflow_id,payload FROM consultation_reviews')]
        for workflow_id,row in rows:
            workflow = self.c.workflow_repository.get(workflow_id)
            if not workflow:
                continue
            from security_guardrails import Actor
            actor = Actor.system('system_agent',workflow.patient_id)
            # Reconcile either side of the checkpoint/state writes after a crash.
            if row['status']=='TRANSCRIPT_REVIEW' and workflow.state==WorkflowState.DOCUMENTATION_PROCESSING and not workflow.note_id:
                self.c.workflow_orchestrator.perform_action(workflow_id,WorkflowAction.TRANSCRIPT_READY,actor=actor,expected_version=workflow.version)
                continue
            if row['status'] not in {'GENERATING','EDITING','TRANSLATING'}:
                continue
            if workflow.note_id:
                self.store.change(workflow_id,lambda value:{**value,'status':'SOAP_READY','note_id':workflow.note_id,'operation_token':None})
            elif row['status']=='TRANSLATING' and workflow.state==WorkflowState.TRANSCRIPT_REVIEW:
                self.store.change(workflow_id,lambda value:{**value,'status':'TRANSCRIPT_REVIEW','operation_token':None,'last_error':''})
            elif row['status']=='EDITING':
                self.store.change(workflow_id,lambda value:{**value,'status':'TRANSCRIPT_REVIEW','operation_token':None,'last_error':'Server restarted during correction. Previous revision preserved.'})
            else:
                status = 'SOAP_FAILED' if row['status']=='GENERATING' else 'TRANSLATION_FAILED'
                if workflow.state == WorkflowState.DOCUMENTATION_PROCESSING:
                    action = WorkflowAction.RETURN_TO_TRANSCRIPT if status=='SOAP_FAILED' else WorkflowAction.MARK_FAILED
                    self.c.workflow_orchestrator.perform_action(workflow_id,action,actor=actor,expected_version=workflow.version,error_code='SERVER_RESTARTED')
                self.store.change(workflow_id,lambda value:{**value,'status':status,'operation_token':None,'last_error':'Server restarted during processing. Retry the saved stage.'})
