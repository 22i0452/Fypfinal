"""Synthetic regressions for conversational SOAP and safe saved-draft recovery."""
import unittest
from unittest.mock import patch
from tests.test_soap_quality import load_soap_module, SequenceAdapter, FailingAdapter
from tests import test_process_observability as process_fixture
from security_guardrails import SecureLLMGateway, set_gateway
from medflow.domain.enums import NoteStatus, ConsentType, WorkflowState, Speaker
from medflow.medicines import clinician_review


class SOAPConversationQualityTests(unittest.TestCase):
    def tearDown(self):
        set_gateway(None)

    @staticmethod
    def source():
        return [
            {'utterance_id':'U1','speaker':'Patient','text':'Peace be upon you. I have a sore throat and high fever.'},
            {'utterance_id':'U2','speaker':'Doctor','text':'Okay, how many days ago did this start and how did it begin?'},
            {'utterance_id':'U3','speaker':'Patient','text':'It started two days ago. I am experiencing vomiting.'},
            {'utterance_id':'U4','speaker':'Doctor','text':'Take Motilium, one tablespoon. Take Paracetamol syrup, one tablespoon in the morning and one tablespoon at night.'},
            {'utterance_id':'U5','speaker':'Patient','text':'Thank you very much.'},
        ]

    @staticmethod
    def summary():
        return {'subjective':'Patient reports sore throat, high fever and vomiting for two days.',
            'objective':'No vital signs or examination findings documented.',
            'assessment':'Clinician assessment not documented.',
            'plan':'Take Motilium, one tablespoon. Take Paracetamol syrup, one tablespoon in the morning and one tablespoon at night.',
            'evidence':[{'utterance_id':'U1'},{'utterance_id':'U3'},{'utterance_id':'U4'}]}

    def test_screenshot_fallback_drops_courtesy_and_history_question_not_medicines(self):
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        result=load_soap_module().SOAPGenerator().generate({'current_complaint':'shtirat','past_medical_history':'none.'},self.source())
        self.assertEqual(result['generation_mode'],'TRANSCRIPT_FALLBACK')
        self.assertNotIn('Peace be upon',result['subjective']);self.assertNotIn('Thank you',result['subjective'])
        self.assertNotIn('shtirat',result['subjective']);self.assertNotIn('none.',result['subjective'])
        self.assertIn('two days',result['subjective']);self.assertIn('vomiting',result['subjective'])
        self.assertNotIn('did this start',result['plan']);self.assertNotIn('?',result['plan'])
        self.assertIn(self.source()[3]['text'],result['plan'])
        self.assertEqual({e['utterance_id'] for e in result['evidence']},{'U1','U3','U4'})
        self.assertIn('not documented',result['assessment'].lower())

    def test_conversation_dump_gets_one_full_context_repair(self):
        bad=self.summary();bad['subjective']='Peace be upon you. '+bad['subjective']
        bad['plan']='How many days ago did this start? '+bad['plan']
        adapter=SequenceAdapter([bad,self.summary()]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        turns=self.source();turns[3].update(original_text='موٹیلیم ایک کھانے کا چمچ لیں۔ Paracetamol syrup ایک کھانے کا چمچ صبح اور رات لیں۔',speaker_relation=None)
        result=load_soap_module().SOAPGenerator().generate({},turns)
        self.assertEqual(result['generation_mode'],'MODEL_VALIDATED');self.assertEqual(len(adapter.calls),2)
        messages=adapter.calls[1]['messages'];sent='\n'.join(m['content'] for m in messages)
        self.assertIn('conversational_text:plan',sent);self.assertIn('موٹیلیم',sent)
        self.assertIn('COMPLETE_ORIGINAL_SOURCE_CONTEXT',sent);self.assertIn('one tablespoon',result['plan'])

    def test_doctor_medicine_question_is_preserved_without_becoming_prescription(self):
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        result=load_soap_module().SOAPGenerator().generate({},[
            {'utterance_id':'U1','speaker':'Doctor','text':'Did you take Motilium?'},
            {'utterance_id':'U2','speaker':'Patient','text':'No.'},
            {'utterance_id':'U3','speaker':'Doctor','text':'Stop Panadol.'}])
        self.assertIn('Motilium',result['subjective']);self.assertIn('No.',result['subjective'])
        self.assertNotIn('Motilium',result['plan']);self.assertIn('Stop Panadol.',result['plan'])

    def test_section_salvage_cannot_accept_conversation_dump(self):
        bad=self.summary();bad['objective']='Blood pressure is 120/80.'
        bad['plan']='How many days ago did this start? '+bad['plan']
        adapter=SequenceAdapter([bad,bad]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        result=load_soap_module().SOAPGenerator().generate({},self.source())
        self.assertEqual(result['generation_mode'],'TRANSCRIPT_FALLBACK')
        self.assertNotIn('did this start',result['plan']);self.assertNotIn('120/80',result['objective'])
        self.assertIn(self.source()[3]['text'],result['plan'])


class SOAPRegenerationAPITests(unittest.TestCase):
    setUp=process_fixture.ProcessObservabilityTests.setUp
    tearDown=process_fixture.ProcessObservabilityTests.tearDown
    capture=process_fixture.ProcessObservabilityTests.capture

    def saved(self):
        result,_=self.capture();self.assertEqual(result['type'],'soap_note')
        self.note_id=result['note_id'];return self.client.get('/api/notes/'+self.note_id).json()

    def rebuild(self,version=1):
        return self.client.post('/api/notes/'+self.note_id+'/regenerate-soap',json={'expected_version':version})

    def test_rebuild_version_preserves_approved_medicine_source_without_retranslation(self):
        old=self.saved();note=self.c.note_repository.get(self.note_id);version=self.c.note_repository.get_version(note.current_version_id)
        source=self.c.transcript_repository.get(version.transcript_id)
        urdu='پینانڈول 500 mg دوائی لیں۔';english='Take Panadol 500 mg.'
        review=clinician_review(urdu,english,{'پینانڈول':'Panadol'},self.actor.ref)
        turn=source.utterances[0].model_copy(update={'original_text':urdu,'clinical_english':english,'speaker':Speaker.DOCTOR,'medicine_review':review,'medicine_suggestions':{},'documentation_relevance':{}})
        self.c.transcript_repository.save(source.model_copy(update={'utterances':[turn]}))
        observed=[]
        class Generator:
            def generate(self,patient,conversation,**kwargs):
                observed.extend(conversation)
                return {'generation_mode':'MODEL_VALIDATED','subjective':'Not documented.','objective':'Not documented.',
                    'assessment':'Not documented.','plan':english,'evidence':[{'utterance_id':turn.utterance_id}],
                    'claim_sources':{'plan':[{'text':english,'evidence_ids':[turn.utterance_id]}]}}
        with patch.object(self.c.documentation_service,'translate',side_effect=AssertionError('Must not retranslate reviewed source')):
            self.c.documentation_service._soap_generator=Generator()
            response=self.rebuild(old['version'])
        self.assertEqual(response.status_code,200,response.text);new=response.json()
        self.assertEqual(new['version'],old['version']+1);self.assertEqual(new['state'],'AI_DRAFT')
        self.assertIsNone(new['soap'].get('prescription'))
        self.assertEqual(observed[0]['original_text'],urdu);self.assertEqual(observed[0]['medicine_review'],review)
        self.assertEqual(new['transcript'][0]['clinical_english'],english)
        self.assertEqual(self.c.note_repository.get_version(version.note_version_id).version_number,old['version'])
        self.assertEqual(self.c.transcript_repository.get(source.transcript_id).utterances[0].medicine_review,review)
        self.assertEqual(self.rebuild(old['version']).status_code,409)

    def test_failed_summary_leaves_current_version_and_transcript_unchanged(self):
        old=self.saved();note=self.c.note_repository.get(self.note_id)
        generator=self.c.documentation_service._components()[2]
        with patch.object(generator,'generate',return_value={'generation_mode':'TRANSCRIPT_FALLBACK'}):
            response=self.rebuild(old['version'])
        self.assertEqual(response.status_code,503,response.text)
        self.assertEqual(self.c.note_repository.get(self.note_id).current_version_id,note.current_version_id)
        self.assertEqual(self.client.get('/api/notes/'+self.note_id).json()['transcript'],old['transcript'])

    def test_approved_or_closed_note_cannot_be_rebuilt(self):
        old=self.saved();note=self.c.note_repository.get(self.note_id)
        self.c.note_repository.save(note.model_copy(update={'state':NoteStatus.APPROVED_BY_DOCTOR}))
        self.assertNotEqual(self.rebuild(old['version']).status_code,200)
        self.c.note_repository.save(note)
        workflow=self.c.workflow_repository.get(self.context.workflow.workflow_id)
        self.c.workflow_repository.save(workflow.model_copy(update={'state':WorkflowState.ENCOUNTER_COMPLETED}))
        self.assertNotEqual(self.rebuild(old['version']).status_code,200)

    def test_permissions_stale_version_and_required_consent(self):
        old=self.saved();self.assertEqual(self.rebuild(99).status_code,409)
        self.c.consent_service.capture_bundle(encounter_id=self.context.encounter.encounter_id,
            decisions={kind:kind not in {ConsentType.AI_DOCUMENTATION,ConsentType.AUDIO_RETENTION} for kind in ConsentType},consent_text_version='CONSENT-V1',capture_method='SYNTHETIC_TEST',actor=self.actor)
        self.assertNotEqual(self.rebuild(old['version']).status_code,200)
        self.c.auth_repository.create_doctor('Other','other@test.example','OtherPass123!')
        self.client.post('/api/auth/login',json={'email':'other@test.example','password':'OtherPass123!'})
        self.assertEqual(self.rebuild(old['version']).status_code,403)
        self.client.post('/api/auth/logout');self.assertEqual(self.rebuild(old['version']).status_code,401)

    def test_concurrent_edit_during_generation_is_not_overwritten(self):
        old=self.saved();generator=self.c.documentation_service._components()[2];original=generator.generate
        def change(*args,**kwargs):
            result=original(*args,**kwargs)
            self.c.note_lifecycle_service.edit_legacy_sections(self.note_id,actor=self.actor,
                sections={**{k:old['soap'][k] for k in ('subjective','objective','assessment','plan')},'subjective':'Doctor updated symptom wording.'})
            return result
        with patch.object(generator,'generate',side_effect=change):
            response=self.rebuild(old['version'])
        self.assertEqual(response.status_code,409,response.text)
        current=self.client.get('/api/notes/'+self.note_id).json()
        self.assertEqual(current['version'],old['version']+1)
        self.assertIn('Doctor updated symptom wording',current['soap']['subjective'])

    def test_revoked_permission_blocks_rebuild_and_preserves_note(self):
        old=self.saved();note=self.c.note_repository.get(self.note_id)
        record=self.c.consent_service.latest_decisions(self.context.encounter.encounter_id,actor=self.actor)[ConsentType.AI_DOCUMENTATION]
        self.c.consent_service.revoke(consent_id=record.consent_id,actor=self.actor)
        generator=self.c.documentation_service._components()[2]
        with patch.object(generator,'generate',side_effect=AssertionError('No provider call after permission revocation')):
            self.assertNotEqual(self.rebuild(old['version']).status_code,200)
        self.assertEqual(self.c.note_repository.get(self.note_id).current_version_id,note.current_version_id)

    def test_permission_revoked_during_generation_prevents_save(self):
        old=self.saved();generator=self.c.documentation_service._components()[2];original=generator.generate
        def revoke(*args,**kwargs):
            result=original(*args,**kwargs)
            record=self.c.consent_service.latest_decisions(self.context.encounter.encounter_id,actor=self.actor)[ConsentType.AI_DOCUMENTATION]
            self.c.consent_service.revoke(consent_id=record.consent_id,actor=self.actor)
            return result
        with patch.object(generator,'generate',side_effect=revoke):
            self.assertNotEqual(self.rebuild(old['version']).status_code,200)
        self.assertEqual(self.client.get('/api/notes/'+self.note_id).json()['version'],old['version'])
