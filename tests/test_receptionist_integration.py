from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from app.main import create_app
from receptionist.audio_recorder import AudioRecorder
from receptionist.agent import ReceptionistAgent
from receptionist.llm_module import LLMBrain
from security_guardrails import Actor, SecureLLMGateway, authorize, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter, ProviderAdapterError
from receptionist.stt_module import STTEngine
from tests.test_central_app_auth import _settings


SERVICE_TOKEN = "synthetic-receptionist-service-token-at-least-32-characters"
SERVICE_HEADERS = {"X-MedFlow-Receptionist-Token": SERVICE_TOKEN}


class _FailingChatAdapter:
    def chat(self, **_kwargs) -> str:
        raise ProviderAdapterError("Synthetic provider failure")


class ReceptionistIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response("intake_intent", {"intent": "answer", "fields": []})
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        self.addCleanup(set_gateway, None)

    @staticmethod
    def _fill(brain: LLMBrain) -> None:
        brain.start_conversation()
        for answer in (
            "Synthetic Test Patient", "35", "03000000999", "Yes",
            "No synthetic history", "Synthetic complaint", "General Medicine",
            "no preference", "New Patient Consultation", "2030-01-07 09:00",
        ):
            brain.get_response(answer)

    @staticmethod
    def _intake(client: TestClient, suffix: str) -> dict:
        response = client.post(
            "/api/receptionist/intakes",
            headers=SERVICE_HEADERS,
            json={
                "name": "Synthetic Reception Patient",
                "age_text": "35 years",
                "phone_number": f"03000000{int(suffix):03d}",
                "first_visit": "Yes",
                "past_medical_history": "No synthetic history reported",
                "current_complaint": f"Synthetic complaint {suffix}",
                "intake_token": f"synthetic-intake-session-token-{suffix:0>12}",
                "revision": 1,
                "confirmed_revision": 1,
            },
        )
        if response.status_code != 200:
            raise AssertionError(response.text)
        return {**response.json(), "intake_token": f"synthetic-intake-session-token-{suffix:0>12}"}

    def test_receptionist_llm_tasks_are_narrow(self) -> None:
        actor = Actor("synthetic-receptionist", "receptionist")
        self.assertTrue(authorize(actor, "llm_receptionist"))
        self.assertTrue(authorize(actor, "intake_extract"))
        self.assertTrue(authorize(actor, "intake_translate"))
        self.assertFalse(authorize(actor, "read_notes"))
        self.assertFalse(authorize(actor, "approve_note"))

        adapter = MockProviderAdapter()
        adapter.set_response(
            "intake_extract",
            {
                "نام": "Synthetic Patient",
                "عمر": "35",
                "فون_نمبر": "03000000001",
                "پہلی_بار": "ہاں",
                "پچھلی_بیماریاں": "کوئی نہیں",
                "آج_کی_شکایت": "Synthetic complaint",
                "شعبہ": "General Medicine",
                "department_id": "DEP-GM",
                "ڈاکٹر_کی_ترجیح": "کوئی خاص ترجیح نہیں",
                "practitioner_id": "",
                "ملاقات_کی_قسم": "New Patient Consultation",
                "visit_type_id": "VISIT-NEW",
                "بکنگ_کا_وقت": "2030-01-02 09:00",
            },
        )
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": adapter},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            brain.continue_after_assistant_prompt("Synthetic intake complete")
            extracted = brain.extract_patient_data()
        finally:
            set_gateway(None)
        self.assertEqual(extracted, {})
        self.assertEqual(adapter.calls, [])

    def test_conversation_turns_minimize_locally_captured_identity(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response("llm_receptionist", "Synthetic acknowledgement")
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": adapter},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            brain.start_conversation()
            for answer in ("Synthetic Turn Patient", "35", "03000000122"):
                brain.get_response(answer)
            brain._call()
        finally:
            set_gateway(None)

        outbound = json.dumps(
            [call["messages"] for call in adapter.calls],
            ensure_ascii=False,
        )
        self.assertNotIn("Synthetic Turn Patient", outbound)
        self.assertNotIn("03000000122", outbound)
        self.assertIn("[PATIENT_NAME]", outbound)
        self.assertIn("[PHONE]", outbound)

    def test_local_summary_contains_all_fields_and_confirmation_skips_provider(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "llm_receptionist",
            (
                "[PATIENT_NAME] [PHONE] کی معلومات مکمل ہیں۔ "
                "کیا یہ سب معلومات درست ہیں؟"
            ),
        )
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": adapter},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            completed_turns = [
                ("آپ کا پورا نام کیا ہے؟", "Synthetic Summary Patient"),
                ("آپ کی عمر کیا ہے؟", "34 سال"),
                ("آپ کا موبائل نمبر کیا ہے؟", "03000000125"),
                ("کیا آپ پہلی بار آ رہے ہیں؟", "جی ہاں پہلی بار"),
                ("کوئی پچھلی بیماری یا طبی تاریخ؟", "ہائی بلڈ پریشر"),
                ("آج آپ کو کیا تکلیف ہے؟", "مصنوعی پیٹ درد"),
                ("آپ کس شعبے میں ملاقات چاہتے ہیں؟", "جنرل میڈیسن"),
                ("کیا کسی خاص ڈاکٹر کو ترجیح ہے؟", "کوئی خاص ترجیح نہیں"),
                ("ملاقات کی قسم کیا ہوگی؟", "نئی مریض ملاقات"),
            ]
            brain.start_conversation()
            for assistant_text, patient_text in completed_turns:
                brain.get_response(patient_text)

            summary = brain.get_response("کل دوپہر دو بجے")
            provider_calls_before_confirmation = len(adapter.calls)
            confirmation = brain.get_response("جی ہاں، اپائنٹمنٹ بک کریں")
        finally:
            set_gateway(None)

        self.assertNotIn("[PATIENT_NAME]", summary)
        self.assertNotIn("[PHONE]", summary)
        for expected in (
            "Synthetic Summary Patient",
            "03000000125",
            "34",
            "ہائی بلڈ پریشر",
            "مصنوعی پیٹ درد",
            "جنرل میڈیسن",
            "کوئی خاص ترجیح نہیں",
            "نئی مریض ملاقات",
            "کل دوپہر دو بجے",
        ):
            self.assertIn(expected, summary)
        for label in (
            "نام:",
            "عمر:",
            "فون نمبر:",
            "پہلی ملاقات:",
            "طبی تاریخ:",
            "آج کی شکایت:",
            "شعبہ:",
            "ڈاکٹر کی ترجیح:",
            "ملاقات کی قسم:",
            "تاریخ اور وقت:",
        ):
            self.assertIn(label, summary)
        self.assertEqual(len(adapter.calls), provider_calls_before_confirmation)
        self.assertTrue(all(call["task_type"] == "intake_intent" for call in adapter.calls))
        self.assertTrue(brain.is_complete())
        self.assertIn("تصدیق", confirmation)

    def test_provider_failure_after_unclear_confirmation_does_not_end_session(self) -> None:
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": _FailingChatAdapter()},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            brain._messages.append(
                {
                    "role": "assistant",
                    "content": "کیا یہ سب معلومات درست ہیں؟",
                }
            )
            response = brain.get_response("موسیقی")
        finally:
            set_gateway(None)

        self.assertFalse(brain.is_complete())
        self.assertIn("جواب واضح نہیں", response)

    def test_spoken_summary_confirmation_accepts_natural_phrases(self) -> None:
        accepted_phrases = (
            "all the information is true",
            "all information is right",
            "تمام معلومات ٹھیک ہیں",
            "جی بالکل درست ہیں",
            "sab theek hai",
        )
        for phrase in accepted_phrases:
            with self.subTest(phrase=phrase):
                brain = LLMBrain()
                self._fill(brain)

                self.assertEqual(brain.expected_field(), "confirmation")
                self.assertTrue(brain.valid_confirmation_answer(phrase))
                response = brain.get_response(phrase)

                self.assertTrue(brain.is_complete())
                self.assertFalse(brain.is_awaiting_confirmation())
                self.assertTrue("تصدیق" in response or "confirmed" in response)

    def test_agent_uses_dedicated_confirmation_stt_context(self) -> None:
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent.llm = LLMBrain()
        self._fill(agent.llm)

        expected_field, validator = agent._stt_turn_context()

        self.assertEqual(expected_field, "confirmation")
        self.assertIsNotNone(validator)
        assert validator is not None
        self.assertTrue(validator("all the information is true"))
        self.assertTrue(validator("تمام معلومات ٹھیک ہیں"))
        self.assertTrue(validator("نہیں، فون نمبر غلط ہے"))
        self.assertFalse(validator("موسیقی"))

    def test_doctor_question_lists_server_controlled_choices(self) -> None:
        brain = LLMBrain(
            schedule_context="Synthetic server-controlled schedule",
            doctor_options=["Ahmad Ali", "Dr. Shaimaan"],
        )
        brain.start_conversation()
        answers = (
            "Synthetic Choice Patient",
            "35 years",
            "03000000126",
            "Yes, first visit",
            "No synthetic history",
            "Synthetic complaint",
            "General Medicine",
        )
        reply = ""
        for answer in answers:
            reply = brain.get_response(answer)

        self.assertEqual(brain.expected_field(), "practitioner_preference")
        self.assertIn("1: Ahmad Ali", reply)
        self.assertIn("2: Dr. Shaimaan", reply)
        self.assertIn("no preference", reply)

    def test_no_preference_correction_preserves_intake_and_can_confirm(self) -> None:
        brain = LLMBrain(doctor_options=["Ahmad Ali", "Dr. Shaimaan"])
        brain.start_conversation()
        answers = (
            "Synthetic Updated Patient",
            "35 years",
            "03000000127",
            "Yes, first visit",
            "No synthetic history",
            "Synthetic complaint",
            "General Medicine",
            "Dr Shaimaan Qadir",
            "New Patient Consultation",
            "tomorrow at 14:00",
        )
        reply = ""
        for answer in answers:
            reply = brain.get_response(answer)
        self.assertTrue(brain.is_awaiting_confirmation())

        corrected = brain.get_response("no preference")
        self.assertFalse(brain.is_awaiting_confirmation())
        self.assertFalse(brain.is_complete())
        brain.get_response("no preference")
        brain.get_response("yes")
        self.assertEqual(brain.expected_field(), "booking_slot_time")
        brain.get_response("tomorrow at 14:00")
        self.assertEqual(
            brain.local_intake_data()["ڈاکٹر_کی_ترجیح"],
            "Ahmad Ali",
        )
        brain.get_response("no preference")
        self.assertFalse(brain.is_complete())

    def test_department_doctor_and_visit_type_are_listed_and_canonicalized(self) -> None:
        brain = LLMBrain(
            doctor_options=["Dr. Shaimaan"],
            department_options=["General Medicine"],
            visit_type_options=[
                "New Patient Consultation",
                "Follow-up Consultation",
                "Teleconsultation",
            ],
        )
        brain.start_conversation()
        for answer in (
            "Synthetic Canonical Patient",
            "35 years",
            "03000000128",
            "Yes, first visit",
            "No synthetic history",
            "Synthetic complaint",
        ):
            reply = brain.get_response(answer)

        self.assertIn("General Medicine", reply)
        reply = brain.get_response("general medicine")
        self.assertIn("General Medicine", reply)
        self.assertIn("Dr. Shaimaan", reply)

        reply = brain.get_response("no preference")
        self.assertIn("Dr. Shaimaan", reply)
        self.assertIn("New Patient Consultation", reply)
        self.assertIn("Follow-up Consultation", reply)
        self.assertIn("Teleconsultation", reply)

        reply = brain.get_response("consultation")
        data = brain.local_intake_data()
        self.assertIn("New Patient Consultation", reply)
        self.assertEqual(data["شعبہ"], "General Medicine")
        self.assertEqual(data["ڈاکٹر_کی_ترجیح"], "Dr. Shaimaan")
        self.assertEqual(data["ملاقات_کی_قسم"], "New Patient Consultation")

    def test_doctor_matching_accepts_display_variants_and_numbered_choice(self) -> None:
        practitioners = [
            {
                "practitioner_id": "DOC-SYNTHETIC-1",
                "display_name": "Ahmad_Ali",
            },
            {
                "practitioner_id": "DOC-SYNTHETIC-2",
                "display_name": "Dr.Shaimaan",
            },
        ]
        for spoken in ("Dr Shaimaan Qadir", "نمبر 2", "second doctor"):
            self.assertEqual(
                ReceptionistAgent._match_config_id(
                    practitioners,
                    "practitioner_id",
                    "display_name",
                    "",
                    spoken,
                ),
                "DOC-SYNTHETIC-2",
            )
        self.assertEqual(
            ReceptionistAgent._match_config_id(
                practitioners,
                "practitioner_id",
                "display_name",
                "",
                "Ahmad Ali Shaimaan",
            ),
            "",
        )

    def test_save_forward_action_confirms_summary_once(self) -> None:
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent._cb = {}
        agent._forward_requested = threading.Event()
        agent.llm = LLMBrain()
        self._fill(agent.llm)

        self.assertTrue(agent.request_forward())
        with patch.object(agent, "_on_complete", return_value=False) as forward:
            completed = agent._process_forward_request()

        self.assertFalse(completed)
        self.assertFalse(agent._forward_requested.is_set())
        self.assertTrue(agent.llm.is_complete())
        forward.assert_called_once_with()

    def test_save_forward_interrupts_microphone_wait_before_opening_device(self) -> None:
        recorder = AudioRecorder()
        interrupt = threading.Event()
        interrupt.set()

        with patch("receptionist.audio_recorder.sd.InputStream") as input_stream:
            result = recorder.record(interrupt_event=interrupt)

        self.assertIsNone(result)
        input_stream.assert_not_called()

    def test_short_confirmation_uses_more_sensitive_microphone_mode(self) -> None:
        class _SyntheticStream:
            def __init__(self) -> None:
                self._chunks = iter(
                    (
                        np.full((1600, 1), 0.005, dtype=np.float32),
                        np.zeros((1600, 1), dtype=np.float32),
                    )
                )

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size):
                return next(self._chunks), False

        recorder = AudioRecorder()
        recorder._max_chunks = 2
        recorder._silence_limit = 1

        with (
            patch("receptionist.audio_recorder.sd.InputStream", return_value=_SyntheticStream()),
            patch("builtins.print"),
        ):
            audio = recorder.record(short_response=True)

        self.assertIsNotNone(audio)
        assert audio is not None
        self.assertGreater(audio.size, 0)

    def test_intake_advances_locally_and_rejects_stt_noise(self) -> None:
        adapter = MockProviderAdapter()
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": adapter},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            greeting = brain.start_conversation()
            age_prompt = brain.get_response("Synthetic Voice Patient")
            rejected = brain.get_response("موسیقی")
            data_after_rejected = brain.local_intake_data()
            phone_prompt = brain.get_response("پینتیس سال")
        finally:
            set_gateway(None)

        self.assertIn("پورا نام", greeting)
        self.assertIn("عمر", age_prompt)
        self.assertNotIn("رابطہ عارضی", age_prompt)
        self.assertIn("عمر", rejected)
        self.assertNotIn("عمر", data_after_rejected)
        self.assertIn("موبائل نمبر", phone_prompt)
        self.assertEqual(brain.local_intake_data()["عمر"], "35")
        self.assertEqual(adapter.calls, [])

    def test_stt_retries_an_implausible_candidate_for_expected_field(self) -> None:
        brain = LLMBrain()
        brain.start_conversation()
        brain.get_response("Synthetic Voice Patient")
        engine = STTEngine.__new__(STTEngine)
        candidates = iter(("موسیقی", "پینتیس سال"))

        with patch.object(
            engine,
            "_transcribe_approved",
            side_effect=lambda *_args, **_kwargs: next(candidates),
        ) as transcribe:
            result = engine.transcribe(
                np.linspace(-0.1, 0.1, 1600, dtype=np.float32),
                expected_field=brain.expected_field(),
                validator=lambda text: brain.valid_answer("age", text),
            )

        self.assertEqual(result, "پینتیس سال")
        self.assertEqual(transcribe.call_count, 2)

    def test_age_and_name_are_validated_and_blood_pressure_is_not_required(self) -> None:
        brain = LLMBrain()
        self.assertFalse(brain.valid_answer("name", "123456"))
        self.assertFalse(brain.valid_answer("age", "موسیقی"))
        self.assertFalse(brain.valid_answer("age", "121 years"))
        self.assertTrue(brain.valid_answer("age", "پینتیس سال"))

        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                _settings(Path(directory)),
                receptionist_service_token=SERVICE_TOKEN,
            )
            app = create_app(settings)
            with TestClient(app) as client:
                base = {
                    "name": "Synthetic Validation Patient",
                    "age_text": "35",
                    "phone_number": "03000000444",
                    "first_visit": "Yes",
                    "past_medical_history": "No synthetic history",
                    "current_complaint": "Synthetic abdominal pain",
                    "intake_token": "synthetic-validation-session-token-0001",
                    "revision": 1,
                    "confirmed_revision": 1,
                }
                invalid_age = client.post(
                    "/api/receptionist/intakes",
                    headers=SERVICE_HEADERS,
                    json={**base, "age_text": "many years"},
                )
                self.assertEqual(invalid_age.status_code, 400)
                self.assertEqual(invalid_age.json()["detail"]["code"], "INVALID_AGE")

                valid = client.post(
                    "/api/receptionist/intakes",
                    headers=SERVICE_HEADERS,
                    json={**base, "age_text": "پینتیس سال"},
                )
                self.assertEqual(valid.status_code, 200, valid.text)
                patient = app.state.container.patient_repository.get(
                    valid.json()["patient_id"]
                )
                self.assertIsNotNone(patient)
                assert patient is not None
                self.assertEqual(patient.age_text, "35")
                self.assertEqual(patient.blood_pressure, "")

    def test_only_displayed_schedule_slots_are_accepted(self) -> None:
        options = [
            {
                "start_at": "2030-01-07T09:00:00+05:00",
                "label": "Monday, 07 January 2030 at 09:00 AM",
                "visit_type_id": "VISIT-NEW",
                "visit_type_name": "New Patient Consultation",
                "practitioner_name": "Dr. Shaimaan",
            },
            {
                "start_at": "2030-01-07T09:30:00+05:00",
                "label": "Monday, 07 January 2030 at 09:30 AM",
                "visit_type_id": "VISIT-NEW",
                "visit_type_name": "New Patient Consultation",
                "practitioner_name": "Dr. Shaimaan",
            },
        ]
        brain = LLMBrain(
            doctor_options=["Dr. Shaimaan"],
            department_options=["General Medicine"],
            visit_type_options=["New Patient Consultation"],
            booking_options=options,
        )
        brain.start_conversation()
        replies = []
        for answer in (
            "Synthetic Schedule Patient",
            "35",
            "03000000555",
            "Yes",
            "No synthetic history",
            "Synthetic complaint",
            "General Medicine",
            "no preference",
            "New Patient Consultation",
        ):
            replies.append(brain.get_response(answer))

        self.assertIn("1:", replies[-1])
        self.assertIn("Dr. Shaimaan", replies[-1])
        self.assertFalse(brain.valid_answer("booking_slot_time", "tomorrow at 14:00"))
        self.assertTrue(brain.valid_answer("booking_slot_time", "نمبر دو"))
        summary = brain.get_response("نمبر دو")
        self.assertEqual(
            brain.local_intake_data()["بکنگ_کا_وقت"],
            "2030-01-07T09:30:00+05:00",
        )
        self.assertIn("2030-01-07T09:30:00+05:00", summary)

    def test_booking_retry_reuses_intake_and_refreshes_visible_slots(self) -> None:
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent._pending = {
            "patient_id": "PT-SYNTHETIC-RETRY",
            "workflow_id": "WF-SYNTHETIC-RETRY",
            "data": {},
            "revision": 1,
        }
        agent._configuration = {
            "visit_types": [
                {
                    "visit_type_id": "VISIT-NEW",
                    "name": "New Patient Consultation",
                }
            ]
        }
        agent._booking_options = []
        agent._cb = {"schedule_options": Mock()}
        agent.api = Mock()
        agent.api.book.return_value = {
            "status": "ALTERNATIVES_REQUIRED",
            "alternatives": [
                {
                    "start_at": "2030-01-07T09:30:00+05:00",
                    "practitioner_id": "DOC-SYNTHETIC",
                    "practitioner_name": "Dr. Shaimaan",
                    "visit_type_id": "VISIT-NEW",
                }
            ],
        }
        agent.llm = Mock()
        agent._intake_token = "synthetic-retry-intake-session-token"
        agent.llm.record.revision = 2
        agent.llm.record.confirmed_revision = 2
        data = {
            "department_id": "DEP-GM",
            "practitioner_id": "DOC-SYNTHETIC",
            "visit_type_id": "VISIT-NEW",
            "بکنگ_کا_وقت": "2030-01-07T09:00:00+05:00",
        }

        message, complete = agent._attempt_booking(data)

        self.assertFalse(complete)
        self.assertIn("نمبر 1", message)
        self.assertEqual(
            agent._booking_options[0]["start_at"],
            "2030-01-07T09:30:00+05:00",
        )
        agent.llm.set_booking_options.assert_called_once_with(
            agent._booking_options
        )
        agent._cb["schedule_options"].assert_called_once()

        agent.llm.extract_patient_data.return_value = data
        agent.api.update_intake.return_value = {
            "patient_id": agent._pending["patient_id"],
            "workflow_id": agent._pending["workflow_id"],
            "revision": 2,
        }
        agent._normalise_selection = Mock(return_value=(data, ""))
        agent._attempt_booking = Mock(return_value=("Synthetic retry", False))
        agent._deliver_followup = Mock()
        with patch("builtins.print"):
            result = agent._on_complete()

        self.assertFalse(result)
        agent.api.create_intake.assert_not_called()
        agent._attempt_booking.assert_called_once_with(data)

    def test_receptionist_stt_context_has_no_otp_state(self) -> None:
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent.llm = LLMBrain()
        agent.llm.start_conversation()

        expected_field, validator = agent._stt_turn_context()

        self.assertEqual(expected_field, "name")
        self.assertIsNotNone(validator)
        assert validator is not None
        self.assertTrue(validator("Synthetic Patient"))
        self.assertTrue(validator("123456"))
        self.assertFalse(validator("موسیقی"))


    def test_complete_local_intake_never_calls_provider(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "intake_extract",
            {
                "نام": "[PATIENT_NAME]",
                "عمر": "34",
                "فون_نمبر": "[PHONE]",
                "پہلی_بار": "",
                "پچھلی_بیماریاں": "",
                "آج_کی_شکایت": "",
                "شعبہ": "",
                "department_id": "",
                "ڈاکٹر_کی_ترجیح": "",
                "practitioner_id": "",
                "ملاقات_کی_قسم": "",
                "visit_type_id": "",
                "بکنگ_کا_وقت": "",
            },
        )
        set_gateway(
            SecureLLMGateway(
                provider="mock",
                adapters={"mock": adapter},
            )
        )
        try:
            brain = LLMBrain(schedule_context="Synthetic server-controlled schedule")
            turns = [
                ("آپ کا پورا نام کیا ہے؟", "Synthetic Local Intake Patient"),
                ("آپ کی عمر کیا ہے؟", "34 سال"),
                ("آپ کا موبائل نمبر کیا ہے؟", "03000000123"),
                ("کیا آپ پہلی بار آ رہے ہیں؟", "جی ہاں پہلی بار"),
                ("کوئی پچھلی بیماری یا طبی تاریخ؟", "کوئی نہیں"),
                ("آج آپ کو کیا تکلیف ہے؟", "مصنوعی پیٹ درد"),
                ("آپ کس شعبے میں ملاقات چاہتے ہیں؟", "جنرل میڈیسن"),
                ("کیا کسی خاص ڈاکٹر کو ترجیح ہے؟", "کوئی خاص ترجیح نہیں"),
                ("ملاقات کی قسم کیا ہوگی؟", "نئی مریض ملاقات"),
                ("اپائنٹمنٹ کی تاریخ اور وقت بتائیں۔", "کل دوپہر دو بجے"),
                ("کیا یہ سب معلومات درست ہیں؟", "جی ہاں، بک کر دیں"),
            ]
            brain.start_conversation()
            for assistant_text, patient_text in turns:
                brain.get_response(patient_text)
            extracted = brain.extract_patient_data()
        finally:
            set_gateway(None)

        self.assertTrue(all(call["task_type"] == "intake_intent" for call in adapter.calls))
        self.assertEqual(extracted["نام"], "Synthetic Local Intake Patient")
        self.assertEqual(extracted["فون_نمبر"], "03000000123")
        self.assertEqual(extracted["پہلی_بار"], "Yes")
        self.assertEqual(extracted["پچھلی_بیماریاں"], "کوئی نہیں")
        self.assertEqual(extracted["آج_کی_شکایت"], "مصنوعی پیٹ درد")
        self.assertEqual(extracted["بکنگ_کا_وقت"], "کل دوپہر دو بجے")

    def test_urdu_relative_slot_and_visit_type_are_normalized_locally(self) -> None:
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent._configuration = {
            "clinic": {
                "timezone": "Asia/Karachi",
                "current_time": "2026-07-26T14:00:00+05:00",
            },
            "departments": [
                {
                    "department_id": "DEP-GM",
                    "name": "General Medicine",
                }
            ],
            "practitioners": [
                {
                    "practitioner_id": "DOC-SYNTHETIC",
                    "display_name": "Synthetic Doctor",
                    "department_id": "DEP-GM",
                }
            ],
            "visit_types": [
                {
                    "visit_type_id": "VISIT-NEW",
                    "name": "New Patient Consultation",
                    "mode": "IN_PERSON",
                },
                {
                    "visit_type_id": "VISIT-FOLLOWUP",
                    "name": "Follow-up Consultation",
                    "mode": "IN_PERSON",
                },
                {
                    "visit_type_id": "VISIT-TELE",
                    "name": "Teleconsultation",
                    "mode": "REMOTE",
                },
            ],
        }
        normalized, error = agent._normalise_selection(
            {
                "شعبہ": "جنرل میڈیسن",
                "ڈاکٹر_کی_ترجیح": "کوئی خاص ترجیح نہیں",
                "ملاقات_کی_قسم": "نئی مریض ملاقات",
                "پہلی_بار": "جی ہاں پہلی بار",
                "بکنگ_کا_وقت": "کل دوپہر دو بجے",
            }
        )
        self.assertEqual(error, "")
        self.assertEqual(normalized["department_id"], "DEP-GM")
        self.assertEqual(normalized["visit_type_id"], "VISIT-NEW")
        self.assertEqual(normalized["بکنگ_کا_وقت"], "2026-07-27 14:00")
        self.assertEqual(
            agent._resolve_booking_slot("tomorrow at 14:00"),
            "2026-07-27 14:00",
        )

    def test_receptionist_booking_reaches_assigned_doctor_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                _settings(Path(directory)),
                receptionist_service_token=SERVICE_TOKEN,
            )
            app = create_app(settings)
            with TestClient(app) as client:
                self.assertEqual(
                    client.get("/api/receptionist/configuration").status_code,
                    401,
                )
                self.assertEqual(
                    client.get("/api/notes", headers=SERVICE_HEADERS).status_code,
                    401,
                )
                self.assertEqual(
                    client.post(
                        "/api/receptionist/verification/not-available",
                        headers=SERVICE_HEADERS,
                        json={"code": "123456"},
                    ).status_code,
                    404,
                )

                signup = client.post(
                    "/api/auth/signup",
                    json={
                        "full_name": "Dr. Synthetic Queue",
                        "email": "queue-doctor@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(signup.status_code, 200)
                doctor = signup.json()["user"]

                configuration = client.get(
                    "/api/receptionist/configuration",
                    headers=SERVICE_HEADERS,
                )
                self.assertEqual(configuration.status_code, 200)
                profiles = configuration.json()["practitioners"]
                self.assertEqual(
                    {item["practitioner_id"] for item in profiles},
                    {doctor["practitioner_id"]},
                )
                profile = profiles[0]

                intake = self._intake(client, "001")
                patient_id = intake["patient_id"]
                workflow_id = intake["workflow_id"]
                self.assertEqual(intake["workflow_state"], "PATIENT_UNVERIFIED")
                self.assertTrue(intake["verification_required_at_doctor"])
                self.assertNotIn("challenge", intake)

                availability = client.get(
                    "/api/receptionist/availability",
                    headers=SERVICE_HEADERS,
                    params={
                        "practitioner_id": doctor["practitioner_id"],
                        "visit_type_id": "VISIT-NEW",
                        "days": 14,
                        "limit": 8,
                    },
                )
                self.assertEqual(availability.status_code, 200, availability.text)
                slots = availability.json()["slots"]
                self.assertTrue(slots)
                start_at = slots[0]["start_at"]

                booking = client.post(
                    "/api/receptionist/bookings",
                    headers=SERVICE_HEADERS,
                    json={
                        "patient_id": patient_id,
                        "workflow_id": workflow_id,
                        "department_id": profile["department_id"],
                        "practitioner_id": "",
                        "visit_type_id": "VISIT-NEW",
                        "start_at": start_at,
                        "idempotency_key": "synthetic-reception-booking-001",
                        "intake_token": intake["intake_token"],
                        "revision": intake["revision"],
                    },
                )
                self.assertEqual(booking.status_code, 200, booking.text)
                booking_payload = booking.json()
                self.assertEqual(booking_payload["status"], "REQUESTED")
                self.assertEqual(
                    booking_payload["appointment"]["status"],
                    "REQUESTED",
                )
                self.assertEqual(
                    booking_payload["appointment"]["practitioner_id"],
                    doctor["practitioner_id"],
                )
                self.assertEqual(
                    booking_payload["workflow_state"],
                    "PATIENT_UNVERIFIED",
                )

                login = client.post(
                    "/api/auth/login",
                    json={
                        "email": "queue-doctor@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(login.status_code, 200)
                queue = client.get("/api/appointments/doctor-queue")
                self.assertEqual(queue.status_code, 200, queue.text)
                queue_items = queue.json()["appointments"]
                self.assertEqual(len(queue_items), 1)
                self.assertEqual(queue_items[0]["patient_id"], patient_id)
                self.assertEqual(queue_items[0]["status"], "REQUESTED")
                self.assertEqual(queue_items[0]["workflow_state"], "PATIENT_UNVERIFIED")
                self.assertEqual(queue_items[0]["blood_pressure"], "")
                blocked_check_in = client.post(
                    f"/api/workflows/{workflow_id}/check-in"
                )
                self.assertEqual(blocked_check_in.status_code, 400)

                patients = client.get("/api/patients")
                self.assertEqual(patients.status_code, 200)
                booked_patient = next(
                    item for item in patients.json()
                    if item["patient_id"] == patient_id
                )
                self.assertEqual(booked_patient["booking_slot_time"], start_at)

                challenge = client.post(
                    "/api/verification/challenges",
                    json={"patient_id": patient_id, "workflow_id": workflow_id},
                )
                self.assertEqual(challenge.status_code, 200, challenge.text)
                self.assertIsNone(challenge.json()["development_otp"])
                verified = client.post(
                    f"/api/verification/challenges/{challenge.json()['challenge_id']}/verify",
                    json={"code": "123456"},
                )
                self.assertEqual(verified.status_code, 200, verified.text)
                completed_intake = client.post(
                    f"/api/workflows/{workflow_id}/complete-intake"
                )
                self.assertEqual(completed_intake.status_code, 200, completed_intake.text)
                self.assertEqual(
                    completed_intake.json()["workflow"]["state"],
                    "BOOKING_CONFIRMED",
                )
                confirmed = app.state.container.appointment_repository.get(
                    booking_payload["appointment"]["appointment_id"]
                )
                self.assertIsNotNone(confirmed)
                self.assertEqual(confirmed.status.value, "CONFIRMED")

                replay = client.post(
                    "/api/receptionist/bookings",
                    headers=SERVICE_HEADERS,
                    json={
                        "patient_id": patient_id,
                        "workflow_id": workflow_id,
                        "department_id": profile["department_id"],
                        "practitioner_id": "",
                        "visit_type_id": "VISIT-NEW",
                        "start_at": start_at,
                        "idempotency_key": "synthetic-reception-booking-001",
                        "intake_token": intake["intake_token"],
                        "revision": intake["revision"],
                    },
                )
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(replay.json()["status"], "BOOKED")
                self.assertEqual(
                    replay.json()["appointment"]["appointment_id"],
                    booking_payload["appointment"]["appointment_id"],
                )

                second = self._intake(client, "002")
                conflict = client.post(
                    "/api/receptionist/bookings",
                    headers=SERVICE_HEADERS,
                    json={
                        "patient_id": second["patient_id"],
                        "workflow_id": second["workflow_id"],
                        "department_id": profile["department_id"],
                        "practitioner_id": doctor["practitioner_id"],
                        "visit_type_id": "VISIT-NEW",
                        "start_at": start_at,
                        "idempotency_key": "synthetic-reception-booking-002",
                        "intake_token": second["intake_token"],
                        "revision": second["revision"],
                    },
                )
                self.assertEqual(conflict.status_code, 200, conflict.text)
                self.assertEqual(
                    conflict.json()["status"],
                    "ALTERNATIVES_REQUIRED",
                )
                self.assertTrue(conflict.json()["alternatives"])
                self.assertFalse(
                    app.state.container.appointment_repository.list(
                        patient_id=second["patient_id"]
                    )
                )

                cross_patient = client.post(
                    "/api/receptionist/bookings",
                    headers=SERVICE_HEADERS,
                    json={
                        "patient_id": second["patient_id"],
                        "workflow_id": workflow_id,
                        "department_id": profile["department_id"],
                        "practitioner_id": doctor["practitioner_id"],
                        "visit_type_id": "VISIT-NEW",
                        "start_at": conflict.json()["alternatives"][0]["start_at"],
                        "idempotency_key": "synthetic-cross-patient-booking",
                        "intake_token": second["intake_token"],
                        "revision": second["revision"],
                    },
                )
                self.assertEqual(cross_patient.status_code, 403)

                queue = client.get("/api/appointments/doctor-queue")
                self.assertEqual(queue.status_code, 200, queue.text)
                queue_items = queue.json()["appointments"]
                self.assertEqual(len(queue_items), 1)
                self.assertEqual(queue_items[0]["patient_id"], patient_id)
                self.assertEqual(queue_items[0]["status"], "CONFIRMED")
                self.assertEqual(
                    queue_items[0]["current_complaint"],
                    "Synthetic complaint 001",
                )


if __name__ == "__main__":
    unittest.main()
