"""Synthetic catalogue/LLM contract tests. These do not measure ASR accuracy."""
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from medflow.medicine_matching import automatic_matches,candidates
from medflow.medicine_catalogue import catalogue,entries
from medflow.medicines import mentions,check_turn,clinician_review,fingerprint
from security_guardrails import SecureLLMGateway,set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter
from scribe.translator import MedicalTranslator
from tests import test_guided_consultation as guided
from medflow.domain.models import TranscriptUtterance
from medflow.domain.enums import Speaker
from app.services.documentation_service import TranscribedText


class MatchingAdapter(MockProviderAdapter):
    def __init__(self,mode='valid'):
        super().__init__();self.mode=mode;self.task_order=[]

    def chat(self,*,task_type,model,messages,**kwargs):
        self.task_order.append(task_type)
        if task_type=='medicine_context':
            self.calls.append({'task_type':task_type,'messages':messages})
            if self.mode=='offline':raise RuntimeError('Synthetic unavailable provider')
            return json.dumps({'entities':[]})
        if task_type=='medicine_lookup_query':
            self.calls.append({'task_type':task_type,'messages':messages})
            if self.mode=='offline':raise RuntimeError('Synthetic unavailable provider')
            jobs=json.loads(messages[-1]['content'])['mentions']
            return json.dumps({'queries':[{'mention_id':job['mention_id'],'latin_spellings':
                ['NoSuchMadeUpBrandzzzz'] if self.mode=='invented' else ['Glucophage'] if job['recognized']=='گلوکوفیج' else []} for job in jobs]})
        if task_type=='medicine_matching':
            self.calls.append({'task_type':task_type,'messages':messages})
            if self.mode=='offline':raise RuntimeError('Synthetic unavailable provider')
            jobs=json.loads(messages[-1]['content'])['mentions'];rows=[]
            for job in jobs:
                target=next((row for row in job['candidates'] if row['name']=='Motilium'),job['candidates'][0])
                selected=target['catalog_id'] if self.mode!='invented' else 'INVENTED'
                if self.mode=='wrong_turn':selected='PK_OTHER_TURN'
                if self.mode=='null':selected=None
                row={'mention_id':job['mention_id'],'catalog_id':selected,'medicine_context':self.mode!='non_medical','usage':'reported' if job['speaker']=='Patient' else 'prescribed'}
                if self.mode=='string_bool':row['medicine_context']='true'
                rows.append(row)
                if self.mode=='duplicate':rows.append(row)
            return json.dumps({'matches':rows})
        if task_type=='medicine_translation_repair':
            self.calls.append({'task_type':task_type,'messages':messages})
            rows=json.loads(messages[-1]['content'])['conversation']
            # Test fixture copies every source token, not a guessed real hearing.
            return json.dumps({'conversation':[{'utterance_id':row['utterance_id'],
                'text':'Take '+re.search(r'MF_MED_\w+',row['original']).group()+(' 10 mg.' if self.mode=='bad_dose' else ' 500 mg.')}
                for row in rows]})
        return super().chat(task_type=task_type,model=model,messages=messages,**kwargs)


class AutomaticMatchingTests(unittest.TestCase):
    def tearDown(self):set_gateway(None)
    def setup_adapter(self,mode='valid'):
        adapter=MatchingAdapter(mode);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}));return adapter
    def turns(self):return [{'utterance_id':'U1','speaker':'Doctor','original_text':'Take mortiiduom 10 mg.','clinical_english':'Take mortiiduom 10 mg.'}]

    def test_attached_catalogue_provenance_and_no_prescribing_fields(self):
        data=catalogue();self.assertEqual(data['source']['data_rows'],18952)
        self.assertEqual(data['source']['sha256'],'fed04e3b7f4d3821ea1761507f2ca2ffd3ed96caf9f21ef8aa6d67e70360856a')
        self.assertGreater(len(entries()),8500);self.assertTrue(data['source']['quarantined_rows'])
        for row in entries():
            self.assertNotIn('strength',row);self.assertNotIn('dose',row);self.assertNotIn('ingredient',row)
            self.assertTrue(row['source_rows'])

    def test_sound_candidates_include_motilium_without_duplicates(self):
        for text in ['mortiiduom','mortiloun','moratorium','موٹیلوم']:
            self.assertIn('Motilium',[row['name'] for row in candidates(text)])
        names=[row['name'].casefold() for row in candidates('panadole')]
        self.assertEqual(len(names),len(set(names)))

    def test_long_mixed_consultation_keeps_full_context_and_reranks_only_uncertain_names(self):
        adapter=self.setup_adapter()
        turns=[{'utterance_id':f'U{i}','speaker':'Doctor','original_text':'Take Panadol and mortiiduom. '+('Full source sentence. '*100)} for i in range(25)]
        outputs=automatic_matches(turns)
        self.assertEqual(adapter.task_order,['medicine_context','medicine_matching'])
        for call in adapter.calls:
            payload=json.loads(call['messages'][-1]['content'])
            self.assertEqual([row['original'] for row in payload['conversation']],[row['original_text'] for row in turns])
        matching=json.loads(adapter.calls[-1]['messages'][-1]['content'])['mentions']
        self.assertEqual(len(matching),25)
        self.assertTrue(all(row['recognized']=='mortiiduom' for row in matching))
        self.assertTrue(all(result['mentions'][0]['status']=='exact_preserved' for result in outputs.values()))
        self.assertTrue(all(result['mentions'][1]['status']=='suggested' for result in outputs.values()))

    def test_brand_variant_and_new_csv_brand_are_exact(self):
        self.assertEqual([row['name'] for row in mentions('Take Panadol Extend 500 mg.')],['Panadol Extend'])
        self.assertEqual([row['name'] for row in mentions('Take Glucophage 500 mg.')],['Glucophage'])
        self.assertEqual([row['name'] for row in mentions('Take Amoxicillin medicine.')],['Amoxicillin'])
        self.assertTrue(check_turn('Take Glucophage 500 mg.','Take painkillers 500 mg.')['issues'])
        self.assertEqual(mentions('Glucophage')[0]['name'],'Glucophage')
        self.assertEqual(mentions('Glucophage 500 mg')[0]['name'],'Glucophage')

    def test_legacy_input_without_turn_ids_still_runs(self):
        self.setup_adapter()
        result=MedicalTranslator().translate_conversation([{'speaker':'Doctor','text':'Take Panadol.'}])
        self.assertEqual(result[0]['utterance_id'],'U1')

    def test_ordinary_word_and_sentence_boundary_do_not_invent(self):
        self.assertEqual(mentions('There is a moratorium on new clinics.'),[])
        self.assertEqual([row['name'] for row in mentions('Maintain hydration. Take Paracetamol 500 mg every six hours.')],['Paracetamol'])
        self.assertEqual([row['name'] for row in mentions('Take Panadol for severe headache.')],['Panadol'])

    def test_prevent_verb_does_not_become_catalogue_brand(self):
        for sentence in ('Take Panadol to prevent fever.',
                         'Take Motilium to prevent severe vomiting.',
                         'Take Panadol to prevent your symptoms getting worse.',
                         'Take medicine to prevent infection.',
                         'Do not take Panadol to prevent complications.'):
            with self.subTest(sentence=sentence):
                self.assertFalse(any(row['source'].casefold() == 'prevent' for row in mentions(sentence)))
        self.assertEqual(mentions('Prevent vomiting.',context=True),[])

    def test_explicit_prevent_brand_is_still_detected(self):
        for sentence in ('Take PREVENT 10 mg.', 'Take Prevent medicine.', 'PREVENT'):
            with self.subTest(sentence=sentence):
                self.assertEqual([row['name'] for row in mentions(sentence)],['PREVENT'])

    def test_automatic_llm_suggestion_is_not_confirmation(self):
        adapter=self.setup_adapter();result=automatic_matches(self.turns())['U1']
        self.assertEqual(adapter.task_order,['medicine_context','medicine_matching'])
        item=result['mentions'][0];chosen=next(c for c in item['candidates'] if c['catalog_id']==item['selected_catalog_id'])
        self.assertEqual(chosen['name'],'Motilium');self.assertEqual(item['status'],'suggested')
        self.assertIn('name_confirmation_required',check_turn(self.turns()[0]['original_text'],self.turns()[0]['clinical_english'])['issues'])
        self.assertNotIn('confidence',item)

    def test_invalid_invented_duplicate_or_non_medical_llm_output_is_not_applied(self):
        for mode in ['invented','duplicate','non_medical','null','wrong_turn','string_bool']:
            with self.subTest(mode=mode):
                self.setup_adapter(mode);item=automatic_matches(self.turns())['U1']['mentions'][0]
                self.assertIsNone(item['selected_catalog_id']);self.assertEqual(item['status'],'uncertain')

    def test_provider_outage_keeps_local_candidates_and_original_review(self):
        self.setup_adapter('offline');result=automatic_matches(self.turns())['U1']
        self.assertEqual(result['status'],'llm_unavailable');self.assertTrue(result['mentions'][0]['candidates'])
        self.assertIsNone(result['mentions'][0]['selected_catalog_id'])

    def test_unfamiliar_urdu_uses_automatic_search_query_before_catalogue_check(self):
        adapter=self.setup_adapter()
        result=automatic_matches([{'utterance_id':'U1','speaker':'Doctor','original_text':'گلوکوفیج دوائی لیں۔'}])['U1']
        self.assertEqual(adapter.task_order,['medicine_context','medicine_lookup_query','medicine_matching'])
        item=next(row for row in result['mentions'] if row['source']=='گلوکوفیج')
        choice=next(row for row in item['candidates'] if row['catalog_id']==item['selected_catalog_id'])
        self.assertEqual(choice['name'],'Glucophage');self.assertEqual(item['lookup_method'],'automatic transliteration query')
        self.assertTrue(check_turn('گلوکوفیج دوائی لیں۔','Take گلوکوفیج medicine.')['issues'])

    def test_urdu_prescribing_sentence_is_context_without_invented_name(self):
        self.setup_adapter();source='میں آپ کو گلوکوفیج دے رہا ہوں۔'
        result=automatic_matches([{'utterance_id':'U1','speaker':'Doctor','original_text':source}])['U1']
        self.assertTrue(any(row['source']=='گلوکوفیج' and row['selected_catalog_id'] for row in result['mentions']))
        self.assertEqual(mentions('میں آپ کو دوا دے رہا ہوں۔'),[])

    def test_short_answer_inherits_medicine_question_context(self):
        adapter=self.setup_adapter()
        turns=[{'utterance_id':'U0','speaker':'Doctor','original_text':'Which medicine do you take?'},
            {'utterance_id':'U1','speaker':'Patient','original_text':'mortiiduom','medicine_context':True}]
        result=automatic_matches(turns)['U1'];self.assertEqual(result['mentions'][0]['status'],'suggested')
        jobs=json.loads(next(call for call in adapter.calls if call.get('task_type')=='medicine_matching')['messages'][-1]['content'])['mentions']
        self.assertEqual(next(row for row in jobs if row['recognized']=='mortiiduom')['previous_turn'],'Which medicine do you take?')
        self.assertTrue(check_turn('mortiiduom','mortiiduom',context=True)['issues'])

    def test_matching_runs_before_translation_and_correct_urdu_is_repaired(self):
        adapter=self.setup_adapter();adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take painkillers 500 mg.'}]})
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','original_text':'پیناڈول 500 mg لیں۔'}])[0]
        self.assertEqual(adapter.task_order,['medicine_context','translation','medicine_translation_repair'])
        self.assertEqual(result['original_text'],'پیناڈول 500 mg لیں۔');self.assertEqual(result['clinical_english'],'Take Panadol 500 mg.')
        self.assertEqual(result['medicine_checks']['issues'],[])
        self.assertEqual(result['medicine_suggestions']['fingerprint'],fingerprint(result['original_text'],result['clinical_english']))

    def test_bad_repair_dose_is_rejected(self):
        adapter=self.setup_adapter('bad_dose');adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':'Take painkillers 500 mg.'}]})
        result=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','original_text':'پیناڈول 500 mg لیں۔'}])[0]
        self.assertIn('Translation requires review',result['clinical_english']);self.assertNotIn('10 mg',result['clinical_english'])

    def test_catalogue_candidate_confirmation_preserves_dose_and_negation(self):
        source='Do not take mortiiduom 10 mg.';target='Do not take Motilium 10 mg.'
        review=clinician_review(source,target,{'mortiiduom':'Motilium'},'D:synthetic')
        self.assertEqual(check_turn(source,target,review)['issues'],[])
        with self.assertRaises(ValueError):clinician_review(source,'Take Motilium 10 mg.',{'mortiiduom':'Motilium'},'D:synthetic')
        with self.assertRaises(ValueError):clinician_review(source,'Do not take Motilium 500 mg.',{'mortiiduom':'Motilium'},'D:synthetic')


class MatchingWorkflowTests(unittest.TestCase):
    setUp=guided.GuidedConsultationTests.setUp
    tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture
    context=guided.GuidedConsultationTests.context
    revision=guided.GuidedConsultationTests.revision

    def test_suggestion_is_saved_confirmed_and_carried_into_soap_with_source(self):
        source='Take mortiiduom 10 mg.'
        adapter=MatchingAdapter();adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':source}]})
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        def diarize(text,patient,transcript_id):
            return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,speaker=Speaker.DOCTOR,original_text=source)]
        with patch.object(self.c.documentation_service,'transcribe',return_value=TranscribedText(source,source)),patch.object(self.c.documentation_service,'diarize',side_effect=diarize):
            result,_=self.capture(True)
        self.assertEqual(result['type'],'conversation_ready')
        before=self.context()['conversation_review'];self.assertEqual(before['utterances'][0]['medicine_suggestions']['mentions'][0]['status'],'suggested')
        first=self.revision();blocked=self.client.post(self.path+'/generate-soap',json=first);self.assertEqual(blocked.status_code,409)
        response=self.client.patch(self.path+'/conversation',json={**first,'corrections':[{'utterance_id':'U1','clinical_english':'Take Motilium 10 mg.','medicines_reviewed':True,'medicine_spellings':{'mortiiduom':'Motilium'}}]})
        self.assertEqual(response.status_code,200,response.text);review=response.json()['conversation_review']
        self.assertFalse(review['medicine_report']['requires_review']);self.assertEqual(review['raw_asr_text'],source)
        self.assertEqual(review['utterances'][0]['medicine_suggestions'],{}) # stale automatic result hidden
        self.assertEqual(self.c.transcript_repository.get(first['transcript_id']).utterances[0].original_text,source)
        response=self.client.post(self.path+'/generate-soap',json=self.revision());self.assertEqual(response.status_code,200,response.text)
        self.assertIn('Motilium 10 mg',response.json()['note']['soap']['plan'])

    def test_symptom_reference_updates_on_correction_without_writing_a_diagnosis(self):
        source='I have itching, skin rash and nodal skin eruptions.'
        adapter=MatchingAdapter();adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':source}]})
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        def diarize(text,patient,transcript_id):
            return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,speaker=Speaker.PATIENT,original_text=source)]
        with patch.object(self.c.documentation_service,'transcribe',return_value=TranscribedText(source,source)),patch.object(self.c.documentation_service,'diarize',side_effect=diarize):self.capture()
        first=self.revision();old=self.c.transcript_repository.get(first['transcript_id'])
        self.assertTrue(old.symptom_patterns['matches'])
        text='No itching, skin rash or nodal skin eruptions.'
        response=self.client.patch(self.path+'/conversation',json={**first,'corrections':[{'utterance_id':'U1','original_text':text,'clinical_english':text}]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['conversation_review']['symptom_patterns']['matches'],[])
        self.assertTrue(self.c.transcript_repository.get(first['transcript_id']).symptom_patterns['matches'])
        generated=self.client.post(self.path+'/generate-soap',json=self.revision());self.assertEqual(generated.status_code,200,generated.text)
        soap=generated.json()['note']['soap'];self.assertEqual(soap['symptom_patterns']['matches'],[])
        self.assertNotIn('Fungal infection',soap['assessment'])


if __name__=='__main__':unittest.main()
