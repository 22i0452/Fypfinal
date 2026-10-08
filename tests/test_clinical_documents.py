"""Synthetic documentation selection and prescription version/API regressions."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.main import create_app
from app.services.conversation_relevance import classify, report, generation_turns, apply_overrides, source_hash
from app.services.prescription_service import draft, save, PrescriptionEdit
from app.services.note_lifecycle_service import NoteLifecycleError
from medflow.domain.models import TranscriptUtterance, TranscriptRecord, ClinicalClaim, StructuredSOAP, SOAPNoteVersion, SOAPNote
from medflow.domain.enums import Speaker, NoteStatus, ConsentType
from security_guardrails import Actor, SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter
from tests.support import build_container
from tests import test_consultation_websocket as websocket_fixture


def turn(id, text, speaker=Speaker.DOCTOR):
    # Supply the context-analysis result the real translation flow records.
    # Route wording must not remain an unresolved lexical drug candidate.
    from medflow.medicine_context import source_fingerprint
    analysis={}
    if 'orally' in text:
        start=text.index('orally')
        analysis={'source_fingerprint':source_fingerprint(text),'entities':[{'kind':'non_medical',
            'source':'orally','start':start,'end':start+6}]}
    return TranscriptUtterance(transcript_id='TRN-DOC-QA', utterance_id=id, speaker=speaker,
        original_text=text, clinical_english=text, medicine_suggestions=analysis)


class RelevanceTests(unittest.TestCase):
    def setUp(self):
        self.adapter=MockProviderAdapter();set_gateway(SecureLLMGateway(provider='mock', adapters={'mock': self.adapter}))
    def tearDown(self): set_gateway(None)

    def suggestion(self, turns, excluded='U2'):
        self.adapter.set_response('conversation_relevance', {'turns': [
            {'utterance_id':t.utterance_id,'status':'excluded' if t.utterance_id==excluded else 'included',
             'topic':'social' if t.utterance_id==excluded else 'symptoms','reason':'Weather chat.' if t.utterance_id==excluded else 'Reported symptom.',
             'sections':[] if t.utterance_id==excluded else ['subjective']} for t in turns]})

    def test_full_context_classification_retains_source_and_filters_only_excluded(self):
        turns=[turn('U1','I have a fever.',Speaker.PATIENT),turn('U2','It is raining today.',Speaker.PATIENT)]
        self.suggestion(turns);result=classify(turns)
        self.assertEqual([t.original_text for t in result],[t.original_text for t in turns])
        self.assertEqual([t.utterance_id for t in generation_turns(result)],['U1'])
        sent=json.loads(self.adapter.calls[-1]['messages'][-1]['content'])['conversation']
        self.assertEqual(len(sent),2);self.assertEqual(report(result)['counts'],{'included':1,'excluded':1,'review':0})

    def test_short_answers_remain_reviewable_on_provider_failure(self):
        result=classify([turn('U1','Any allergy?'),turn('U2','No.',Speaker.PATIENT),turn('U3','Hello',Speaker.PATIENT)])
        self.assertEqual([t.utterance_id for t in generation_turns(result)],['U1','U2'])
        self.assertEqual(result[1].documentation_relevance['status'],'review')

    def test_missing_duplicate_unknown_ids_reject_entire_classification(self):
        turns=[turn('U1','Fever'),turn('U2','No allergy')]
        self.adapter.set_response('conversation_relevance',{'turns':[{'utterance_id':'U999','status':'excluded','topic':'social','reason':'x','sections':[]}]})
        self.assertTrue(all(t.documentation_relevance['status']=='review' for t in classify(turns)))

    def test_model_cannot_exclude_medicine_turn(self):
        turns=[turn('U2','Stop Motilium.')];self.suggestion(turns)
        result=classify(turns);self.assertEqual(result[0].documentation_relevance['status'],'included')

    def test_doctor_override_records_actor_and_stale_context_invalidates_it(self):
        turns=[turn('U1','I arrived by taxi.',Speaker.PATIENT)]
        corrected=apply_overrides(turns,[{'utterance_id':'U1','relevance_status':'excluded','relevance_reason':'Travel logistics only.'}],Actor('doctor-QA','doctor'))
        self.assertEqual(report(corrected)['items'][0]['reviewed_by'],'doctor:doctor-QA')
        self.assertEqual(generation_turns(corrected),[])
        changed=[corrected[0].model_copy(update={'clinical_english':'Taxi accident caused pain.'})]
        self.assertEqual(report(changed)['items'][0]['status'],'review')

    def test_doctor_cannot_use_selection_to_bypass_medicine_checks(self):
        with self.assertRaises(ValueError):
            apply_overrides([turn('U1','Take Panadol 500 mg.')],[{'utterance_id':'U1','relevance_status':'excluded','relevance_reason':'Skip.'}],Actor('QA','doctor'))

    def test_unknown_speaker_is_not_automatically_confirmed(self):
        turns=[turn('U1','I have a fever.',Speaker.UNKNOWN)];self.suggestion(turns,excluded='none')
        self.assertEqual(classify(turns)[0].documentation_relevance['status'],'review')

    def test_actual_soap_links_distinct_from_selection(self):
        turns=[turn('U1','Fever',Speaker.PATIENT)]
        soap=StructuredSOAP(subjective=[ClinicalClaim(claim_id='C1',text='Patient reports fever.',evidence_ids=['U1'])])
        self.assertEqual(report(turns,soap)['items'][0]['soap_links'][0]['claim_id'],'C1')


class PrescriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.settings,self.c,self.user,self.patient,self.actor,_=build_container(self.root)
        self.adapter=MockProviderAdapter();set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':self.adapter}))
        self.plan='Take Panadol 500 mg orally twice daily for 3 days. Stop Motilium. Have a blood test. Return in one week.'
        self.transcript=self.c.transcript_repository.save(TranscriptRecord(transcript_id='TRN-DOC-QA',patient_id=self.patient.patient_id,encounter_id='ENC-DOC-QA',
            utterances=[turn('U1','Take Panadol 500 mg orally twice daily for 3 days.'),turn('U2','Stop Motilium.')]))
        soap=StructuredSOAP(subjective=[ClinicalClaim(claim_id='S1',text='Headache reported.')],objective=[ClinicalClaim(claim_id='O1',text='Not documented.')],
            assessment=[ClinicalClaim(claim_id='A1',text='Doctor assessment recorded.')],plan=[ClinicalClaim(claim_id='P1',text=self.plan,evidence_ids=['U1','U2'])])
        self.version=self.c.note_repository.save_version(SOAPNoteVersion(note_version_id='NV-DOC-QA',note_id='NOTE-DOC-QA',version_number=1,status=NoteStatus.AI_DRAFT,
            soap=soap,transcript_id=self.transcript.transcript_id,created_by_actor_id='soap-generator-agent'))
        self.note=self.c.note_repository.save(SOAPNote(note_id='NOTE-DOC-QA',patient_id=self.patient.patient_id,encounter_id='ENC-DOC-QA',current_version_id=self.version.note_version_id))

    def tearDown(self):set_gateway(None);self.temp.cleanup()

    def response(self):
        return {'medicines':[{'name':'Panadol','action':'take','dose':'500 mg','route':'orally','frequency':'twice daily','duration':'3 days',
            'instructions':'Take Panadol 500 mg orally twice daily for 3 days.','source_quote':'Take Panadol 500 mg orally twice daily for 3 days.'},
            {'name':'Motilium','action':'stop','dose':'','route':'','frequency':'','duration':'','instructions':'Stop Motilium.','source_quote':'Stop Motilium.'}],
            'tests':'Have a blood test.','advice':'','follow_up':'Return in one week.'}

    def prepared(self):
        self.adapter.set_response('prescription_extract',self.response());return draft(self.c.note_lifecycle_service,self.note,self.version,extract=True)

    def edit(self):
        d=self.prepared();return PrescriptionEdit(expected_version=1,medicines=d['medicines'],tests=d['tests'],advice=d['advice'],follow_up=d['follow_up'],confirmed=True)

    def test_extraction_preserves_fields_and_stop_instructions(self):
        d=self.prepared();self.assertEqual(d['origin'],'source_extraction');self.assertEqual(d['medicines'][0]['dose'],'500 mg')
        self.assertEqual(d['medicines'][1]['action'],'stop');self.assertEqual(d['medicines'][1]['duration'],'');self.assertFalse(d['confirmed'])

    def test_missing_details_are_not_guessed_when_provider_output_invalid(self):
        for mutate in ('dose','name','stop','quote'):
            r=self.response()
            if mutate=='dose':r['medicines'][0]['dose']='1000 mg'
            if mutate=='name':r['medicines'][0]['name']='Paracetamol'
            if mutate=='stop':r['medicines'][1]['action']='take'
            if mutate=='quote':r['medicines'][0]['source_quote']='Invented instructions'
            self.adapter.set_response('prescription_extract',r);d=draft(self.c.note_lifecycle_service,self.note,self.version,extract=True)
            self.assertEqual(d['origin'],'source_layout_review');self.assertEqual(d['medicines'][0]['dose'],'')
            self.assertEqual(d['medicines'][1]['instructions'],'Stop Motilium.')

    def test_prescription_save_reapproval_and_immutable_version(self):
        service=self.c.note_lifecycle_service;note,version=save(service,self.note.note_id,self.actor,self.edit())
        self.assertEqual(version.version_number,2);self.assertEqual(version.prescription['reviewed_by'],self.actor.ref)
        self.assertIsNone(self.c.note_repository.get_version(self.version.note_version_id).prescription)
        note,_=service.submit_for_review(note.note_id,actor=self.actor);note,approved=service.approve(note.note_id,actor=self.actor)
        self.assertEqual(note.state,NoteStatus.APPROVED_BY_DOCTOR);self.assertEqual(approved.prescription['medicines'][1]['action'],'stop')
        reloaded=self.c.note_repository.get_version(approved.note_version_id)
        self.assertTrue(reloaded.prescription['confirmed'])

    def test_stale_version_and_missing_confirmation_rejected(self):
        request=self.edit();request.expected_version=9
        with self.assertRaises(NoteLifecycleError):save(self.c.note_lifecycle_service,self.note.note_id,self.actor,request)
        request.expected_version=1;request.confirmed=False
        with self.assertRaises(NoteLifecycleError):save(self.c.note_lifecycle_service,self.note.note_id,self.actor,request)

    def test_forged_source_and_reversal_of_stop_rejected(self):
        request=self.edit();request.medicines[1].action='take'
        with self.assertRaises(NoteLifecycleError):save(self.c.note_lifecycle_service,self.note.note_id,self.actor,request)
        request=self.edit();request.medicines[0].source_ids=['U999']
        with self.assertRaises(NoteLifecycleError):save(self.c.note_lifecycle_service,self.note.note_id,self.actor,request)

    def test_patient_history_does_not_become_automatic_order(self):
        changed=[t.model_copy(update={'speaker':Speaker.PATIENT}) for t in self.transcript.utterances]
        self.c.transcript_repository.save(self.transcript.model_copy(update={'utterances':changed}))
        self.assertTrue(all(r['action']=='review' for r in self.prepared()['medicines']))

    def test_soap_edit_invalidates_prescription_without_rewriting_previous_version(self):
        service=self.c.note_lifecycle_service;note,v=save(service,self.note.note_id,self.actor,self.edit())
        from app.services.documentation_service import DocumentationService
        sections=DocumentationService.legacy_soap(v.soap);sections['plan']+=' Additional doctor advice.'
        _,changed=service.edit_legacy_sections(note.note_id,sections=sections,actor=self.actor)
        self.assertIsNone(changed.prescription);self.assertTrue(self.c.note_repository.get_version(v.note_version_id).prescription['confirmed'])

    def test_api_export_only_current_approved_prescription(self):
        with TestClient(create_app(self.settings)) as client:
            client.post('/api/auth/login',json={'email':'doctor@example.test','password':'SyntheticPass123!'})
            base='/api/notes/'+self.note.note_id
            self.assertNotEqual(client.get(base+'/prescription.pdf').status_code,200)
            prepared=client.post(base+'/prescription/prepare',json={'expected_version':1})
            self.assertEqual(prepared.status_code,200,prepared.text)
            request=self.edit();saved=client.patch(base+'/prescription',json=request.model_dump())
            self.assertEqual(saved.status_code,200,saved.text)
            self.assertNotEqual(client.get(base+'/prescription.pdf').status_code,200)
            self.assertEqual(client.post(base+'/submit-for-review').status_code,200)
            approved=client.post(base+'/approve');self.assertEqual(approved.status_code,200,approved.text)
            pdf=client.get(base+'/prescription.pdf');self.assertEqual(pdf.status_code,200)
            self.assertTrue(pdf.content.startswith(b'%PDF'));self.assertEqual(pdf.headers['cache-control'],'no-store')
            client.post('/api/auth/logout');self.assertEqual(client.get(base+'/prescription.pdf').status_code,401)

    def test_unassigned_doctor_cannot_prepare_or_save(self):
        denied=Actor('other','doctor',{'OTHER-PATIENT'})
        with self.assertRaises(NoteLifecycleError):save(self.c.note_lifecycle_service,self.note.note_id,denied,self.edit())


class RelevanceWorkflowTests(unittest.TestCase):
    def test_saved_override_filters_generation_and_preserves_original_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            settings,c,p,u,actor,visit=websocket_fixture.ConsultationWebSocketTests()._ready_context(Path(directory))
            c.consent_service.capture_bundle(encounter_id=visit.encounter.encounter_id,decisions={kind:kind!=ConsentType.AUDIO_RETENTION for kind in ConsentType},
                consent_text_version='QA',capture_method='SYNTHETIC_TEST',actor=actor)
            c.lifecycle_service.start_consultation(visit.workflow.workflow_id,actor=actor)
            c.lifecycle_service.start_documentation(visit.workflow.workflow_id,actor=actor)
            transcript=c.documentation_service.save_transcript(transcript_id='TRN-DOC-QA',patient_id=p.patient_id,encounter_id=visit.encounter.encounter_id,
                utterances=[turn('U1','Fever reported.',Speaker.PATIENT),turn('U2','The parking lot is full.',Speaker.PATIENT)],raw_asr_text='Full original consultation')
            run=c.process_trace.start(p.patient_id,visit.encounter.encounter_id,'QA')
            c.consultation_review.prepare(visit.workflow.workflow_id,transcript,run,'TPL-GP-01',False);c.consultation_review.ready(visit.workflow.workflow_id,actor)
            c.consultation_review.revise(visit.workflow.workflow_id,actor,1,transcript.transcript_id,[{'utterance_id':'U2','relevance_status':'excluded','relevance_reason':'Parking logistics.'}])
            r=c.consultation_review.payload(visit.workflow.workflow_id,actor)
            self.assertEqual(r['revision'],2);self.assertEqual(r['relevance_report']['counts']['excluded'],1)
            self.assertEqual(len(c.transcript_repository.get(r['transcript_id']).utterances),2)
            self.assertEqual(c.transcript_repository.get(transcript.transcript_id).raw_asr_text,'Full original consultation')
            observed=[]
            class Generator:
                def generate(self,patient,conversation,**kwargs):
                    observed.extend(conversation)
                    return {'subjective':'Fever reported.','objective':'Not documented.','assessment':'Not documented.','plan':'Not documented.',
                        'evidence':[{'utterance_id':'U1'}],'claim_sources':{'subjective':[{'text':'Fever reported.','evidence_ids':['U1']}]}}
            c.documentation_service._soap_generator=Generator();c.documentation_service._diarizer=object();c.documentation_service._translator=object()
            c.consultation_review.generate(visit.workflow.workflow_id,actor,2,r['transcript_id'])
            self.assertEqual([t['utterance_id'] for t in observed],['U1'])
            workflow=c.workflow_repository.get(visit.workflow.workflow_id)
            from app.services.transcript_revision import revise_relevance
            payload=revise_relevance(c,workflow.note_id,actor,1,[{'utterance_id':'U2','relevance_status':'included','relevance_reason':'Doctor requests retention.'}])
            self.assertEqual(payload['version'],2);self.assertEqual(len(payload['transcript']),2)
            self.assertEqual(payload['soap']['relevance_report']['items'][1]['origin'],'doctor')
            with self.assertRaises(NoteLifecycleError):revise_relevance(c,workflow.note_id,actor,1,[{'utterance_id':'U2','relevance_status':'included','relevance_reason':'Stale'}])
