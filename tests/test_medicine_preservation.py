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
from tests.test_soap_quality import SequenceAdapter,load_soap_module


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


class MedicineWorkflowTests(unittest.TestCase):
    setUp=guided.GuidedConsultationTests.setUp
    tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture
    context=guided.GuidedConsultationTests.context
    revision=guided.GuidedConsultationTests.revision

    def test_role_assignment_cannot_rewrite_medicine_source(self):
        from unittest.mock import Mock
        wrong=Mock();wrong.diarize_transcript.return_value=[{'speaker':'Doctor','text':'میں آپ کو درد کی دوا دے رہا ہوں۔'}]
        with patch.object(self.c.documentation_service,'_components',return_value=(wrong,None,None)):
            turns=self.c.documentation_service.diarize('میں آپ کو پیناڈول دے رہا ہوں۔',patient=self.patient,transcript_id='TRN-SYNTHETIC')
        self.assertIn('MF_MED_',wrong.diarize_transcript.call_args.args[0])
        self.assertEqual(turns[0].original_text,'میں آپ کو پیناڈول دے رہا ہوں۔')
        self.assertEqual(turns[0].speaker,Speaker.UNKNOWN);self.assertTrue(turns[0].needs_review)

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
