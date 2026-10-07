"""Ending a demo booking call saves the patient intake and requests the appointment."""
from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_central_app_auth import _settings


SERVICE_TOKEN = "synthetic-receptionist-service-token-at-least-32-characters"
SCENARIO = "in-new-booking"


def _answer(key: str, ur: str, en: str | None = None, **extra: str) -> dict:
    return {"intent": "answer", "fields": {key: {"ur": ur, "en": en or ur, **extra}}, "fix": []}


YES = {"intent": "yes", "fields": {}, "fix": []}


class DemoCallFinishTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = replace(
            _settings(Path(directory.name)),
            receptionist_service_token=SERVICE_TOKEN,
            groq_api_key="",
            openrouter_api_key="",
        )
        self.client = TestClient(create_app(settings))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        # A doctor with a dashboard account makes General Medicine bookable.
        signup = self.client.post(
            "/api/auth/signup",
            json={"full_name": "Dr. Synthetic Demo", "email": "demo-doctor@example.test", "password": "SyntheticPass123!"},
        )
        self.assertEqual(signup.status_code, 200, signup.text)
        self.doctor = signup.json()["user"]
        self.client.cookies.clear()
        self.service = self.client.app.state.container.demo_call_service

    def _first_open_slot(self) -> str:
        response = self.client.get(
            "/api/desk/availability",
            params={"practitioner_id": self.doctor["practitioner_id"], "visit_type_id": "VISIT-NEW"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return datetime.fromisoformat(response.json()["slots"][0]["start_at"]).replace(tzinfo=None).isoformat(timespec="minutes")

    def _call(self, extractions: list[dict]) -> list[dict]:
        queue = list(extractions)
        self.service._extract = lambda flow, text: queue.pop(0)
        history = self.client.post("/api/desk/demo-calls/start", json={"scenario_id": SCENARIO}).json()["history"]
        for _ in extractions:
            response = self.client.post(
                "/api/desk/demo-calls/turn",
                json={"scenario_id": SCENARIO, "history": history, "user_message": "..."},
            )
            self.assertEqual(response.status_code, 200, response.text)
            history = response.json()["history"]
        return history

    def _full_call(self, iso: str) -> list[dict]:
        return self._call([
            _answer("name", "شہزیب علی خان", "Shahzaib Ali Khan"), YES,
            _answer("age", "22"), YES,
            _answer("phone", "03037556360"), YES,
            _answer("first_visit", "جی ہاں", "Yes"),
            _answer("history", "کوئی نہیں", "None"),
            _answer("complaint", "گھٹنے میں شدید درد", "Severe knee pain"),
            _answer("department", "جنرل میڈیسن", "General Medicine"),
            _answer("doctor", "کوئی بھی دستیاب ڈاکٹر", "Any available doctor"),
            _answer("time", "صبح", "requested slot", iso=iso), YES,
            YES,
        ])

    def _finish(self, history: list[dict]) -> dict:
        response = self.client.post("/api/desk/demo-calls/finish", json={"scenario_id": SCENARIO, "history": history})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_completed_call_saves_patient_and_requests_appointment(self) -> None:
        slot = self._first_open_slot()
        result = self._finish(self._full_call(slot))

        self.assertTrue(result["saved"])
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["booking"]["status"], "REQUESTED")
        self.assertEqual(result["booking"]["appointment"]["practitioner_id"], self.doctor["practitioner_id"])
        self.assertEqual(result["booking"]["appointment"]["visit_type_id"], "VISIT-NEW")
        details = {row["key"]: row["en"] for row in result["details"]}
        self.assertEqual(details["name"], "Shahzaib Ali Khan")
        self.assertEqual(details["phone"], "0303 755 6360")

        patient = self.client.app.state.container.patient_repository.get(result["patient_id"])
        self.assertEqual(patient.name, "Shahzaib Ali Khan")
        self.assertEqual(patient.age_text, "22")
        self.assertEqual(patient.phone_number, "03037556360")
        self.assertEqual(patient.current_complaint, "Severe knee pain")

    def test_ending_twice_does_not_duplicate_the_patient(self) -> None:
        history = self._full_call(self._first_open_slot())
        first = self._finish(history)
        second = self._finish(history)
        self.assertEqual(first["patient_id"], second["patient_id"])
        self.assertEqual(
            first["booking"]["appointment"]["appointment_id"],
            second["booking"]["appointment"]["appointment_id"],
        )

    def test_time_outside_clinic_hours_offers_alternatives(self) -> None:
        # 07:00 is before the clinic opens at 09:00.
        slot = datetime.fromisoformat(self._first_open_slot()).replace(hour=7, minute=0).isoformat(timespec="minutes")
        result = self._finish(self._full_call(slot))

        self.assertTrue(result["saved"])
        self.assertEqual(result["booking"]["status"], "ALTERNATIVES_REQUIRED")
        self.assertTrue(result["booking"]["alternatives"])

        option = result["booking"]["alternatives"][0]
        booked = self.client.post(
            "/api/desk/bookings",
            json={
                "patient_id": result["patient_id"],
                "workflow_id": result["workflow_id"],
                "department_id": option["department_id"],
                "practitioner_id": option["practitioner_id"],
                "visit_type_id": option["visit_type_id"],
                "start_at": option["start_at"],
                "idempotency_key": f"demo-alt-{result['intake_token']}",
                "intake_token": result["intake_token"],
                "revision": result["revision"],
            },
        )
        self.assertEqual(booked.status_code, 200, booked.text)
        self.assertEqual(booked.json()["status"], "REQUESTED")

    def test_call_ended_early_is_not_saved(self) -> None:
        history = self._call([_answer("name", "شہزیب", "Shahzaib"), YES, _answer("age", "22"), YES])
        result = self._finish(history)
        self.assertFalse(result["saved"])
        self.assertEqual(result["missing"], ["Phone", "First visit", "Medical history", "Complaint"])
        self.assertEqual([row["key"] for row in result["details"]], ["name", "age"])

    def test_unconfirmed_final_summary_cannot_create_booking(self) -> None:
        from app.services.booking_flow import BookingFlow
        history = self._full_call(self._first_open_slot())
        flow = BookingFlow.from_history(history)
        flow.step = "summary"
        unconfirmed = [flow.state_message(), *[item for item in history if item["role"] != "system"]]
        result = self._finish(unconfirmed)
        self.assertFalse(result["saved"])
        self.assertFalse(result["confirmed"])
        self.assertEqual(len(self.client.app.state.container.patient_repository.list()), 0)

    def test_other_scenarios_are_not_saved(self) -> None:
        response = self.client.post("/api/desk/demo-calls/finish", json={"scenario_id": "in-cancel", "history": []})
        self.assertEqual(response.json(), {"supported": False, "saved": False})


if __name__ == "__main__":
    unittest.main()
