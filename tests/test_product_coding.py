"""Synthetic version/source integrity checks; no medical-code accuracy claim."""
import threading
import unittest
from dataclasses import replace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from app.services.coding_service import CodingCandidate,CodingServiceError
from app.services.llm_coding_provider import LLMCodingProvider
from tests import test_guided_consultation as guided
from security_guardrails import get_gateway


class SourceProvider:
    def __init__(self):self.calls=0
    def suggest(self,version):
        self.calls+=1
        return [CodingCandidate('Z00.00','Synthetic source suggestion',None,[version.soap.subjective[0].claim_id],method='QA_SYNTHETIC')]


class ProductCodingTests(unittest.TestCase):
    setUpBase=guided.GuidedConsultationTests.setUp
    tearDown=guided.GuidedConsultationTests.tearDown
    capture=guided.GuidedConsultationTests.capture
    context=guided.GuidedConsultationTests.context
    revision=guided.GuidedConsultationTests.revision
    def setUp(self):
        self.setUpBase()
        self.c.settings=replace(self.c.settings,icd_coding_enabled=True)
        self.provider=SourceProvider();self.c.coding_service.provider=self.provider
        get_gateway()._adapter('mock').set_response('soap_generation',{
            'subjective':'Synthetic response during the consultation.',
            'objective':'Not documented.','assessment':'Not documented.','plan':'Not documented.',
            'evidence':[{'utterance_id':'U1','quote':'synthetic response'}],
            'claim_sources':{'subjective':[{'text':'Synthetic response during the consultation.','evidence_ids':['U1']}],'objective':[],'assessment':[],'plan':[]}})
        self.capture()
        response=self.client.post(self.path+'/generate-soap',json=self.revision())
        self.assertEqual(response.status_code,200,response.text)
        self.note_id=response.json()['note']['note_id']
        self.codes='/api/notes/'+self.note_id+'/code-suggestions'
    def generate(self,force=False):
        response=self.client.post(self.codes+('?force=true' if force else ''))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['suggestions']
    def advance_version(self):
        note=self.c.note_repository.get(self.note_id)
        source=self.c.note_repository.get_version(note.current_version_id)
        updated=source.model_copy(update={'note_version_id':source.note_version_id+'-EDIT','version_number':source.version_number+1})
        self.c.note_repository.save_version(updated)
        self.c.note_repository.save(note.model_copy(update={'current_version_id':updated.note_version_id}))
        return updated
    def test_source_chain_is_exact_and_confidence_remains_unassessed(self):
        item=self.generate()[0]
        response=self.client.get('/api/code-suggestions/'+item['code_suggestion_id']+'/evidence')
        self.assertEqual(response.status_code,200,response.text)
        source=response.json()
        self.assertEqual(source['claims'][0]['claim_id'],item['evidence_ids'][0])
        self.assertEqual(source['claims'][0]['sources'][0]['utterance_id'],'U1')
        self.assertTrue(source['claims'][0]['sources'][0]['available'])
        self.assertEqual(source['clinical_correctness'],'UNASSESSED')
        self.assertEqual(source['catalog_validation'],'UNASSESSED')
        self.assertIsNone(item['confidence'])
        self.assertGreaterEqual(item['generation_duration_ms'],0)
    def test_stale_sources_remain_readable_but_cannot_be_reviewed(self):
        item=self.generate()[0];new=self.advance_version()
        source=self.client.get('/api/code-suggestions/'+item['code_suggestion_id']+'/evidence').json()
        self.assertTrue(source['stale']);self.assertEqual(source['version'],1)
        review=self.client.post('/api/code-suggestions/'+item['code_suggestion_id']+'/approve')
        self.assertEqual(review.status_code,409)
        current=self.generate();self.assertEqual(current[0]['note_version_id'],new.note_version_id)
        self.assertEqual(self.provider.calls,2)
        history=self.client.get(self.codes).json()['suggestions']
        self.assertEqual(len(history),2);self.assertEqual(sum(item['stale'] for item in history),1)
    def test_provider_failure_and_invalid_regeneration_preserve_saved_suggestions(self):
        old=self.generate()[0]
        with patch.object(self.provider,'suggest',side_effect=CodingServiceError('CODING_UNAVAILABLE','Synthetic failure')):
            self.assertEqual(self.client.post(self.codes+'?force=true').status_code,503)
        valid=self.provider.suggest(self.c.note_repository.get_version(old['note_version_id']))[0]
        invalid=CodingCandidate('X00','Synthetic invalid evidence',None,['OTHER-PATIENT-CLAIM'])
        with patch.object(self.provider,'suggest',return_value=[valid,invalid]):
            self.assertEqual(self.client.post(self.codes+'?force=true').status_code,400)
        rows=self.client.get(self.codes).json()['suggestions']
        self.assertEqual([row['code_suggestion_id'] for row in rows],[old['code_suggestion_id']])
    def test_change_during_generation_rejects_late_provider_result(self):
        original=self.provider.suggest
        def changed(version):
            result=original(version);self.advance_version();return result
        with patch.object(self.provider,'suggest',side_effect=changed):
            self.assertEqual(self.client.post(self.codes).status_code,409)
        self.assertEqual(self.client.get(self.codes).json()['suggestions'],[])
    def test_force_regeneration_does_not_duplicate_a_reviewed_code(self):
        item=self.generate()[0]
        response=self.client.post('/api/code-suggestions/'+item['code_suggestion_id']+'/approve')
        self.assertEqual(response.status_code,200,response.text)
        result=self.generate(force=True)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['code_suggestion_id'],item['code_suggestion_id'])
        self.assertEqual(result[0]['status'],'APPROVED')
    def test_cross_patient_access_and_disabled_configuration(self):
        item=self.generate()[0]
        self.c.settings=replace(self.c.settings,icd_coding_enabled=False)
        self.assertEqual(self.client.post(self.codes).status_code,503)
        # Stored sources remain readable when generation is disabled.
        self.assertEqual(self.client.get('/api/code-suggestions/'+item['code_suggestion_id']+'/evidence').status_code,200)
        self.c.auth_repository.create_doctor('Other','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.get('/api/code-suggestions/'+item['code_suggestion_id']+'/evidence').status_code,403)
        self.assertEqual(self.client.get(self.codes).status_code,403)
    def test_unavailable_transcript_is_not_replaced_with_another_source(self):
        item=self.generate()[0]
        with patch.object(self.c.transcript_repository,'get',return_value=None):
            source=self.c.coding_service.evidence(suggestion_id=item['code_suggestion_id'],actor=self.actor)
        self.assertFalse(source['claims'][0]['sources'][0]['available'])
        self.assertIsNone(source['claims'][0]['sources'][0]['original_text'])
    def test_unresolved_claim_cannot_be_approved(self):
        item=self.generate()[0]
        suggestion=self.c.code_suggestion_repository.get(item['code_suggestion_id'])
        self.c.code_suggestion_repository.save(suggestion.model_copy(update={'evidence_ids':['UNKNOWN']}))
        source=self.client.get('/api/code-suggestions/'+item['code_suggestion_id']+'/evidence').json()
        self.assertEqual(source['reference_check'],'FAILED')
        self.assertEqual(self.client.post('/api/code-suggestions/'+item['code_suggestion_id']+'/approve').status_code,400)
    def test_concurrent_generation_reuses_one_result(self):
        entered=threading.Event();release=threading.Event();original=self.provider.suggest
        def slow(version):
            entered.set();release.wait(5);return original(version)
        with patch.object(self.provider,'suggest',side_effect=slow),ThreadPoolExecutor(2) as pool:
            first=pool.submit(self.c.coding_service.generate,note_id=self.note_id,actor=self.actor)
            self.assertTrue(entered.wait(3))
            second=pool.submit(self.c.coding_service.generate,note_id=self.note_id,actor=self.actor)
            release.set();a=first.result(5);b=second.result(5)
        self.assertEqual(self.provider.calls,1)
        self.assertEqual(a[0].code_suggestion_id,b[0].code_suggestion_id)
    def test_llm_does_not_guess_codes_on_failure_or_invent_missing_scores(self):
        version=self.c.note_repository.get_version(self.c.note_repository.get(self.note_id).current_version_id)
        with patch('app.services.llm_coding_provider.get_gateway') as gateway:
            gateway.return_value.chat_json.side_effect=RuntimeError('Synthetic provider failure')
            with self.assertRaises(CodingServiceError) as raised:LLMCodingProvider().suggest(version)
            self.assertEqual(raised.exception.code,'CODING_UNAVAILABLE')
        provider=LLMCodingProvider();claim=version.soap.subjective[0].claim_id
        result=provider._parse_suggestions({'suggestions':[{'system':'ICD-10','code':'Z00.00','description':'Synthetic','evidence_ids':[claim]}]},{claim})
        self.assertIsNone(result[0].confidence)
        self.assertEqual(provider._parse_suggestions({'suggestions':[{'system':'HCPCS','code':'G0001','description':'Synthetic','evidence_ids':[claim]}]},{claim}),[])
        self.assertEqual(provider._parse_suggestions({'suggestions':[{'system':'ICD-10','code':'Z00.00','description':'Synthetic','evidence_ids':[claim,'UNKNOWN']} ]},{claim}),[])
    def test_public_home_and_private_workspace_routes(self):
        self.client.post('/api/auth/logout')
        home=self.client.get('/')
        self.assertEqual(home.status_code,200)
        self.assertIn('Care, <em>in rhythm.</em>',home.text)
        self.assertIn('Coming soon',home.text)
        workspace=self.client.get('/workspace',follow_redirects=False)
        self.assertEqual(workspace.status_code,302)
        self.assertEqual(workspace.headers['location'],'/consultation/login')

if __name__=='__main__':unittest.main()
