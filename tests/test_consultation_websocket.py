from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.container import ApplicationContainer
from app.main import create_app
from app.services import AppointmentRequest
from medflow.domain.enums import ConsentType, WorkflowState
from medflow.domain.models import Patient
from medflow.orchestration import WorkflowAction
from security_guardrails import Actor, SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter
from tests.support import test_settings


class ConsultationWebSocketTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    def _ready_context(self, root: Path):
        settings = test_settings(root)
        container = ApplicationContainer(settings)
        container.initialize()
        patient = container.patient_repository.save(
            Patient(
                patient_id="PT-SYNTHETIC-WS-001",
                name="Synthetic WebSocket Patient",
                phone_number="03001112222",
                current_complaint="Synthetic consultation",
            )
        )
        user = container.auth_repository.create_doctor(
            "Dr. Synthetic WebSocket",
            "websocket@example.test",
            "SyntheticPass123!",
        )
        assert user.practitioner_id
        container.auth_repository.assign_patient(user.practitioner_id, patient.patient_id)
        actor = Actor(str(user.user_id), "doctor", {patient.patient_id}, patient.patient_id)
        workflow = container.lifecycle_service.get_or_create_workflow(patient_id=patient.patient_id, actor=actor)
        workflow = container.workflow_orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.VERIFY_PATIENT,
            actor=actor,
            expected_version=workflow.version,
        )
        workflow = container.lifecycle_service.complete_existing_intake(workflow.workflow_id, actor=actor)
        profile = container.clinic_repository.get_practitioner(user.practitioner_id)
        slots = container.appointment_service.availability(
            patient_id=patient.patient_id,
            practitioner_id=user.practitioner_id,
            visit_type_id="VISIT-NEW",
            start_date=date.today() + timedelta(days=2),
            days=7,
        )
        appointment = container.appointment_service.create(
            AppointmentRequest(
                patient_id=patient.patient_id,
                practitioner_id=user.practitioner_id,
                department_id=profile["department_id"],
                location_id=profile["location_id"],
                visit_type_id="VISIT-NEW",
                start_at=datetime.fromisoformat(slots[0]["start_at"]),
                idempotency_key="synthetic-websocket-booking-001",
            ),
            actor=actor,
        )
        workflow = container.lifecycle_service.confirm_booking(
            workflow.workflow_id,
            appointment=appointment,
            actor=actor,
        )
        context = container.lifecycle_service.check_in(workflow.workflow_id, actor=actor)
        return settings, container, patient, user, actor, context

    def test_flow_03_and_04_backend_blocks_then_allows_recording(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings, setup, patient, _, actor, context = self._ready_context(Path(directory))
            adapter = MockProviderAdapter()
            set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
            app = create_app(settings)

            with TestClient(app) as client:
                login = client.post(
                    "/api/auth/login",
                    json={"email": "websocket@example.test", "password": "SyntheticPass123!"},
                )
                self.assertEqual(login.status_code, 200)
                start_payload = {
                    "type": "start",
                    "patient_id": patient.patient_id,
                    "workflow_id": context.workflow.workflow_id,
                    "encounter_id": context.encounter.encounter_id,
                    "sample_rate": 16_000,
                    "capture_id": "capture-websocket-test",
                    "template_id": "TPL-SHORT-01",
                    "audio_retention_requested": True,
                }
                with client.websocket_connect("/ws") as websocket:
                    websocket.send_text(json.dumps(start_payload))
                    denied = websocket.receive_json()
                    self.assertEqual(denied["type"], "error")
                    self.assertEqual(denied["code"], "REQUIRED_CONSENT_MISSING")

                setup.consent_service.capture_bundle(
                    encounter_id=context.encounter.encounter_id,
                    decisions={
                        ConsentType.AUDIO_RECORDING: True,
                        ConsentType.AI_TRANSCRIPTION: True,
                        ConsentType.AI_DOCUMENTATION: True,
                        ConsentType.AUDIO_RETENTION: False,
                    },
                    consent_text_version="CONSENT-V1",
                    capture_method="SYNTHETIC_TEST",
                    actor=actor,
                )

                with client.websocket_connect("/ws") as websocket:
                    websocket.send_text(json.dumps(start_payload))
                    started = websocket.receive_json()
                    self.assertEqual(started["type"], "recording_started")
                    self.assertFalse(started["audio_retention"])
                    websocket.send_bytes(bytes(32_000))
                    websocket.send_text(json.dumps({"type": "stop"}))
                    messages = []
                    while True:
                        message = websocket.receive_json()
                        messages.append(message)
                        self.assertEqual(message["patient_id"], patient.patient_id)
                        self.assertEqual(message["workflow_id"], context.workflow.workflow_id)
                        self.assertEqual(message["encounter_id"], context.encounter.encounter_id)
                        self.assertEqual(message["capture_id"], "capture-websocket-test")
                        if message["type"] in {"soap_note", "error"}:
                            break

                self.assertEqual(messages[-1]["type"], "soap_note", messages[-1])
                self.assertEqual(messages[-1]["note_state"], "AI_DRAFT")
                self.assertTrue(messages[-1]["note_id"].startswith("NOTE-"))
                self.assertEqual(
                    messages[-1]["english_transcript"][0]["utterance_id"],
                    messages[-1]["urdu_transcript"][0]["utterance_id"],
                )
                self.assertEqual(
                    messages[-1]["soap"]["audio_retention"]["state"],
                    "AUDIO_DELETED",
                )
                note = app.state.container.note_repository.get(messages[-1]["note_id"])
                self.assertIsNotNone(note)
                version = app.state.container.note_repository.get_version(note.current_version_id)
                self.assertEqual(version.template_id, "TPL-SHORT-01")
                workflow = app.state.container.workflow_repository.get(context.workflow.workflow_id)
                self.assertEqual(
                    workflow.state,
                    WorkflowState.NOTE_REVIEW_REQUIRED,
                )


if __name__ == "__main__":
    unittest.main()
