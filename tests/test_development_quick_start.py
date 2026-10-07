from __future__ import annotations

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from medflow.domain.enums import AppointmentStatus, EncounterStatus, WorkflowState
from medflow.domain.models import Patient
from tests.test_central_app_auth import _settings


class DevelopmentQuickStartTests(unittest.TestCase):
    @staticmethod
    def _login_development_doctor(client: TestClient, app, patient: Patient) -> dict:
        signup = client.post(
            "/api/auth/signup",
            json={
                "full_name": "Dr. Synthetic Quick Start",
                "email": "quick-start@example.test",
                "password": "SyntheticPass123!",
            },
        )
        assert signup.status_code == 200
        user = signup.json()["user"]
        app.state.container.auth_repository.assign_patient(
            user["practitioner_id"],
            patient.patient_id,
        )
        login = client.post(
            "/api/auth/login",
            json={
                "email": "quick-start@example.test",
                "password": "SyntheticPass123!",
            },
        )
        assert login.status_code == 200
        return user

    def test_quick_start_creates_recording_ready_context_and_resets_previous_visit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                _settings(Path(directory)),
                app_env="development",
                development_quick_start_enabled=True,
            )
            app = create_app(settings)
            patient = Patient(
                patient_id="PT-DEMO-SYNTHETIC-901",
                name="Synthetic Quick Start Patient",
                phone_number="03000000901",
                current_complaint="Synthetic testing complaint",
            )
            app.state.container.patient_repository.save(patient)

            with TestClient(app) as client:
                self._login_development_doctor(client, app, patient)
                first = client.post(
                    "/api/workflows/development/quick-start",
                    json={"patient_id": patient.patient_id},
                )
                self.assertEqual(first.status_code, 200, first.text)
                first_payload = first.json()
                self.assertEqual(first_payload["workflow"]["state"], "CONSULTATION_READY")
                self.assertEqual(first_payload["appointment"]["status"], "CHECKED_IN")
                self.assertEqual(first_payload["encounter"]["status"], "READY")
                decisions = {
                    item["consent_type"]: item["decision"]
                    for item in first_payload["consents"]
                }
                self.assertTrue(decisions["AUDIO_RECORDING"])
                self.assertTrue(decisions["AI_TRANSCRIPTION"])
                self.assertTrue(decisions["AI_DOCUMENTATION"])
                self.assertFalse(decisions["AUDIO_RETENTION"])
                self.assertFalse(first_payload["audio_retention"])

                first_workflow_id = first_payload["workflow"]["workflow_id"]
                first_appointment_id = first_payload["appointment"]["appointment_id"]
                first_encounter_id = first_payload["encounter"]["encounter_id"]
                second = client.post(
                    "/api/workflows/development/quick-start",
                    json={"patient_id": patient.patient_id},
                )
                self.assertEqual(second.status_code, 200, second.text)
                second_payload = second.json()
                self.assertNotEqual(second_payload["workflow"]["workflow_id"], first_workflow_id)
                self.assertEqual(second_payload["workflow"]["state"], "CONSULTATION_READY")
                self.assertEqual(second_payload["cancelled_workflow_count"], 1)

                container = app.state.container
                self.assertEqual(
                    container.workflow_repository.get(first_workflow_id).state,
                    WorkflowState.CANCELLED,
                )
                self.assertEqual(
                    container.appointment_repository.get(first_appointment_id).status,
                    AppointmentStatus.CANCELLED,
                )
                self.assertEqual(
                    container.encounter_repository.get(first_encounter_id).status,
                    EncounterStatus.CANCELLED,
                )

    def test_quick_start_is_hidden_outside_development(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(Path(directory))
            app = create_app(settings)
            patient = Patient(
                patient_id="PT-DEMO-SYNTHETIC-902",
                name="Synthetic Disabled Quick Start Patient",
                phone_number="03000000902",
            )
            app.state.container.patient_repository.save(patient)
            with TestClient(app) as client:
                self._login_development_doctor(client, app, patient)
                response = client.post(
                    "/api/workflows/development/quick-start",
                    json={"patient_id": patient.patient_id},
                )
            self.assertEqual(response.status_code, 404)

    def test_quick_start_rejects_non_synthetic_patient(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                _settings(Path(directory)),
                app_env="development",
                development_quick_start_enabled=True,
            )
            app = create_app(settings)
            patient = Patient(
                patient_id="PT-NOT-A-DEMO-001",
                name="Synthetic Negative Test",
                phone_number="03000000903",
            )
            app.state.container.patient_repository.save(patient)
            with TestClient(app) as client:
                self._login_development_doctor(client, app, patient)
                response = client.post(
                    "/api/workflows/development/quick-start",
                    json={"patient_id": patient.patient_id},
                )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["detail"]["code"], "SYNTHETIC_PATIENT_REQUIRED")

    def test_configuration_rejects_quick_start_outside_development(self) -> None:
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "SHOW_DEV_OTP": "false",
                "DEVELOPMENT_QUICK_START_ENABLED": "true",
                "SESSION_SECRET": "synthetic-production-session-secret-at-least-32-characters",
                "OTP_SECRET": "synthetic-production-otp-secret-at-least-32-characters",
            },
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "DEVELOPMENT_QUICK_START_ENABLED"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
