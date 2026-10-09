"""Full-context contracts and screenshot regressions with synthetic providers."""
import json
import unittest
from unittest.mock import patch

from medflow.medicine_matching import automatic_matches
from medflow.medicine_context import analyze, source_fingerprint, context_fingerprint
from medflow.medicines import check_turn, clinician_review, soap_issues, mentions
from scribe.translator import MedicalTranslator
from security_guardrails import SecureLLMGateway, set_gateway
from tests.test_medicine_matching import MatchingAdapter
from tests.test_soap_quality import FailingAdapter, SequenceAdapter, load_soap_module
from tests import test_guided_consultation as guided
from app.services.documentation_service import TranscribedText
from medflow.domain.models import TranscriptUtterance
from medflow.domain.enums import Speaker


class ContextAdapter(MatchingAdapter):
    def chat(self, *, task_type, model, messages, **kwargs):
        if task_type=='medicine_context':
            self.task_order.append(task_type)
            self.calls.append({'task_type':task_type,'messages':messages})
            if self.mode=='context_offline':raise RuntimeError('Synthetic context failure')
            payload=json.loads(messages[-1]['content']);entities=[]
            for turn in payload['conversation']:
                text=turn['original']
                for source,kind in [('advance','non_medical'),('ٹیسٹ','non_medical'),
                                    ('پینڈول','medicine'),('Zin Zin','medicine'),('Panadol','medicine')]:
                    if source not in text:continue
                    start=text.index(source)
                    entities.append({'utterance_id':turn['utterance_id'],'source':source,
                                     'start':start,'end':start+len(source),
                                     'kind':'non_medical' if self.mode=='drop_known' else kind})
            if self.mode=='duplicate':entities=entities+entities
            if self.mode=='invented':entities=[{'utterance_id':'U1','source':'InventedMedicine','start':0,'end':16,'kind':'medicine'}]
            return json.dumps({'entities':entities})
        if task_type=='medicine_lookup_query':
            jobs=json.loads(messages[-1]['content'])['mentions']
            if any(job['recognized']=='پینڈول' for job in jobs):
                self.task_order.append(task_type);self.calls.append({'task_type':task_type,'messages':messages})
                return json.dumps({'queries':[{'mention_id':job['mention_id'],'latin_spellings':['Panadol']}
                    for job in jobs if job['recognized']=='پینڈول']})
        return super().chat(task_type=task_type,model=model,messages=messages,**kwargs)


class ContextMedicineTests(unittest.TestCase):
    def tearDown(self):set_gateway(None)

    def test_context_fingerprint_includes_relation_and_addressee(self):
        turn={'utterance_id':'U1','speaker':'DOCTOR','original_text':'Give Panadol.'}
        original=context_fingerprint([turn])
        self.assertNotEqual(original,context_fingerprint([{**turn,'addressed_to':'NURSE'}]))
        self.assertNotEqual(original,context_fingerprint([{**turn,'speaker_relation':'mother'}]))

    def setup(self, mode='valid'):
        adapter=ContextAdapter(mode);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        return adapter

    def test_entire_long_consultation_exact_names_need_only_context_request(self):
        adapter=self.setup()
        turns=[{'utterance_id':f'U{i}','speaker':'Doctor' if i%2 else 'Patient',
                'original_text':'Take Panadol. '+('Complete source context sentence. '*100)} for i in range(25)]
        output=automatic_matches(turns,patient_context={'age':'22','current_complaint':'Abdominal pain'})
        self.assertEqual(adapter.task_order,['medicine_context'])
        for call in adapter.calls:
            payload=json.loads(call['messages'][-1]['content'])
            self.assertEqual(len(payload['conversation']),25)
            self.assertEqual([t['original'] for t in payload['conversation']],[t['original_text'] for t in turns])
        self.assertEqual(len(output),25)
        self.assertTrue(all(result['context_status']=='complete' for result in output.values()))
        self.assertTrue(all(result['mentions'][0]['status']=='exact_preserved' for result in output.values()))
        self.assertTrue(all(result['mentions'][0]['usage']=='uncertain' for result in output.values()))

    def test_nonmedicine_decision_is_used_by_translation_review_and_soap(self):
        adapter=self.setup();source='We can advance the medicine review.'
        self.assertTrue(mentions(source))  # Advance is also a catalogue brand.
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':source}]})
        turn=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source}])[0]
        self.assertEqual(turn['clinical_english'],source)
        self.assertEqual(turn['medicine_checks']['mentions'],[])
        self.assertEqual(turn['medicine_checks']['issues'],[])
        self.assertEqual(soap_issues([turn],{'plan':source}),[])

    def test_diagnostic_word_from_screenshot_does_not_require_medicine_approval(self):
        adapter=self.setup();source='چلو میں آپ کو ٹیسٹ لکھ کے دے رہا ہوں بلڈ ٹیسٹ کرو ایک ذیابیطس کا بھی ٹیسٹ کرو۔'
        english='Have a blood test and a diabetes test done.'
        adapter.set_response('translation',{'conversation':[{'utterance_id':'U1','text':english}]})
        turn=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source}])[0]
        self.assertEqual(turn['medicine_checks']['issues'],[])
        self.assertEqual(turn['medicine_checks']['mentions'],[])
        self.assertEqual(turn['clinical_english'],english)

    def test_llm_discovers_name_outside_local_prescribing_patterns(self):
        self.setup('null');source='Zin Zin';output=automatic_matches([{'utterance_id':'U1','speaker':'Doctor','text':source}])['U1']
        self.assertEqual(output['entities'][0]['kind'],'medicine')
        self.assertEqual(output['mentions'][0]['source'],source)
        check=check_turn(source,source,analysis=output)
        self.assertIn('name_confirmation_required',check['issues'])

    def test_automatic_catalogue_spelling_is_translated_then_confirmed_once(self):
        adapter=self.setup();source='پینڈول لیں۔'
        def token_translation(*args,**kwargs):
            if kwargs.get('task_type')=='translation':
                adapter.task_order.append('translation')
                import re
                token=re.search(r'MF_MED_\w+',kwargs['messages'][-1]['content']).group()
                return json.dumps({'conversation':[{'utterance_id':'U1','text':'Take '+token+'.'}]})
            return original(*args,**kwargs)
        original=adapter.chat
        with patch.object(adapter,'chat',side_effect=token_translation):
            turn=MedicalTranslator().translate_conversation([{'utterance_id':'U1','speaker':'Doctor','text':source}])[0]
        self.assertEqual(turn['original_text'],source)
        self.assertEqual(turn['clinical_english'],'Take Panadol.')
        self.assertEqual(turn['medicine_checks']['issues'],['name_confirmation_required'])
        review=clinician_review(source,turn['clinical_english'],{},'D:test',analysis=turn['medicine_suggestions'])
        self.assertEqual(review['spellings'],{'پینڈول':'Panadol'})
        self.assertEqual(check_turn(source,turn['clinical_english'],review,analysis=turn['medicine_suggestions'])['issues'],[])
        turn['medicine_review']=review
        self.assertEqual(soap_issues([turn],{'plan':'Take Panadol.'}),[])

    def test_untrusted_or_stale_context_cannot_delete_source_medicines(self):
        for mode in ('drop_known','duplicate','invented','context_offline'):
            with self.subTest(mode=mode):
                self.setup(mode)
                output=automatic_matches([{'utterance_id':'U1','speaker':'Doctor','text':'Take Panadol.'}])['U1']
                checked=check_turn('Take Panadol.','Take painkillers.',analysis=output)
                self.assertIn('name_missing_or_changed:Panadol',checked['issues'])
        self.setup();source='We can advance the medicine review.'
        output=automatic_matches([{'utterance_id':'U1','text':source}])['U1']
        self.assertEqual(check_turn(source,source,analysis=output)['mentions'],[])
        changed='Please advance the medicine review.'
        self.assertTrue(check_turn(changed,changed,analysis=output)['mentions'])

    def test_clinician_confirmation_replaces_proposal_without_allowing_both_drugs(self):
        self.setup();source='Take mortiiduom 10 mg.'
        analysis=automatic_matches([{'utterance_id':'U1','speaker':'Doctor','text':source}])['U1']
        english='Take Panadol 10 mg and Motilium.'
        with self.assertRaises(ValueError):
            clinician_review(source,english,{'mortiiduom':'Panadol'},'D:test',analysis=analysis)

    def test_fallback_puts_test_orders_in_plan_and_only_measured_reading_in_objective(self):
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        turns=[{'utterance_id':'U1','speaker':'Doctor','text':
            'You need to get this done: have a blood test, also get a diabetes test done, and open this mouth so I can check your temperature.'},
               {'utterance_id':'U2','speaker':'Doctor','text':'Your temperature is coming up as 102.'},
               {'utterance_id':'U3','speaker':'Doctor','text':'I am writing you a prescription for tests.'}]
        result=load_soap_module().SOAPGenerator().generate({},turns)
        self.assertIn('blood test',result['plan']);self.assertIn('diabetes test',result['plan'])
        self.assertNotIn('blood test',result['objective']);self.assertNotIn('diabetes test',result['objective'])
        self.assertIn('102',result['objective']);self.assertNotIn('prescription',result['subjective'])
        self.assertEqual(result['claim_sources']['objective'][0]['evidence_ids'],['U2'])
        self.assertEqual(soap_issues(turns,result),[])

    def test_soap_retry_has_complete_source_manifest_and_rejected_candidate(self):
        source='Take Panadol to prevent fever.'
        turns=[{'utterance_id':'U1','speaker':'Doctor','text':source}]
        bad={'subjective':'Not documented.','objective':'Not documented.',
             'assessment':'Not documented.','plan':'Not documented.',
             'evidence':[{'utterance_id':'U1','quote':source}]}
        good={**bad,'plan':source}
        adapter=SequenceAdapter([bad,good]);set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        result=load_soap_module().SOAPGenerator().generate({'current_complaint':'Fever'},turns)
        self.assertEqual(result['generation_mode'],'MODEL_VALIDATED')
        first=adapter.calls[0]['messages'][-1]['content']
        self.assertIn(source,first);self.assertIn('SOURCE_MEDICINE_MANIFEST',first)
        repair=json.loads(adapter.calls[1]['messages'][-1]['content'])
        self.assertEqual(repair['previous_rejected_draft']['plan'],'Not documented.')
        self.assertEqual(repair['source_medicine_manifest'][0]['name'],'Panadol')


class ContextWorkflowTests(unittest.TestCase):
    setUp=guided.GuidedConsultationTests.setUp
    tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture
    context=guided.GuidedConsultationTests.context
    revision=guided.GuidedConsultationTests.revision

    def test_persisted_nonmedicine_context_is_used_after_reload_and_soap(self):
        source='We can advance the medicine review.'
        adapter=ContextAdapter();adapter.set_response('translation',{
            'conversation':[{'utterance_id':'U1','text':source}]})
        adapter.set_response('soap_generation',{'subjective':'Not documented.',
            'objective':'Not documented.','assessment':'Not documented.','plan':source,
            'evidence':[{'utterance_id':'U1','quote':source}]})
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        def diarize(text,patient,transcript_id):
            return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,
                        speaker=Speaker.DOCTOR,original_text=source)]
        with patch.object(self.c.documentation_service,'transcribe',return_value=TranscribedText(source,source)),\
             patch.object(self.c.documentation_service,'diarize',side_effect=diarize):
            self.capture()
        before=self.context()['conversation_review']
        self.assertFalse(before['medicine_report']['requires_review'])
        self.assertEqual(before['utterances'][0]['medicine_checks']['mentions'],[])
        persisted=self.c.transcript_repository.get(before['transcript_id']).utterances[0]
        self.assertEqual(persisted.medicine_suggestions['entities'][0]['kind'],'non_medical')
        generated=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(generated.status_code,200,generated.text)
        soap=generated.json()['note']['soap']
        self.assertEqual(soap['medicine_report']['soap_issues'],[])
        self.assertEqual(soap['plan'],source)

    def test_fallback_sources_are_preserved_in_structured_soap_after_api_generation(self):
        source='You need to get a blood test done. Your temperature is coming up as 102.'
        adapter=ContextAdapter();adapter.set_response('translation',{
            'conversation':[{'utterance_id':'U1','text':source}]})
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':adapter}))
        def diarize(text,patient,transcript_id):
            return [TranscriptUtterance(utterance_id='U1',transcript_id=transcript_id,
                        speaker=Speaker.DOCTOR,original_text=source)]
        with patch.object(self.c.documentation_service,'transcribe',return_value=TranscribedText(source,source)),\
             patch.object(self.c.documentation_service,'diarize',side_effect=diarize):self.capture()
        set_gateway(SecureLLMGateway(provider='mock',adapters={'mock':FailingAdapter()}))
        response=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(response.status_code,200,response.text)
        soap=response.json()['note']['soap']
        self.assertIn('blood test',soap['plan']);self.assertNotIn('blood test',soap['objective'])
        self.assertIn('102',soap['objective'])
        self.assertEqual(soap['structured_soap']['plan'][0]['evidence_ids'],['U1'])
        self.assertFalse(any('Claim-level sources unavailable' in w for w in soap['structured_soap']['warnings']))


if __name__=='__main__':unittest.main()
