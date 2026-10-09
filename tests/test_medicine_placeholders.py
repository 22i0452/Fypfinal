"""Synthetic regressions for abbreviated medicine identifiers and source recovery."""
import json
import unittest
from unittest.mock import Mock,patch

from medflow.medicines import (has_medicine_placeholder,translation_issues,check_turn,
    restore,protect,soap_issues,clinician_review)
from medflow.domain.enums import Speaker
from medflow.domain.models import TranscriptUtterance
from scribe.translator import MedicalTranslator
from scribe.transcript_cleaner import TranscriptCleaner
from security_guardrails import SecureLLMGateway,set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter
from tests import test_guided_consultation as guided
from tests.test_medicine_context import ContextAdapter


class ManifestAdapter(ContextAdapter):
    def __init__(self,mode='valid'):
        super().__init__();self.repair_mode=mode
    def chat(self,*,task_type,model,messages,**kwargs):
        if task_type=='medicine_translation_repair':
            self.calls.append({'task_type':task_type,'messages':messages});self.task_order.append(task_type)
            if self.repair_mode=='offline':raise RuntimeError('Synthetic repair unavailable')
            data=json.loads(messages[-1]['content']);rows=[]
            for target in data['conversation']:
                matches=[m for m in data['medicine_manifest'] if m['utterance_id']==target['utterance_id']]
                if self.repair_mode=='damaged':text='Take MF_MED_...'
                elif self.repair_mode=='swap':text='Take Motilium 500 mg. Stop Panadol.'
                elif self.repair_mode=='dose':text='Take Panadol 1000 mg. Stop Motilium.'
                elif matches:text='Take '+matches[0]['allowed_english']+' 500 mg. Stop '+matches[1]['allowed_english']+'.' if len(matches)>1 else 'Take '+matches[0]['allowed_english']+'.'
                else:text='I am ordering a blood test.'
                rows.append({'utterance_id':target['utterance_id'],'text':text})
            return json.dumps({'conversation':rows})
        return super().chat(task_type=task_type,model=model,messages=messages,**kwargs)


class PlaceholderTests(unittest.TestCase):
    def tearDown(self):set_gateway(None)
    def gateway(self,adapter):set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))

    def test_all_reserved_prefixes_are_blocked_without_recognized_names(self):
        for damaged in ('MF_MED_...','MF_MED_…','MF_MED_','MF_MED','mf_med_bad_4','MF-MED-…','MF _ MED _ ...','MF_MED_a1b2c3d4e5_0'):
            with self.subTest(damaged=damaged):
                self.assertTrue(has_medicine_placeholder(damaged))
                self.assertIn('unresolved_medicine_token',translation_issues('Blood test.',damaged,[]))
                self.assertTrue(check_turn('Blood test.',damaged)['issues'])
                self.assertIn('unresolved_medicine_token',soap_issues([{'text':'Blood test.'}],{'plan':damaged}))
        self.assertFalse(has_medicine_placeholder('Take Panadol.'))

    def test_exact_restore_only_never_guess_multiple_placeholder_positions(self):
        protected,rows=protect('Panadol and Motilium.','U1')
        self.assertEqual(restore(protected,rows),'Panadol and Motilium.')
        self.assertEqual(restore('MF_MED_... and MF_MED_...',rows),'MF_MED_... and MF_MED_...')

    def test_cleanup_rejects_placeholder_even_without_a_local_medicine_match(self):
        adapter=MockProviderAdapter();self.gateway(adapter)
        adapter.set_response('transcript_cleanup',{'transcript':'I am ordering MF_MED_... for you and another MF_MED_... tonight.'})
        source='I am ordering a blood test and a blood pressure check for you.'
        self.assertEqual(TranscriptCleaner().clean(source),source)

    def test_full_urdu_and_manifest_support_automatic_two_name_repair(self):
        adapter=ManifestAdapter();self.gateway(adapter)
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take MF_MED_... 500 mg. Stop MF_MED_...'},
            {'utterance_id':'U2','text':'Yes.'}]})
        source='پیناڈول 500 mg لیں۔ موٹیلیم بند کر دیں۔'
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source},
            {'utterance_id':'U2','speaker':'Attendant','speaker_relation':'Mother','text':'جی۔'}])
        self.assertEqual(result[0]['original_text'],source)
        self.assertEqual(result[0]['clinical_english'],'Take Panadol 500 mg. Stop Motilium.')
        self.assertEqual(result[0]['medicine_checks']['issues'],[])
        repair=next(c for c in adapter.calls if c['task_type']=='medicine_translation_repair')
        payload=json.loads(repair['messages'][-1]['content'])
        self.assertEqual(len(payload['complete_original_conversation']),2)
        self.assertEqual(payload['complete_original_conversation'][0]['original'],source)
        self.assertEqual(payload['complete_original_conversation'][1]['speaker_relation'],'Mother')
        self.assertEqual([r['allowed_english'] for r in payload['medicine_manifest']],['Panadol','Motilium'])
        translation=next(c for c in adapter.calls if c['task_type']=='translation')
        self.assertIn(source,translation['messages'][-1]['content']);self.assertIn('medicine_manifest',translation['messages'][-1]['content'])
        self.assertEqual(soap_issues(result,{'plan':result[0]['clinical_english']}),[])

    def test_repair_failure_preserves_original_never_displays_identifier_as_translation(self):
        for mode in ('offline','damaged','dose','swap'):
            adapter=ManifestAdapter(mode);self.gateway(adapter)
            adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take MF_MED_...'}]})
            source='پیناڈول 500 mg لیں۔ موٹیلیم بند کر دیں۔'
            result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source}])[0]
            self.assertEqual(result['original_text'],source)
            self.assertIn('[Translation requires review]',result['clinical_english'])
            self.assertFalse(has_medicine_placeholder(result['clinical_english']))
            self.assertTrue(result['medicine_checks']['issues'])

    def test_hallucinated_marker_without_any_source_drug_can_be_retranslated(self):
        adapter=ManifestAdapter();self.gateway(adapter)
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'I am ordering MF_MED_...'}]})
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':'Blood test.'}])[0]
        self.assertEqual(result['clinical_english'],'I am ordering a blood test.')
        self.assertEqual(result['medicine_checks']['issues'],[])

    def test_corrupt_original_cannot_be_attested_or_approved_away(self):
        source='Take MF_MED_...'
        self.assertIn('source_medicine_placeholder',check_turn(source,'Take Panadol.')['issues'])
        with self.assertRaises(ValueError):clinician_review(source,source,{},'doctor:QA')
        self.assertIn('source_medicine_placeholder',soap_issues([{'text':source}],{'plan':'Take Panadol.'}))

    def test_provider_fallback_never_presents_corrupt_identifier_as_english(self):
        self.gateway(MockProviderAdapter())
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':'Take MF_MED_...'}])[0]
        self.assertEqual(result['original_text'],'Take MF_MED_...')
        self.assertFalse(has_medicine_placeholder(result['clinical_english']))
        self.assertIn('source_medicine_placeholder',result['medicine_checks']['issues'])

    def test_uncertain_suggestion_remains_doctor_review_after_automatic_repair(self):
        adapter=ManifestAdapter();self.gateway(adapter)
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'MF_MED_...'}]})
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':'پینڈول لیں۔'}])[0]
        self.assertEqual(result['clinical_english'],'Take Panadol.')
        self.assertEqual(result['medicine_checks']['issues'],['name_confirmation_required'])
        review=clinician_review(result['original_text'],result['clinical_english'],{},'doctor:QA',analysis=result['medicine_suggestions'])
        self.assertEqual(check_turn(result['original_text'],result['clinical_english'],review,analysis=result['medicine_suggestions'])['issues'],[])


class SavedRecoveryTests(unittest.TestCase):
    setUp=guided.GuidedConsultationTests.setUp;tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture;context=guided.GuidedConsultationTests.context;revision=guided.GuidedConsultationTests.revision

    def damaged(self,original='Take MF_MED_...',english='Take MF_MED_...',raw='پیناڈول لیں۔'):
        self.capture();body=self.revision();source=self.c.transcript_repository.get(body['transcript_id'])
        turns=[TranscriptUtterance(transcript_id=source.transcript_id,utterance_id='U1',speaker=Speaker.DOCTOR,
            original_text=original,clinical_english=english)]
        self.c.transcript_repository.save(source.model_copy(update={'utterances':turns,'raw_asr_text':raw}))
        return body

    def test_saved_corrupt_original_recovers_from_raw_asr_as_new_revision(self):
        body=self.damaged();seen=[]
        def roles(text,*,patient,transcript_id):
            seen.append(text);return [TranscriptUtterance(transcript_id=transcript_id,utterance_id='U1',speaker=Speaker.DOCTOR,original_text=text)]
        adapter=ManifestAdapter();set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take Panadol.'}]})
        with patch.object(self.c.documentation_service,'diarize',side_effect=roles):
            response=self.client.post(self.path+'/repair-medicines',json=body)
        self.assertEqual(response.status_code,200,response.text)
        current=response.json()['conversation_review'];self.assertEqual(current['revision'],2)
        self.assertNotEqual(current['transcript_id'],body['transcript_id']);self.assertEqual(seen,['پیناڈول لیں۔'])
        self.assertEqual(current['utterances'][0]['clinical_english'],'Take Panadol.')
        self.assertEqual(self.c.transcript_repository.get(body['transcript_id']).utterances[0].original_text,'Take MF_MED_...')
        self.assertIsNone(response.json()['note'])
        self.assertEqual(self.client.post(self.path+'/repair-medicines',json=body).status_code,409)

    def test_english_only_repair_preserves_unaffected_doctor_confirmation(self):
        body=self.damaged(original='پیناڈول لیں۔');source=self.c.transcript_repository.get(body['transcript_id'])
        second=TranscriptUtterance(transcript_id=source.transcript_id,utterance_id='U2',speaker=Speaker.DOCTOR,
            original_text='موٹیلیم نہ لیں۔',clinical_english='Do not take Motilium.',
            medicine_review=clinician_review('موٹیلیم نہ لیں۔','Do not take Motilium.',{},self.actor.ref))
        self.c.transcript_repository.save(source.model_copy(update={'utterances':source.utterances+[second]}))
        adapter=MockProviderAdapter();set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take Panadol.'},{'utterance_id':'U2','text':'Wrong fresh translation.'}]})
        with patch.object(self.c.documentation_service,'diarize') as roles:
            response=self.client.post(self.path+'/repair-medicines',json=body)
        self.assertEqual(response.status_code,200,response.text);roles.assert_not_called()
        current=response.json()['conversation_review']['utterances'][1]
        self.assertEqual(current['clinical_english'],second.clinical_english)
        self.assertEqual(current['medicine_review'],second.medicine_review)

    def test_no_raw_source_no_guess_and_no_revision_change(self):
        body=self.damaged(raw='');response=self.client.post(self.path+'/repair-medicines',json=body)
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.revision(),body)
        self.assertNotEqual(self.client.post(self.path+'/generate-soap',json=body).status_code,200)

    def test_recovery_outage_preserves_checkpoint_and_allows_retry(self):
        body=self.damaged(original='پیناڈول لیں۔')
        with patch.object(self.c.documentation_service,'translate',side_effect=RuntimeError('Synthetic outage')):
            failed=self.client.post(self.path+'/repair-medicines',json=body)
        self.assertEqual(failed.status_code,503,failed.text)
        self.assertEqual(self.revision(),body);self.assertEqual(self.context()['conversation_review']['status'],'TRANSCRIPT_REVIEW')

    def test_incomplete_model_recovery_does_not_replace_saved_revision(self):
        body=self.damaged(original='پیناڈول لیں۔')
        source=self.c.transcript_repository.get(body['transcript_id'])
        fallback=[source.utterances[0].model_copy(update={'clinical_english':'[Translation requires review] پیناڈول لیں۔'})]
        with patch.object(self.c.documentation_service,'translate',return_value=fallback):
            failed=self.client.post(self.path+'/repair-medicines',json=body)
        self.assertEqual(failed.status_code,503,failed.text);self.assertEqual(self.revision(),body)

    def test_recovery_requires_assigned_doctor(self):
        body=self.damaged();self.client.post('/api/auth/logout')
        self.assertEqual(self.client.post(self.path+'/repair-medicines',json=body).status_code,401)
        self.c.auth_repository.create_doctor('Other','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.post(self.path+'/repair-medicines',json=body).status_code,403)

    def test_diarization_cannot_introduce_malformed_markers_without_source_match(self):
        fake=Mock();fake.diarize_transcript.return_value=[{'speaker':'Doctor','text':'Blood test MF_MED_...'}]
        with patch.object(self.c.documentation_service,'_components',return_value=(fake,None,None)):
            turns=self.c.documentation_service.diarize('Blood test and blood pressure check.',patient=self.patient,transcript_id='TRN-QA')
        self.assertEqual(turns[0].original_text,'Blood test and blood pressure check.')
        self.assertEqual(turns[0].speaker,Speaker.UNKNOWN)
