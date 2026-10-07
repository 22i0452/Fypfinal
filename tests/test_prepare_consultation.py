from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from medflow.domain.enums import WorkflowState
from medflow.domain.models import Patient
from tests.test_central_app_auth import _settings


class PrepareConsultationTests(unittest.TestCase):
    def test_prepare_consultation_skips_to_consent_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(
                _settings(Path(directory)),
                app_env="development",
                development_quick_start_enabled=True,
            )
            app = create_app(settings)
            patient = Patient(
                patient_id="PT-CONSENT-FLOW-001",
                name="Consent Flow Patient",
                phone_number="03000000123",
                current_complaint="Synthetic testing complaint",
            )
            app.state.container.patient_repository.save(patient)

            with TestClient(app) as client:
                signup = client.post(
                    "/api/auth/signup",
                    json={
                        "full_name": "Dr. Consent Flow",
                        "email": "consent-flow@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(signup.status_code, 200)
                user = signup.json()["user"]
                app.state.container.auth_repository.assign_patient(
                    user["practitioner_id"],
                    patient.patient_id,
                )
                login = client.post(
                    "/api/auth/login",
                    json={
                        "email": "consent-flow@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(login.status_code, 200)

                response = client.post(
                    "/api/workflows/prepare-consultation",
                    json={"patient_id": patient.patient_id},
                )
                self.assertEqual(response.status_code, 200, response.text)
                payload = response.json()
                self.assertEqual(payload["workflow"]["state"], "CONSULTATION_READY")
                self.assertTrue(payload["encounter"]["encounter_id"])
                self.assertTrue(payload["appointment"]["appointment_id"])
                # Consent is intentionally left for the doctor UI.
                self.assertEqual(payload["consents"], [])

                first_workflow_id = payload["workflow"]["workflow_id"]
                workflow = app.state.container.workflow_repository.get(first_workflow_id)
                app.state.container.workflow_repository.save(
                    workflow.model_copy(
                        update={
                            "state": WorkflowState.NOTE_REVIEW_REQUIRED,
                            "version": workflow.version + 1,
                        }
                    ),
                    expected_version=workflow.version,
                )

                again = client.post(
                    "/api/workflows/prepare-consultation",
                    json={"patient_id": patient.patient_id},
                )
                self.assertEqual(again.status_code, 200, again.text)
                again_payload = again.json()
                self.assertEqual(again_payload["workflow"]["state"], "NOTE_REVIEW_REQUIRED")
                self.assertEqual(again_payload["workflow"]["workflow_id"], first_workflow_id)
                self.assertEqual(again_payload["cancelled_workflow_count"], 0)


if __name__ == "__main__":
    unittest.main()
