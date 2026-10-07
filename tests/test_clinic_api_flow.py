from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from medflow.domain.models import Patient
from tests.test_central_app_auth import _settings


class ClinicAPIFlowTests(unittest.TestCase):
    def test_verified_patient_can_book_check_in_and_grant_consents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(Path(directory))
            app = create_app(settings)
            patient = Patient(
                patient_id="PT-SYNTHETIC-API-001",
                name="Synthetic API Patient",
                phone_number="03001234567",
                current_complaint="Synthetic follow-up",
            )
            app.state.container.patient_repository.save(patient)

            with TestClient(app) as client:
                signup = client.post(
                    "/api/auth/signup",
                    json={
                        "full_name": "Dr. Synthetic API",
                        "email": "api-doctor@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(signup.status_code, 200)
                user = signup.json()["user"]
                app.state.container.auth_repository.assign_patient(
                    user["practitioner_id"], patient.patient_id
                )
                self.assertEqual(
                    client.post(
                        "/api/auth/login",
                        json={
                            "email": "api-doctor@example.test",
                            "password": "SyntheticPass123!",
                        },
                    ).status_code,
                    200,
                )

                workflow_response = client.post(
                    "/api/workflows", json={"patient_id": patient.patient_id}
                )
                self.assertEqual(workflow_response.status_code, 200)
                workflow_id = workflow_response.json()["workflow"]["workflow_id"]

                challenge = client.post(
                    "/api/verification/challenges",
                    json={"patient_id": patient.patient_id, "workflow_id": workflow_id},
                )
                self.assertEqual(challenge.status_code, 200)
                self.assertIsNone(challenge.json()["development_otp"])
                challenge_id = challenge.json()["challenge_id"]
                verified = client.post(
                    f"/api/verification/challenges/{challenge_id}/verify",
                    json={"code": "123456"},
                )
                self.assertEqual(verified.status_code, 200)

                intake = client.post(f"/api/workflows/{workflow_id}/complete-intake")
                self.assertEqual(intake.status_code, 200)
                self.assertEqual(intake.json()["workflow"]["state"], "BOOKING_REQUIRED")

                config = client.get("/api/appointments/configuration").json()
                own_profile = next(
                    item for item in config["practitioners"] if item["practitioner_id"] == user["practitioner_id"]
                )
                slots = client.get(
                    "/api/appointments/availability",
                    params={
                        "patient_id": patient.patient_id,
                        "practitioner_id": user["practitioner_id"],
                        "visit_type_id": "VISIT-NEW",
                        "start_date": (date.today() + timedelta(days=2)).isoformat(),
                        "days": 7,
                    },
                )
                self.assertEqual(slots.status_code, 200)
                start_at = slots.json()["slots"][0]["start_at"]
                booking = client.post(
                    "/api/appointments",
                    json={
                        "patient_id": patient.patient_id,
                        "practitioner_id": user["practitioner_id"],
                        "department_id": own_profile["department_id"],
                        "location_id": own_profile["location_id"],
                        "visit_type_id": "VISIT-NEW",
                        "start_at": start_at,
                        "idempotency_key": "synthetic-api-booking-001",
                        "workflow_id": workflow_id,
                    },
                )
                self.assertEqual(booking.status_code, 200)
                self.assertEqual(booking.json()["workflow"]["state"], "BOOKING_CONFIRMED")

                checked_in = client.post(f"/api/workflows/{workflow_id}/check-in")
                self.assertEqual(checked_in.status_code, 200)
                self.assertEqual(checked_in.json()["workflow"]["state"], "CONSULTATION_READY")
                encounter_id = checked_in.json()["encounter"]["encounter_id"]

                consent = client.post(
                    "/api/consents",
                    json={
                        "encounter_id": encounter_id,
                        "audio_recording": True,
                        "ai_transcription": True,
                        "ai_documentation": True,
                        "audio_retention": False,
                    },
                )
                self.assertEqual(consent.status_code, 200)
                decisions = {
                    item["consent_type"]: item["decision"] for item in consent.json()["consents"]
                }
                self.assertTrue(decisions["AUDIO_RECORDING"])
                self.assertFalse(decisions["AUDIO_RETENTION"])


if __name__ == "__main__":
    unittest.main()
