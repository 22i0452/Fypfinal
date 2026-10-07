"""Clinician role corrections create a new transcript and draft version on the same note."""
from medflow.domain.enums import NoteStatus, Speaker, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import EvidenceReference, SOAPNoteVersion, TranscriptRecord, utc_now
from app.services.note_lifecycle_service import NoteLifecycleError
from security_guardrails import require_authorized


def revise_roles(container, note_id, actor, expected_version, corrections):
    service = container.note_lifecycle_service
    note, current = service.get(note_id, actor=actor)
    service._require(actor, 'create_note_draft', note.patient_id)
    workflow = service._workflow_for_note(note)
    if current.version_number != expected_version:
        raise NoteLifecycleError('VERSION_CONFLICT', 'Reload the latest note before correcting roles.')
    if note.state == NoteStatus.APPROVED_BY_DOCTOR or not workflow or workflow.state in {WorkflowState.ENCOUNTER_COMPLETED, WorkflowState.CANCELLED}:
        raise NoteLifecycleError('INVALID_NOTE_STATE', 'Correct roles on an unapproved active draft.')
    source = container.transcript_repository.get(current.transcript_id) if current.transcript_id else None
    if not source:
        raise NoteLifecycleError('TRANSCRIPT_NOT_FOUND', 'The source transcript is unavailable.')
    if source.patient_id != note.patient_id or source.encounter_id != note.encounter_id:
        raise NoteLifecycleError("PATIENT_MISMATCH", "Transcript does not belong to this encounter.")
    valid_ids = {item.utterance_id for item in source.utterances}
    if any(item['utterance_id'] not in valid_ids for item in corrections):
        raise NoteLifecycleError('UNKNOWN_UTTERANCE', 'A correction referenced an unknown turn.')
    if len({item['utterance_id'] for item in corrections}) != len(corrections):
        raise NoteLifecycleError('DUPLICATE_CORRECTION', 'Correct each turn once.')
    changes = {item['utterance_id']:item for item in corrections}
    transcript_id = new_id('TRN')
    utterances = []
    for item in source.utterances:
        update = {'transcript_id':transcript_id}
        if item.utterance_id in changes:
            correction = changes[item.utterance_id]
            update.update(speaker=Speaker(correction['speaker']), speaker_relation=correction.get('speaker_relation') if correction['speaker']=='ATTENDANT' else None, addressed_to=None, needs_review=correction['speaker']=='UNKNOWN')
        utterances.append(item.model_copy(update=update))
    patient = container.patient_repository.get(note.patient_id)
    translated = container.documentation_service.translate(utterances, patient=patient)
    transcript = TranscriptRecord(transcript_id=transcript_id, patient_id=note.patient_id, encounter_id=note.encounter_id, utterances=translated)
    template = container.template_service.require_active(current.template_id)
    legacy = container.documentation_service._components()[2].generate(container.documentation_service._patient_context(patient), [container.documentation_service.utterance_payload(item, translated=True) for item in translated], template={'template_id':template.template_id,'name':template.name,'sections':template.sections})
    soap = container.documentation_service.build_structured_soap(note_id, legacy, transcript)
    # Do not overwrite a note edited or approved while providers were running.
    latest, version = service.get(note_id, actor=actor)
    if latest.current_version_id != current.note_version_id or latest.state == NoteStatus.APPROVED_BY_DOCTOR:
        raise NoteLifecycleError('VERSION_CONFLICT', 'The note changed during processing. Reload it and try again.')
    revised = SOAPNoteVersion(note_version_id=new_id('NV'), note_id=note_id, version_number=current.version_number+1, status=NoteStatus.AI_DRAFT, soap=soap,
        evidence=[EvidenceReference(evidence_id=item.utterance_id,source_type='TRANSCRIPT_UTTERANCE',source_id=item.utterance_id,excerpt=item.clinical_english or item.original_text) for item in translated],
        transcript_id=transcript_id, template_id=current.template_id, created_by_actor_id=actor.ref, change_reason='Clinician corrected speaker roles; translation and SOAP regenerated')
    container.transcript_repository.save(transcript)
    container.note_repository.save_version(revised)
    updated = latest.model_copy(update={'current_version_id':revised.note_version_id,'state':NoteStatus.AI_DRAFT,'updated_at':utc_now(),'approved_at':None,'approved_by_doctor_id':None})
    container.note_repository.save(updated)
    container.audit_service.record('transcript_roles_corrected', actor_ref=actor.ref,action='create_note_draft',patient_ref=note.patient_id,resource_ref=note_id,result='allow',metadata={'version':revised.version_number,'turn_count':len(corrections)})
    return service.payload(updated, revised, patient_name=patient.name)
