"""Speech recovery preserves evidence and booking routes to the chosen account."""
import io
import json
import unittest
import wave
from unittest.mock import patch
import numpy as np
from app.services.booking_flow import BookingFlow
from app.services.demo_stt import audio_metrics, contextual_stt_prompt, transcript_issue, wav_bytes_from_upload
from tests import test_demo_call_finish as fixture


def wav(amplitude=.05):
    samples=(np.sin(np.arange(16000)*.2)*amplitude*32767).astype(np.int16)
    b=io.BytesIO()
    with wave.open(b,'wb') as h:
        h.setnchannels(1);h.setsampwidth(2);h.setframerate(16000);h.writeframes(samples.tobytes())
    return b.getvalue()


class ReceptionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.helper=fixture.DemoCallFinishTests();self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.client=self.helper.client;self.service=self.helper.service

    def test_prompt_echo_is_retained_for_review_not_collected(self):
        echo='مریض اردو رسم خط میں لکھیں جیسے 3 بجے۔'
        self.assertEqual(transcript_issue(echo),'prompt_echo')
        started=self.service.start(fixture.SCENARIO)
        with patch.object(self.service,'_extract') as extract:
            turn=self.service.turn(scenario_id=fixture.SCENARIO,history=started['history'],user_message=echo)
            extract.assert_not_called()
        self.assertTrue(turn['understanding']['needs_review'])
        self.assertEqual(turn['understanding']['raw'],echo)
        self.assertEqual(turn['process']['values'],{})

    def test_context_and_translation_preserve_original(self):
        flow=BookingFlow();flow.current='department'
        flow.values={'name':{'ur':'احمد','en':'Ahmed'}}
        flow.recent_turns=[{'role':'assistant','content':'Which department?'}]
        payload=json.loads(flow.extraction_messages('general med')[1]['content'])
        self.assertEqual(payload['collected_fields']['name']['en'],'Ahmed')
        self.assertEqual(payload['recent_turns'][0]['content'],'Which department?')
        extraction={'intent':'answer','fields':{'department':{'ur':'جنرل میڈیسن','en':'General Medicine'},'doctor':{'ur':'کوئی بھی دستیاب ڈاکٹر','en':'Any available doctor'}},'interpretation':{'ur':'جنرل میڈیسن، کوئی بھی ڈاکٹر','en':'General Medicine, any available doctor'}}
        with patch.object(self.service,'_extract',return_value=extraction):
            turn=self.service.turn(scenario_id=fixture.SCENARIO,history=[flow.state_message()],user_message='general med any doctor')
        self.assertEqual(turn['understanding']['raw'],'general med any doctor')
        self.assertEqual(turn['understanding']['en'],'General Medicine, any available doctor')
        self.assertEqual(turn['process']['values']['department']['en'],'General Medicine')
        restored=BookingFlow.from_history(turn['history'])
        self.assertEqual(restored.prefill['doctor']['en'],'Any available doctor')

    def test_uncertain_answer_does_not_advance_collected_fields(self):
        f=BookingFlow();f.current='phone';f.values={'name':{'ur':'احمد','en':'Ahmed'}}
        with patch.object(self.service,'_extract',return_value={'needs_review':True,'fields':{'phone':{'ur':'03000000000','en':'03000000000'}}}):
            result=self.service.turn(scenario_id=fixture.SCENARIO,history=[f.state_message()],user_message='unclear phone')
        self.assertTrue(result['understanding']['needs_review'])
        self.assertEqual(result['process']['values'],f.values)
        self.assertEqual(result['process']['current_field'],'phone')

    def test_short_confirmations_skip_model_but_corrections_do_not(self):
        f=BookingFlow();f._ask_confirm('age',{'ur':'22','en':'22'})
        with patch.object(self.service,'_completion',side_effect=AssertionError('model not expected')):
            self.assertEqual(self.service._extract(f,'جی ہاں۔')['intent'],'yes')
        with patch.object(self.service,'_providers',return_value=[('test','key','model')]), patch.object(self.service,'_completion',return_value=json.dumps({'intent':'no','fields':{'age':{'ur':'23','en':'23'}}})) as call:
            self.service._extract(f,'No, 23');self.assertTrue(call.called)

    def test_audio_gain_is_bounded_and_short_replies_allowed(self):
        original=wav(.0001);before=audio_metrics(original);after=audio_metrics(wav_bytes_from_upload(original))
        self.assertLessEqual(after['peak'],before['peak']*4.01)
        prompt=contextual_stt_prompt('phone')
        self.assertNotIn('0303',prompt);self.assertNotIn('لکھیں',prompt)
        for answer in ['جی','22','جنرل میڈیسن جنرل میڈیسن']:
            self.assertEqual(transcript_issue(answer),'')

    def test_stt_silence_and_provider_failure_are_distinct(self):
        with patch('app.routers.receptionist_desk.get_gateway') as getter:
            response=self.client.post('/api/desk/demo-calls/stt',files={'audio':('voice.wav',wav(0),'audio/wav')})
            self.assertEqual(response.json()['reason'],'no_audio');getter.assert_not_called()
            getter.return_value.transcribe_audio.side_effect=RuntimeError('private-provider-detail')
            response=self.client.post('/api/desk/demo-calls/stt',files={'audio':('voice.wav',wav(),'audio/wav')})
            self.assertNotEqual(response.status_code,200)
            self.assertNotIn('private-provider-detail',response.text)

    def test_stt_echo_response_keeps_text_and_context(self):
        echo='مریض اردو رسم خط میں لکھیں جیسے 3 بجے۔'
        f=BookingFlow();f.current='department'
        with patch('app.routers.receptionist_desk.get_gateway') as getter:
            getter.return_value.transcribe_audio.return_value=echo
            response=self.client.post('/api/desk/demo-calls/stt',data={'history':json.dumps([f.state_message()])},files={'audio':('voice.wav',wav(),'audio/wav')})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['raw_text'],echo)
            self.assertTrue(response.json()['needs_review'])
            self.assertIn('شعبہ',getter.return_value.transcribe_audio.call_args.kwargs['prompt'])

    def test_saved_request_reaches_only_assigned_doctor_and_survives_restart(self):
        c=self.client.app.state.container
        other=c.auth_repository.create_doctor('Dr. Other','other@example.test','SyntheticPass123!')
        self.client.post('/api/auth/login',json={'email':'demo-doctor@example.test','password':'SyntheticPass123!'})
        config=self.client.get('/api/desk/configuration').json()
        self.assertEqual(config['preferred_practitioner_id'],self.helper.doctor['practitioner_id'])
        slot=self.helper._first_open_slot()
        result=self.helper._finish(self.helper._full_call(slot))
        appointment=result['booking']['appointment']
        self.assertEqual(appointment['practitioner_id'],self.helper.doctor['practitioner_id'])
        self.assertTrue(appointment['practitioner_name'])
        patient_id=result['patient_id']
        self.assertIn(patient_id,[x['_id'] for x in self.client.get('/api/patients').json()])
        self.assertEqual(self.client.get('/api/appointments/doctor-queue').json()['appointments'][0]['status'],'REQUESTED')
        from app.main import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(c.settings)) as fresh:
            fresh.post('/api/auth/login',json={'email':'demo-doctor@example.test','password':'SyntheticPass123!'})
            self.assertIn(patient_id,[x['_id'] for x in fresh.get('/api/patients').json()])
        self.client.post('/api/auth/login',json={'email':'other@example.test','password':'SyntheticPass123!'})
        self.assertEqual(self.client.get('/api/appointments/doctor-queue').json()['appointments'],[])
        self.assertNotIn(patient_id,[x['_id'] for x in self.client.get('/api/patients').json()])
        self.assertEqual(self.client.get('/api/workflows/context/'+patient_id).status_code,403)

    def test_unmatched_named_doctor_is_not_silently_rerouted(self):
        history=self.helper._full_call(self.helper._first_open_slot())
        flow=BookingFlow.from_history(history)
        flow.values['doctor']={'ur':'نامعلوم ڈاکٹر','en':'Dr. Nonexistent'}
        result=self.helper._finish([flow.state_message()])
        self.assertTrue(result['saved'])
        self.assertEqual(result['booking']['status'],'DOCTOR_UNCLEAR')
        self.assertFalse(self.client.app.state.container.appointment_repository.list(patient_id=result['patient_id']))

    def test_short_answers_use_context_without_model_calls(self):
        cases=[('age','بائیس','22'),('age','twenty two','22'),('age','7','7'),('first_visit','جی','Yes'),('first_visit','نہیں','No'),('history','none','None'),('complaint','بخار','Fever'),('department','general general medicine medicine','General Medicine'),('doctor','any','Any available doctor')]
        for key,answer,expected in cases:
            with self.subTest(key=key,answer=answer):
                f=BookingFlow();f.current=key
                with patch.object(self.service,'_extract',side_effect=AssertionError('No model needed')):
                    result=self.service.turn(scenario_id=fixture.SCENARIO,history=[f.state_message()],user_message=answer)
                state=BookingFlow.from_history(result['history'])
                value=state.pending if state.step=='confirm' else state.values.get(key)
                self.assertEqual(value['en'],expected)
                self.assertFalse(result['understanding']['needs_review'])

    def test_repeated_short_confirmations_and_corrections(self):
        for answer in ['yes yes','جی جی','جی بالکل درست ہے','جی نہیں']:
            f=BookingFlow();f._ask_confirm('age',{'ur':'22','en':'22'})
            with patch.object(self.service,'_extract',side_effect=AssertionError('No model needed')):
                result=self.service.turn(scenario_id=fixture.SCENARIO,history=[f.state_message()],user_message=answer)
            state=BookingFlow.from_history(result['history'])
            self.assertEqual('age' in state.values,answer!='جی نہیں')
        f=BookingFlow();f.current='age'
        self.assertIsNone(self.service._short_answer(f,'22 or 23'))
        f.current='department'
        self.assertIsNone(self.service._short_answer(f,'general medicine any doctor'))
        f.current='first_visit'
        self.assertEqual(f.fallback_extraction('not sure')['fields'],{})

    def _catalogue_flow(self):
        f=BookingFlow();f.current='department'
        f.values={'name':{'ur':'مریض','en':'Synthetic Choice Patient'},'age':{'ur':'22','en':'22'},'phone':{'ur':'03000000456','en':'03000000456'},'first_visit':{'ur':'جی ہاں','en':'Yes'},'history':{'ur':'کوئی نہیں','en':'None'},'complaint':{'ur':'بخار','en':'Fever'}}
        return f

    def test_real_doctor_list_is_spoken_and_inactive_accounts_excluded(self):
        c=self.client.app.state.container
        inactive=c.auth_repository.create_doctor('Dr. Inactive','inactive@example.test','SyntheticPass123!')
        with c.database.connection() as conn:
            conn.execute('UPDATE doctors SET active=0 WHERE id=?',(inactive.user_id,))
        f=self._catalogue_flow()
        result=self.service.turn(scenario_id=fixture.SCENARIO,history=[f.state_message()],user_message='General Medicine')
        choices=result['process']['doctor_choices']
        self.assertIn(self.helper.doctor['practitioner_id'],[row['practitioner_id'] for row in choices])
        self.assertNotIn(inactive.practitioner_id,[row['practitioner_id'] for row in choices])
        self.assertIn(self.helper.doctor['full_name'],result['speech_text'])
        self.assertIn(self.helper.doctor['full_name'],self.service.urdu_for_speech(result['speech_text']))
        self.assertEqual(sum(row['recommended'] for row in choices),1)

    def test_recommendation_uses_earliest_actual_slot(self):
        c=self.client.app.state.container
        c.auth_repository.create_doctor('Dr. Second Choice','second-choice@example.test','SyntheticPass123!')
        f=self._catalogue_flow();f.values['department']={'ur':'جنرل میڈیسن','en':'General Medicine'}
        def availability(**kwargs):
            hour='15' if kwargs['practitioner_id']==self.helper.doctor['practitioner_id'] else '12'
            return {'slots':[{'start_at':f'2026-10-12T{hour}:00:00+05:00'}]}
        with patch.object(c.receptionist_integration_service,'availability',side_effect=availability):
            choices=self.service._doctor_choices(f)
        self.assertEqual(choices[0]['display_name'],'Dr. Second Choice')
        self.assertTrue(choices[0]['recommended'])
        self.assertFalse(choices[1]['recommended'])
        f.current='doctor'
        selected=self.service._catalog_answer(f,'recommended',choices)
        self.assertEqual(selected['fields']['doctor']['en'],'Dr. Second Choice')
        with patch.object(c.receptionist_integration_service,'availability',return_value={'slots':[]}):
            self.assertFalse(any(row['recommended'] for row in self.service._doctor_choices(f)))

    def test_doctor_numbers_keep_listed_order_and_exact_identity(self):
        c=self.client.app.state.container
        duplicate=c.auth_repository.create_doctor(self.helper.doctor['full_name'],'duplicate-name@example.test','SyntheticPass123!')
        f=self._catalogue_flow();f.current='doctor';f.values['department']={'ur':'جنرل میڈیسن','en':'General Medicine'}
        choices=self.service._doctor_choices(f)
        f.doctor_options=[{'practitioner_id':self.helper.doctor['practitioner_id'],'recommended':False},{'practitioner_id':duplicate.practitioner_id,'recommended':False}]
        with patch.object(self.service,'_extract',side_effect=AssertionError('No model needed')):
            result=self.service.turn(scenario_id=fixture.SCENARIO,history=[f.state_message()],user_message='2')
        selected=BookingFlow.from_history(result['history'])
        self.assertEqual(selected.values['doctor']['practitioner_id'],duplicate.practitioner_id)
        response=self.client.get('/api/desk/availability',params={'practitioner_id':duplicate.practitioner_id,'visit_type_id':'VISIT-NEW'})
        selected.values['time']={'ur':'وقت','en':'Synthetic available slot','iso':response.json()['slots'][0]['start_at']};selected.step='done'
        saved=self.helper._finish([selected.state_message()])
        self.assertEqual(saved['booking']['appointment']['practitioner_id'],duplicate.practitioner_id)

    def test_short_audio_keeps_signal_and_original_measurement(self):
        source=io.BytesIO(wav())
        with wave.open(source,'rb') as h: frames=h.readframes(1280)
        target=io.BytesIO()
        with wave.open(target,'wb') as h:
            h.setnchannels(1);h.setsampwidth(2);h.setframerate(16000);h.writeframes(frames)
        short=target.getvalue()
        self.assertEqual(audio_metrics(short)['duration_ms'],80)
        prepared=wav_bytes_from_upload(short)
        self.assertEqual(audio_metrics(prepared)['duration_ms'],440)
        with wave.open(io.BytesIO(prepared),'rb') as h: samples=np.frombuffer(h.readframes(h.getnframes()),dtype=np.int16)
        self.assertTrue(np.all(samples[:1920]==0));self.assertTrue(np.all(samples[-3840:]==0))
        self.assertGreater(np.max(np.abs(samples[1920:-3840])),0)
        self.assertEqual(contextual_stt_prompt('age','confirm'),'')
        self.assertNotIn('جنرل میڈیسن',contextual_stt_prompt('name'))
