from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services import AppointmentError, AppointmentRequest
from medflow.domain.enums import AppointmentStatus
from security_guardrails import Actor
from tests.support import build_container


PK_TZ = ZoneInfo("Asia/Karachi")


class AppointmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        (
            self.settings,
            self.container,
            self.user,
            self.patient,
            self.actor,
            self.receptionist,
        ) = build_container(Path(self.temporary.name))
        self.now = datetime(2030, 1, 7, 7, 0, tzinfo=PK_TZ)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _request(self, *, key: str, start: datetime, practitioner_id: str | None = None):
        practitioner = practitioner_id or self.user.practitioner_id
        department = "DEP-GM" if practitioner != "DOC-DEV-003" else "DEP-CAR"
        return AppointmentRequest(
            patient_id=self.patient.patient_id,
            practitioner_id=practitioner,
            department_id=department,
            location_id="LOC-ISB-001",
            visit_type_id="VISIT-NEW",
            start_at=start,
            idempotency_key=key,
        )

    def test_create_is_idempotent_and_duplicate_slot_is_prevented(self) -> None:
        request = self._request(key="create-001", start=datetime(2030, 1, 7, 10, 0))
        first = self.container.appointment_service.create(request, actor=self.actor, now=self.now)
        second = self.container.appointment_service.create(request, actor=self.actor, now=self.now)
        self.assertEqual(first.appointment_id, second.appointment_id)
        self.assertEqual(
            self.container.appointment_service.get(first.appointment_id, actor=self.actor).appointment_id,
            first.appointment_id,
        )
        with self.assertRaises(AppointmentError):
            self.container.appointment_service.create(
                self._request(key="create-002", start=datetime(2030, 1, 7, 10, 0)),
                actor=self.actor,
                now=self.now,
            )

    def test_patient_overlap_is_prevented_across_doctors(self) -> None:
        self.container.appointment_service.create(
            self._request(key="doctor-one", start=datetime(2030, 1, 7, 10, 0)),
            actor=self.actor,
            now=self.now,
        )
        with self.assertRaisesRegex(AppointmentError, "overlapping"):
            self.container.appointment_service.create(
                self._request(
                    key="doctor-two",
                    start=datetime(2030, 1, 7, 10, 0),
                    practitioner_id="DOC-DEV-003",
                ),
                actor=self.actor,
                now=self.now,
            )

    def test_reschedule_and_cancel_lifecycle(self) -> None:
        appointment = self.container.appointment_service.create(
            self._request(key="lifecycle-create", start=datetime(2030, 1, 7, 10, 0)),
            actor=self.actor,
            now=self.now,
        )
        moved = self.container.appointment_service.reschedule(
            appointment.appointment_id,
            new_start_at=datetime(2030, 1, 7, 11, 0),
            idempotency_key="lifecycle-reschedule",
            actor=self.actor,
            now=self.now,
        )
        self.assertEqual(moved.start_at.hour, 11)
        cancelled = self.container.appointment_service.cancel(
            appointment.appointment_id,
            reason_code="PATIENT_REQUEST",
            idempotency_key="lifecycle-cancel",
            actor=self.actor,
        )
        self.assertEqual(cancelled.status, AppointmentStatus.CANCELLED)
        with self.assertRaises(AppointmentError):
            self.container.appointment_service.start(cancelled.appointment_id, actor=self.actor)

    def test_friday_break_and_minimum_advance_are_enforced(self) -> None:
        friday_now = datetime(2030, 1, 11, 8, 0, tzinfo=PK_TZ)
        with self.assertRaisesRegex(AppointmentError, "working hours"):
            self.container.appointment_service.create(
                self._request(key="friday-break", start=datetime(2030, 1, 11, 13, 0)),
                actor=self.actor,
                now=friday_now,
            )
        with self.assertRaisesRegex(AppointmentError, "minimum advance"):
            self.container.appointment_service.create(
                self._request(key="too-soon", start=datetime(2030, 1, 11, 9, 0)),
                actor=self.actor,
                now=friday_now,
            )

    def test_availability_returns_only_valid_slots(self) -> None:
        slots = self.container.appointment_service.availability(
            patient_id=self.patient.patient_id,
            practitioner_id=self.user.practitioner_id,
            visit_type_id="VISIT-NEW",
            start_date=datetime(2030, 1, 7).date(),
            days=1,
            now=self.now,
        )
        self.assertTrue(slots)
        self.assertEqual(slots[0]["start_at"], "2030-01-07T09:00:00+05:00")


if __name__ == "__main__":
    unittest.main()
