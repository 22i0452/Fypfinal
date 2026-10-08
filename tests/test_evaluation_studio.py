"""Measured scoring, owned audio, exact references and bounded provider evaluation."""
import base64
import copy
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from app.testing.evaluation import scores,comparison,transcription_metrics,PROTOCOL
from app.testing.audio_library import validate_wav
from app.testing.audio_cases import role_alignment
from app.testing.catalog import catalog,PACK_VERSION
from app.testing.references import scripts
from app.testing.worker import Probe
from tests import test_demo_reports as report_tests


def wav_bytes(seconds=1,channels=1,rate=16000,width=2):
    data=io.BytesIO()
    with wave.open(data,'wb') as w:
        w.setnchannels(channels);w.setsampwidth(width);w.setframerate(rate);w.writeframes(b'\0'*(int(rate*seconds)*channels*width))
    return data.getvalue()


def report(statuses=('PASSED','FAILED','ERROR','SKIPPED')):
    return {'run_id':'QA-ONE','mode':'synthetic','pack_version':PACK_VERSION,'evaluation_protocol':PROTOCOL,
        'reference_sha256':'same-fixed-reference','status':'FAILED','timing_scope':'Synthetic wall time',
        'cases':[{'id':str(i),'category':'Workflow','status':s,'checks':[{'status':'PASSED','metric':'valid_allowed'}] if s=='PASSED' else [],
                  'duration_ms':i+1} for i,s in enumerate(statuses)]}


class ScoringTests(unittest.TestCase):
    def test_errors_count_skipped_does_not_zero_never_becomes_success(self):
        actual=scores(report());self.assertEqual(actual['success'],{'numerator':1,'denominator':3,'percent':33.33})
        self.assertEqual(actual['completion']['percent'],75)
        empty=scores(report(('PENDING','SKIPPED')));self.assertIsNone(empty['success']['percent']);self.assertIsNone(empty['timings']['p95_ms'])
    def test_median_and_nearest_rank_p95_use_completed_cases(self):
        measured=scores(report());self.assertEqual(measured['timings']['median_ms'],2);self.assertEqual(measured['timings']['p95_ms'],3)
    def test_no_delta_for_incomplete_different_or_legacy_references(self):
        old=report();new=copy.deepcopy(old);new['run_id']='QA-TWO'
        self.assertFalse(comparison(old,new)['compatible'])
        old=report(('PASSED','FAILED'));new=copy.deepcopy(old);new['run_id']='QA-TWO';new['cases'][1]['status']='PASSED'
        self.assertEqual(comparison(old,new)['success_delta_pp'],50)
        for key,value in [('reference_sha256','changed'),('evaluation_protocol',None),('mode','live_text')]:
            changed=copy.deepcopy(new);changed[key]=value;self.assertIsNone(comparison(old,changed)['success_delta_pp'])
    def test_model_or_actual_fallback_changes_reject_live_comparison(self):
        old=report(('PASSED',));old['mode']='live_text';old['environment']={'provider_settings':{'model':'A'}}
        old['cases'][0]['provider_calls']=[{'task':'translation','model':'A'}]
        new=copy.deepcopy(old);new['run_id']='QA-TWO';new['cases'][0]['provider_calls'][0]['model']='B'
        self.assertFalse(comparison(old,new)['compatible'])
        old['cases'][0]['provider_calls'].extend([{'task':'http_request','model':None},{'task':'http_request','model':'A'}])
        new=copy.deepcopy(old);new['run_id']='QA-THREE'
        self.assertTrue(comparison(old,new)['compatible'])
    def test_wer_can_exceed_100_and_normalization_does_not_repair_words(self):
        actual=transcription_metrics('Panadol','one two three Panadol');self.assertEqual(actual['wer']['percent'],300)
        self.assertEqual(transcription_metrics('PANADOL!','panadol')['word_errors'],0)
        self.assertEqual(transcription_metrics('Panadol','painkillers')['word_errors'],1)
    def test_audio_names_and_roles_use_separate_denominators(self):
        r=report(('PASSED',));r['cases'][0]['audio_metrics']={'words':4,'word_errors':2,'characters':12,'character_errors':3,
            'medicine_tp':1,'medicine_fp':1,'medicine_fn':0,'roles_expected':3,'roles_correct':2}
        a=scores(r)['audio'];self.assertEqual(a['word_error_rate']['percent'],50);self.assertEqual(a['medicine_precision']['percent'],50)
        self.assertEqual(a['medicine_recall']['percent'],100);self.assertEqual(a['roles']['percent'],66.67)
    def test_role_alignment_cannot_reuse_one_observed_turn_for_every_reference(self):
        refs=[{'speaker':'DOCTOR','text':'Same short words'},{'speaker':'PATIENT','text':'Same short words'}]
        actual=role_alignment(refs,[{'speaker':'DOCTOR','original_text':'Same short words'}]);self.assertEqual(sum(r['correct'] for r in actual),1)
        self.assertEqual(actual[1]['actual'],'UNMATCHED')
    def test_fixed_scripts_have_independent_gold_names_and_roles(self):
        self.assertEqual(len(scripts()),12);self.assertEqual(sum(s['split']=='held_out' for s in scripts()),2)
        self.assertEqual(next(s for s in scripts() if s['id']=='audio-two-medicines')['medicine_names'],['Panadol','Motilium'])
    def test_wav_validation_rejects_malformed_large_stereo_short_and_compressed(self):
        self.assertEqual(validate_wav(wav_bytes())['duration_ms'],1000)
        for data in [b'not audio',b'x'*3_000_001,wav_bytes(.2),wav_bytes(channels=2),wav_bytes(width=1),wav_bytes(91,rate=16000),wav_bytes()[:-10]]:
            with self.assertRaises(ValueError):validate_wav(data)
    def test_http_budget_counts_failures_and_blocks_extra_before_network(self):
        from urllib import request
        from app.testing.provider_budget import RequestBudget
        from urllib.error import URLError
        original=request.urlopen;calls=[]
        def fail(*args,**kwargs):calls.append(kwargs['timeout']);raise URLError('controlled failure')
        try:
            with patch('urllib.request.urlopen',side_effect=fail):
                budget=RequestBudget(total=2,per_case=2);budget.install()
                req=request.Request('https://openrouter.ai/api/v1/chat/completions',data=b'{"model":"model-A"}')
                for _ in range(2):
                    with self.assertRaises(URLError):request.urlopen(req,timeout=90)
                with self.assertRaises(RuntimeError):request.urlopen(req)
                self.assertEqual(calls,[20,20]);self.assertEqual(len(budget.events),2)
                self.assertEqual(budget.events[0]['model'],'model-A')
        finally:request.urlopen=original
    def test_live_pipeline_fixed_cases_can_execute_with_controlled_components(self):
        from medflow.domain.models import TranscriptUtterance
        from medflow.domain.enums import Speaker
        from app.testing.live_cases import run_pipeline
        class Service:
            def translate(self,turns,patient):
                return [t.model_copy(update={'clinical_english':'Take Panadol.','medicine_checks':{'issues':[]}}) for t in turns]
        class Fixture:
            c=type('C',(),{'documentation_service':Service()})()
            def close(self):pass
        with patch('app.testing.worker.Clinic',return_value=Fixture()):
            probe=Probe();run_pipeline('live-no-invented-dose',probe,Path('/unused'))
        self.assertTrue(all(c['status']=='PASSED' for c in probe.checks))


class StudioAPITests(unittest.TestCase):
    setUp=report_tests.DemoReportTests.setUp
    tearDown=report_tests.DemoReportTests.tearDown
    paused=report_tests.DemoReportTests.paused
    def add_clip(self,script='audio-short-yes'):
        return self.client.post('/api/demo-testing/audio',data={'script_id':script,'attested':'true'},files={'file':('fictional.wav',wav_bytes(),'audio/wav')})
    def test_owned_upload_playback_delete_and_durable_restart(self):
        added=self.add_clip();self.assertEqual(added.status_code,201,added.text);row=added.json();self.assertNotIn('wav_base64',row)
        clip_id=row['clip_id'];self.assertEqual(self.client.get('/api/demo-testing/audio/'+clip_id).content,wav_bytes())
        from app.testing.audio_library import AudioLibrary
        restarted=AudioLibrary(self.c.database);restarted.initialize();self.assertEqual(restarted.get(self.user.user_id,clip_id)['script']['reference'],'جی ہاں۔')
        self.c.auth_repository.create_doctor('Other','other-audio@example.test','SyntheticQA123!')
        self.client.post('/api/auth/login',json={'email':'other-audio@example.test','password':'SyntheticQA123!'})
        self.assertEqual(self.client.get('/api/demo-testing/audio').json()['clips'],[])
        self.assertEqual(self.client.get('/api/demo-testing/audio/'+clip_id).status_code,404)
        self.assertEqual(self.client.request('DELETE','/api/demo-testing/audio/'+clip_id,json={}).status_code,404)
    def test_upload_attestation_limits_and_cross_site(self):
        for data in [{'script_id':'audio-short-yes','attested':'false'},{'script_id':'not-in-pack','attested':'true'}]:
            self.assertEqual(self.client.post('/api/demo-testing/audio',data=data,files={'file':('a.wav',wav_bytes(),'audio/wav')}).status_code,400)
        self.assertEqual(self.client.post('/api/demo-testing/audio',headers={'Origin':'https://elsewhere.example'},data={'script_id':'audio-short-yes','attested':'true'},files={'file':('a.wav',wav_bytes(),'audio/wav')}).status_code,403)
    def test_audio_selection_acknowledgement_and_repetitions(self):
        clip=self.add_clip().json();held=self.add_clip('audio-heldout-dose').json()
        self.s.settings=replace(self.s.settings,demo_live_text_enabled=True,openrouter_api_key='controlled-key')
        with patch.object(self.s,'_run'):
            bad=self.client.post(self.base,json={'mode':'audio','audio_ids':[clip['clip_id']]});self.assertEqual(bad.status_code,400)
            mixed=self.client.post(self.base,json={'mode':'audio','confirm_live':True,'audio_ids':[clip['clip_id'],held['clip_id']]});self.assertEqual(mixed.status_code,400)
            good=self.client.post(self.base,json={'mode':'audio','confirm_live':True,'audio_ids':[clip['clip_id']],'repetitions':2});self.assertEqual(good.status_code,202,good.text)
        rows=good.json()['cases'];self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id']);self.assertEqual(rows[0]['source_id'],clip['clip_id'])
        self.assertNotIn('wav_base64',json.dumps(good.json()));self.assertEqual(good.json()['provider_request_limit'],80)
    def test_compare_requires_owner_and_complete_matching_pack(self):
        old=self.paused();self.s.cancel(old['run_id'],self.user.user_id);new=self.paused();self.s.cancel(new['run_id'],self.user.user_id)
        compared=self.client.get('/api/demo-testing/compare',params={'baseline':old['run_id'],'current':new['run_id']});self.assertEqual(compared.status_code,200)
        self.assertFalse(compared.json()['compatible']);self.assertIsNone(compared.json()['success_delta_pp'])
        pdf=self.client.get('/api/demo-testing/compare.pdf',params={'baseline':old['run_id'],'current':new['run_id']});self.assertEqual(pdf.status_code,200);self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.c.auth_repository.create_doctor('Other','other-compare@example.test','SyntheticQA123!')
        self.client.post('/api/auth/login',json={'email':'other-compare@example.test','password':'SyntheticQA123!'})
        self.assertEqual(self.client.get('/api/demo-testing/compare',params={'baseline':old['run_id'],'current':new['run_id']}).status_code,404)
    def test_recorded_audio_scoring_keeps_gold_out_of_pipeline_inputs(self):
        from app.testing.audio_cases import run_audio
        from medflow.domain.models import TranscriptUtterance
        from medflow.domain.enums import Speaker
        heard=[]
        class Service:
            def transcribe(self,audio,**kwargs):heard.append(('asr',kwargs));return 'Observed different words'
            def diarize(self,text,**kwargs):heard.append(('roles',text));return [TranscriptUtterance(transcript_id='T',utterance_id='U1',speaker=Speaker.UNKNOWN,original_text=text)]
            def translate(self,turns,**kwargs):heard.append(('translate',turns[0].original_text));return [t.model_copy(update={'clinical_english':'Observed words','medicine_checks':{'issues':[]}}) for t in turns]
        class Fixture:
            patient=type('P',(),{'patient_id':'PT-FICTIONAL'})()
            c=type('C',(),{'documentation_service':Service()})()
            def ready(self):pass
            def close(self):pass
        clip=self.s.audio.get(self.user.user_id,self.add_clip().json()['clip_id']);probe=Probe()
        with patch('app.testing.worker.Clinic',return_value=Fixture()):run_audio(clip,probe,self.root)
        self.assertNotIn(clip['script']['reference'],str(heard));self.assertGreater(probe.audio_metrics['word_errors'],0)
        self.assertTrue(any(c['status']=='FAILED' for c in probe.checks))


if __name__=='__main__':unittest.main()
