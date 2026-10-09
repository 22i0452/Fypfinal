"""Synthetic spelling/translation/workflow regressions, not ASR accuracy tests."""
import re
import unittest
from unittest.mock import patch
from medflow.medicines import (mentions,protect,restore,check_turn,translation_issues,
    clinician_review,soap_issues,vocabulary)
from security_guardrails import SecureLLMGateway,set_gateway
from scribe.translator import MedicalTranslator
from scribe.transcript_cleaner import TranscriptCleaner
from app.services.documentation_service import TranscribedText
from medflow.domain.enums import Speaker
from medflow.domain.models import TranscriptUtterance
from tests import test_guided_consultation as guided
from tests.test_soap_quality import SequenceAdapter,FailingAdapter,load_soap_module


class MedicinePreservationTests(unittest.TestCase):
    def tearDown(self):set_gateway(None)

    def translate(self,source,answer):
        gateway=SecureLLMGateway(provider='mock');adapter=gateway._adapter('mock')
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':answer}]})
        set_gateway(gateway)
        return MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source}])[0]

    def test_catalogue_has_sources_and_no_prescribing_fields(self):
        for entry in vocabulary()['entries']:
            self.assertNotIn('dose',entry);self.assertNotIn('ingredient',entry)
            if entry['status']=='catalog_name':self.assertTrue(entry['source_url'].startswith('https://'))

    def test_urdu_alias_longest_variant_and_diacritics(self):
        self.assertEqual([row['name'] for row in mentions('پیناڈول ایکسٹرا اور موٹیلیم')],['Panadol Extra','Motilium'])
        self.assertEqual(mentions('پِیناڈول')[0]['name'],'Panadol')

    def test_short_medicine_name_is_protected(self):
        source,rows=protect('پیناڈول','U1')
        self.assertEqual(restore(source,rows),'Panadol')
        self.assertEqual(restore(source,rows,english=False),'پیناڈول')

    def test_tokens_restore_real_name_without_generics(self):
        source='میں آپ کو پیناڈول 500 mg دے رہا ہوں۔';protected,rows=protect(source,'U1')
        token=rows[0]['token']
        result=self.translate(source,'I am giving you '+token+' 500 mg.')
        self.assertEqual(result['clinical_english'],'I am giving you Panadol 500 mg.')
        self.assertEqual(result['medicine_checks']['issues'],[])

    def test_panadol_cannot_become_painkiller_or_ingredient(self):
        for target in ('Take painkillers.','Take paracetamol.'):
            result=self.translate('پیناڈول لیں۔',target)
            self.assertIn('پیناڈول',result['clinical_english'])
            self.assertNotIn(target,result['clinical_english'])
            self.assertTrue(result['medicine_checks']['issues'])

    def test_fixage_cannot_become_fixed(self):
        result=self.translate('فکسج دوائی لیں۔','Take fixed medicine.')
        self.assertIn('فکسج',result['clinical_english']);self.assertTrue(result['medicine_checks']['issues'])

    def test_missing_id_cannot_attach_other_medicine_turn(self):
        result=self.translate('پیناڈول لیں۔','Take Panadol.')
        self.assertFalse(result['medicine_checks']['issues'])
        gateway=SecureLLMGateway(provider='mock');gateway._adapter('mock').set_response('translation',{'conversation':[{'utterance_id':'OTHER','text':'Take Panadol.'}]});set_gateway(gateway)
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':'پیناڈول لیں۔'}])[0]
        self.assertIn('Translation requires review',result['clinical_english'])

    def test_cleanup_cannot_destroy_correct_urdu_medicine(self):
        gateway=SecureLLMGateway(provider='mock');gateway._adapter('mock').set_response('transcript_cleanup',{'transcript':'میں آپ کو پین کلرز دے رہا ہوں روز صبح لیں۔'});set_gateway(gateway)
        source='میں آپ کو پیناڈول دے رہا ہوں روز صبح لیں۔'
        self.assertEqual(TranscriptCleaner().clean(source),source)

    def test_context_unknown_is_preserved_and_generic_phrase_does_not_invent(self):
        self.assertEqual(mentions('میں آپ کو دوا دے رہا ہوں۔'),[])
        row=mentions('Zorbex medicine')[0];self.assertEqual(row['status'],'context_candidate')
        self.assertTrue(check_turn('Zorbex medicine','Zorbex medicine')['issues'])

    def test_unknown_spelling_requires_exact_revision_attestation(self):
        source='فکسج دوائی لیں۔';target='Take Fixage medicine.'
        review=clinician_review(source,target,{'فکسج':'Fixage'},'D:test')
        self.assertEqual(check_turn(source,target,review)['issues'],[])
        self.assertTrue(check_turn(source,'Take fixed medicine.',review)['issues'])

    def test_known_medicine_cannot_be_acknowledged_away(self):
        with self.assertRaises(ValueError):clinician_review('پیناڈول لیں۔','Take painkillers.',{},'D:test')
        with self.assertRaises(ValueError):clinician_review('پیناڈول لیں۔','Take Motilium.',{'پیناڈول':'Motilium'},'D:test')

    def test_doses_arabic_digits_and_dose_swap(self):
        self.assertEqual(translation_issues('پیناڈول ۵۰۰ ملی گرام','Panadol 500 mg'),[])
        self.assertIn('medicine_dose_link_changed',translation_issues('Panadol 500 mg and Motilium 10 mg.','Panadol 10 mg and Motilium 500 mg.'))

    def test_negation_and_new_medicine_are_flagged(self):
        self.assertIn('negation_or_stopping_changed',translation_issues('پیناڈول نہ لیں۔','Take Panadol.'))
        self.assertIn('medicine_introduced',translation_issues('پیناڈول لیں۔','Take Panadol and Motilium.'))
        self.assertIn('medicine_negation_link_changed',translation_issues('Do not take Panadol. Take Motilium.','Take Panadol. Do not take Motilium.'))

    def test_soap_identity_dose_and_negation(self):
        self.assertIn('soap_medicine_missing:Panadol',soap_issues([{'text':'Take Panadol.'}],{'plan':'Take painkillers.'}))
        self.assertIn('soap_medicine_dose_changed:Panadol',soap_issues([{'text':'Take Panadol 500 mg.'}],{'plan':'Take Panadol 10 mg.'}))
        self.assertIn('soap_medicine_negation_changed:Panadol',soap_issues([{'text':'Do not take Panadol.'}],{'plan':'Take Panadol.'}))

    def test_generator_retries_then_preserves_source_in_fallback(self):
        bad={'subjective':'Not documented.','objective':'Not documented.','assessment':'Not documented.','plan':'Take painkillers.','evidence':[{'utterance_id':'U1','quote':'Take Panadol.'}]}
        adapter=SequenceAdapter([bad,bad]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        result=load_soap_module().SOAPGenerator().generate({},[{'utterance_id':'U1','speaker':'Doctor','text':'Take Panadol.'}])
        self.assertEqual(len(adapter.calls),2);self.assertIn('Panadol',result['plan'])
        self.assertEqual(soap_issues([{'text':'Take Panadol.'}],result),[])

    def fallback(self, turns):
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        return load_soap_module().SOAPGenerator().generate({},turns)

    def test_giving_and_prescribing_keep_names_doses_and_stop_instructions(self):
        for statement in ("I'm giving you Motilium 10 mg and Panadol 500 mg.",
                          'I am prescribing Panadol 500 mg. Do not take Motilium 10 mg.',
                          'I will give you Panadol 500 mg.'):
            with self.subTest(statement=statement):
                turns=[{'utterance_id':'U1','speaker':'Doctor','text':statement}]
                result=self.fallback(turns)
                self.assertIn(statement,result['plan'])
                self.assertEqual(soap_issues(turns,result),[])

    def test_approved_urdu_spelling_survives_fallback_normalization(self):
        source='پینانڈول دوائی لیں۔';english='Take panadol medicine.'
        review=clinician_review(source,english,{'پینانڈول':'panadol'},'D:test')
        turns=[{'utterance_id':'U1','speaker':'Doctor','text':english,
                'original_text':source,'clinical_english':english,'medicine_review':review}]
        result=self.fallback(turns)
        self.assertIn(english,result['plan'])
        self.assertEqual(soap_issues(turns,result),[])
        self.assertEqual(result['validation_issues'],['provider_error'])

    def test_unprompted_and_short_medicine_names_do_not_become_prescriptions(self):
        for speaker in ('Doctor','Nurse','Unknown','Patient','Attendant'):
            with self.subTest(speaker=speaker):
                turns=[{'utterance_id':'U1','speaker':speaker,'text':'Motilium',
                        'medicine_context':True}]
                result=self.fallback(turns)
                self.assertIn('Motilium',result['subjective'])
                self.assertNotIn('Motilium',result['plan'])
                self.assertEqual(soap_issues(turns,result),[])
                self.assertEqual(result['evidence'][0]['utterance_id'],'U1')

    def test_prevention_word_does_not_reject_otherwise_valid_soap(self):
        turns=[{'utterance_id':'U1','speaker':'Doctor','text':'Take Panadol to prevent fever.'}]
        good={'subjective':'Not documented.','objective':'Not documented.',
              'assessment':'Not documented.','plan':turns[0]['text'],
              'evidence':[{'utterance_id':'U1','quote':turns[0]['text']}]}
        adapter=SequenceAdapter([good]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        result=load_soap_module().SOAPGenerator().generate({},turns)
        self.assertEqual(result['generation_mode'],'MODEL_VALIDATED')
        self.assertEqual(soap_issues(turns,result),[])
        self.assertEqual(len(adapter.calls),1)

    def test_rejected_model_errors_are_separate_from_fallback_checks(self):
        turns=[{'utterance_id':'U1','speaker':'Doctor','text':'I am giving you Motilium.'}]
        bad={'subjective':'Not documented.','objective':'Not documented.',
             'assessment':'Not documented.','plan':'Not documented.',
             'evidence':[{'utterance_id':'U1','quote':turns[0]['text']}]}
        adapter=SequenceAdapter([bad,bad]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        result=load_soap_module().SOAPGenerator().generate({},turns)
        self.assertEqual(result['generation_mode'],'TRANSCRIPT_FALLBACK')
        self.assertIn('model_draft_rejected:soap_medicine_missing:Motilium',result['validation_issues'])
        self.assertNotIn('soap_medicine_missing:Motilium',result['validation_issues'])
        self.assertEqual(soap_issues(turns,result),[])
        self.assertEqual(len(adapter.calls),2)


class MedicineWorkflowTests(unittest.TestCase):
    setUp=guided.GuidedConsultationTests.setUp
    tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture
    context=guided.GuidedConsultationTests.context
    revision=guided.GuidedConsultationTests.revision

    def test_role_assignment_cannot_rewrite_medicine_source(self):
        from unittest.mock import Mock
        from scribe.llm_diarizer import LLMDiarizer
        wrong=Mock();wrong.diarize_transcript.return_value=[{'speaker':'Doctor','text':'میں آپ کو درد کی دوا دے رہا ہوں۔'}]
        # Recovery helpers come from the real diarizer so medicine text stays literal
        # while usable speaker roles are still recovered from the original ASR.
        real=LLMDiarizer()
        for name in ('_cue_based_diarize','_split_mixed_speaker_turns','_relabel_turns','_fallback_diarize','_infer_relations','_with_identity','_is_usable_diarization'):
            setattr(wrong,name,getattr(real,name))
        with patch.object(self.c.documentation_service,'_components',return_value=(wrong,None,None)):
            turns=self.c.documentation_service.diarize('میں آپ کو پیناڈول دے رہا ہوں۔',patient=self.patient,transcript_id='TRN-SYNTHETIC')
        self.assertIn('MF_MED_',wrong.diarize_transcript.call_args.args[0])
        self.assertEqual(turns[0].original_text,'میں آپ کو پیناڈول دے رہا ہوں۔')
        self.assertIn('پیناڈول',turns[0].original_text)
        self.assertNotIn('درد کی دوا',turns[0].original_text)
        self.assertEqual(turns[0].speaker,Speaker.DOCTOR)

    def medicine_capture(self,source,target,auto=False):
        def diarize(text,patient,transcript_id):
            return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,speaker=Speaker.DOCTOR,original_text=source)]
        gateway=SecureLLMGateway(provider='mock');gateway._adapter('mock').set_response('translation',{'conversation':[{'utterance_id':'U1','text':target}]});set_gateway(gateway)
        with patch.object(self.c.documentation_service,'transcribe',return_value=TranscribedText(source,source)),patch.object(self.c.documentation_service,'diarize',side_effect=diarize):
            return self.capture(auto)[0]

    def test_automatic_soap_stops_at_review_and_bad_name_cannot_bypass(self):
        result=self.medicine_capture('پیناڈول لیں۔','Take painkillers.',True)
        self.assertEqual(result['type'],'conversation_ready');self.assertIsNone(self.context()['note'])
        response=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['detail']['code'],'MEDICINE_REVIEW_REQUIRED')
        body={**self.revision(),'corrections':[{'utterance_id':'U1','clinical_english':'Take painkillers.','medicines_reviewed':True}]}
        response=self.client.patch(self.path+'/conversation',json=body)
        self.assertEqual(response.status_code,400);self.assertEqual(self.context()['conversation_review']['revision'],1)

    def test_confirm_unknown_then_generate_keep_original_asr(self):
        self.medicine_capture('فکسج دوائی لیں۔','Take fixed medicine.')
        first=self.revision()
        response=self.client.patch(self.path+'/conversation',json={**first,'corrections':[{'utterance_id':'U1','clinical_english':'Take Fixage medicine.','medicines_reviewed':True,'medicine_spellings':{'فکسج':'Fixage'}}]})
        self.assertEqual(response.status_code,200,response.text)
        review=response.json()['conversation_review'];self.assertFalse(review['medicine_report']['requires_review'])
        self.assertEqual(review['raw_asr_text'],'فکسج دوائی لیں۔')
        self.assertNotEqual(review['transcript_id'],first['transcript_id'])
        old=self.c.transcript_repository.get(first['transcript_id']);self.assertIn('Translation requires review',old.utterances[0].clinical_english)
        stale=self.client.post(self.path+'/generate-soap',json=first);self.assertEqual(stale.status_code,409)
        generated=self.client.post(self.path+'/generate-soap',json=self.revision());self.assertEqual(generated.status_code,200,generated.text)
        self.assertIn('Fixage',generated.json()['note']['soap']['plan'])

    def test_approved_spelling_and_prescription_survive_provider_failure(self):
        source='پینانڈول دوائی لیں۔'
        self.medicine_capture(source,'Take پینانڈول medicine.')
        response=self.client.patch(self.path+'/conversation',json={**self.revision(),
            'corrections':[{'utterance_id':'U1','clinical_english':"I'm giving you panadol medicine.",
                           'medicines_reviewed':True,'medicine_spellings':{'پینانڈول':'panadol'}}]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['conversation_review']['medicine_report']['requires_review'])
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        generated=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(generated.status_code,200,generated.text)
        soap=generated.json()['note']['soap']
        self.assertIn("I'm giving you panadol medicine.",soap['plan'])
        self.assertEqual(soap['medicine_report']['soap_issues'],[])
        self.assertFalse(soap['medicine_report']['requires_review'])
        warnings=' '.join(soap['structured_soap']['warnings'])
        self.assertIn('SOAP model request failed',warnings)
        self.assertNotIn('model draft was unavailable',warnings)
        self.assertEqual(self.context()['conversation_review']['raw_asr_text'],source)

    def test_validation_rejection_message_does_not_claim_provider_failure(self):
        self.medicine_capture('موٹیلیم لیں۔','Take Motilium.')
        bad={'subjective':'Not documented.','objective':'Not documented.',
             'assessment':'Not documented.','plan':'Not documented.',
             'evidence':[{'utterance_id':'U1','quote':'Take Motilium.'}]}
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':SequenceAdapter([bad,bad])}))
        response=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(response.status_code,200,response.text)
        soap=response.json()['note']['soap']
        self.assertEqual(soap['medicine_report']['soap_issues'],[])
        warnings=' '.join(soap['structured_soap']['warnings'])
        self.assertIn('Original model draft rejected',warnings)
        self.assertIn('medicine missing: Motilium',warnings)
        self.assertNotIn('SOAP model request failed',warnings)
        self.assertNotIn('model draft was unavailable',warnings)

    def test_soap_edit_cannot_remove_brand_and_approve(self):
        self.medicine_capture('پیناڈول لیں۔','Take Panadol.')
        response=self.client.post(self.path+'/generate-soap',json=self.revision());self.assertEqual(response.status_code,200,response.text)
        note=response.json()['note']['note_id'];service=self.c.note_lifecycle_service
        from app.services.documentation_service import DocumentationService
        _,version=service.get(note,actor=self.actor)
        sections={**DocumentationService.legacy_soap(version.soap),'plan':'Take painkillers.'}
        service.edit_legacy_sections(note,sections=sections,actor=self.actor)
        service.submit_for_review(note,actor=self.actor)
        from app.services.note_lifecycle_service import NoteLifecycleError
        with self.assertRaises(NoteLifecycleError) as caught:service.approve(note,actor=self.actor)
        self.assertEqual(caught.exception.code,'MEDICINE_REVIEW_REQUIRED')
        current,version=service.get(note,actor=self.actor);self.assertTrue(service.payload(current,version)['soap']['medicine_report']['soap_issues'])
        service.edit_legacy_sections(note,sections={**sections,'plan':'Take Panadol.'},actor=self.actor)
        service.submit_for_review(note,actor=self.actor);service.approve(note,actor=self.actor)


if __name__=='__main__':unittest.main()
