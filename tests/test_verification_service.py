from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.services.otp_provider import OTPProvider
from app.services.verification_service import PatientVerificationService, VerificationError
from medflow.domain.enums import VerificationStatus, WorkflowState
from medflow.domain.models import utc_now
from security_guardrails import get_audit_events, reset_audit_events
from tests.support import build_container


class SequenceOTPProvider(OTPProvider):
    def __init__(self, *codes: str) -> None:
        self.codes = list(codes)

    def generate_code(self) -> str:
        return self.codes.pop(0)

    def deliver(self, *, normalized_phone: str, code: str, challenge_id: str) -> None:
        return None


class VerificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_audit_events()
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        (
            self.settings,
            self.container,
            self.user,
            self.patient,
            self.actor,
            self.receptionist,
        ) = build_container(root, otp_resend_cooldown_seconds=0)
        self.workflow = self.container.workflow_orchestrator.create_session(
            patient_id=self.patient.patient_id,
            actor=self.actor,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _service(self, *codes: str) -> PatientVerificationService:
        return PatientVerificationService(
            settings=self.settings,
            provider=SequenceOTPProvider(*codes),
            patients=self.container.patient_repository,
            verifications=self.container.verification_repository,
            workflows=self.container.workflow_repository,
            orchestrator=self.container.workflow_orchestrator,
            audit=self.container.audit_service,
        )

    def test_correct_otp_verifies_once_and_advances_workflow(self) -> None:
        service = self._service("123456")
        challenge = service.request_challenge(
            patient_id=self.patient.patient_id,
            workflow_id=self.workflow.workflow_id,
            actor=self.actor,
        )
        verified = service.verify(challenge_id=challenge.challenge_id, code="123456", actor=self.actor)
        self.assertEqual(verified.status, VerificationStatus.VERIFIED)
        self.assertIsNotNone(verified.used_at)
        self.assertEqual(
            self.container.workflow_repository.get(self.workflow.workflow_id).state,
            WorkflowState.PATIENT_VERIFIED,
        )
        with self.assertRaisesRegex(VerificationError, "already been used"):
            service.verify(challenge_id=challenge.challenge_id, code="123456", actor=self.actor)

    def test_incorrect_otp_counts_attempts_and_locks_after_five(self) -> None:
        service = self._service("123456")
        challenge = service.request_challenge(
            patient_id=self.patient.patient_id,
            workflow_id=self.workflow.workflow_id,
            actor=self.actor,
        )
        for attempt in range(5):
            with self.assertRaises(VerificationError):
                service.verify(challenge_id=challenge.challenge_id, code="000000", actor=self.actor)
            record = self.container.verification_repository.get(challenge.challenge_id)
            self.assertEqual(record.failed_attempts, attempt + 1)
        self.assertEqual(record.status, VerificationStatus.LOCKED)
        self.assertGreater(record.locked_until, utc_now())

    def test_expired_otp_is_rejected(self) -> None:
        service = self._service("123456")
        challenge = service.request_challenge(
            patient_id=self.patient.patient_id,
            workflow_id=self.workflow.workflow_id,
            actor=self.actor,
        )
        record = self.container.verification_repository.get(challenge.challenge_id)
        self.container.verification_repository.save(
            record.model_copy(update={"expires_at": utc_now() - timedelta(seconds=1)})
        )
        with self.assertRaisesRegex(VerificationError, "expired"):
            service.verify(challenge_id=challenge.challenge_id, code="123456", actor=self.actor)

    def test_resend_invalidates_old_otp(self) -> None:
        service = self._service("111111", "222222")
        challenge = service.request_challenge(
            patient_id=self.patient.patient_id,
            workflow_id=self.workflow.workflow_id,
            actor=self.actor,
        )
        service.resend(challenge_id=challenge.challenge_id, actor=self.actor)
        with self.assertRaises(VerificationError):
            service.verify(challenge_id=challenge.challenge_id, code="111111", actor=self.actor)
        verified = service.verify(challenge_id=challenge.challenge_id, code="222222", actor=self.actor)
        self.assertEqual(verified.status, VerificationStatus.VERIFIED)

    def test_raw_otp_is_absent_from_database_and_audit(self) -> None:
        service = self._service("654321")
        service.request_challenge(
            patient_id=self.patient.patient_id,
            workflow_id=self.workflow.workflow_id,
            actor=self.actor,
        )
        connection = sqlite3.connect(self.settings.database_path)
        try:
            serialized_rows = " ".join(
                str(row) for row in connection.execute("SELECT * FROM verification_challenges").fetchall()
            )
        finally:
            connection.close()
        self.assertNotIn("654321", serialized_rows)
        self.assertNotIn("654321", str(get_audit_events()))


if __name__ == "__main__":
    unittest.main()
