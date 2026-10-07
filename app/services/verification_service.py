from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import timedelta

from app.config import Settings
from app.services.audit_service import AuditService
from app.services.otp_provider import OTPProvider
from medflow.domain.enums import VerificationStatus, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import Patient, VerificationRecord, utc_now
from medflow.orchestration import ClinicWorkflowOrchestrator, WorkflowAction
from medflow.repositories.protocols import PatientRepository, VerificationRepository, WorkflowRepository
from security_guardrails import Actor
from security_guardrails.authz import is_patient_authorized


class VerificationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class VerificationChallengeResult:
    challenge_id: str
    patient_id: str
    workflow_id: str
    phone_last_four: str
    expires_at: str
    status: str
    resend_available_at: str
    development_otp: str | None = None


class PatientVerificationService:
    def __init__(
        self,
        *,
        settings: Settings,
        provider: OTPProvider,
        patients: PatientRepository,
        verifications: VerificationRepository,
        workflows: WorkflowRepository,
        orchestrator: ClinicWorkflowOrchestrator,
        audit: AuditService,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.patients = patients
        self.verifications = verifications
        self.workflows = workflows
        self.orchestrator = orchestrator
        self.audit = audit

    def request_challenge(self, *, patient_id: str, workflow_id: str, actor: Actor) -> VerificationChallengeResult:
        patient, workflow = self._authorized_context(patient_id, workflow_id, actor)
        now = utc_now()
        latest = self._latest_for_workflow(workflow_id)
        if latest and latest.locked_until and latest.locked_until > now:
            raise VerificationError("VERIFICATION_LOCKED", "Verification is temporarily locked")
        if latest and latest.status in {VerificationStatus.PENDING, VerificationStatus.FAILED}:
            available_at = latest.last_sent_at + timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
            if available_at > now:
                raise VerificationError("RESEND_COOLDOWN", "A new code cannot be requested yet")
            latest = latest.model_copy(update={"status": VerificationStatus.EXPIRED})
            self.verifications.save(latest)

        normalized_phone = self._normalize_phone(patient)
        code = self.provider.generate_code()
        challenge_id = new_id("OTP")
        record = VerificationRecord(
            challenge_id=challenge_id,
            patient_id=patient.patient_id,
            workflow_id=workflow.workflow_id,
            method="PHONE_OTP",
            status=VerificationStatus.PENDING,
            normalized_phone_reference=self._phone_reference(normalized_phone),
            phone_last_four=normalized_phone[-4:],
            otp_digest=self._otp_digest(challenge_id, code),
            created_at=now,
            last_sent_at=now,
            expires_at=now + timedelta(seconds=self.settings.otp_expiry_seconds),
        )
        self.verifications.save(record)
        self.provider.deliver(normalized_phone=normalized_phone, code=code, challenge_id=challenge_id)
        self.audit.record(
            "patient_verification_requested",
            actor_ref=actor.ref,
            action="request_phone_otp",
            patient_ref=patient.patient_id,
            resource_ref=workflow.workflow_id,
            metadata={"challenge_id": challenge_id, "method": "PHONE_OTP"},
        )
        return self._result(record, code)

    def resend(self, *, challenge_id: str, actor: Actor) -> VerificationChallengeResult:
        record = self._get(challenge_id)
        patient, _ = self._authorized_context(record.patient_id, record.workflow_id, actor)
        now = utc_now()
        if record.used_at or record.status == VerificationStatus.VERIFIED:
            raise VerificationError("OTP_ALREADY_USED", "The verification code has already been used")
        if record.locked_until and record.locked_until > now:
            raise VerificationError("VERIFICATION_LOCKED", "Verification is temporarily locked")
        available_at = record.last_sent_at + timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
        if available_at > now:
            raise VerificationError("RESEND_COOLDOWN", "A new code cannot be requested yet")
        if record.resend_count >= self.settings.otp_max_resends:
            raise VerificationError("RESEND_LIMIT", "The resend limit has been reached")

        normalized_phone = self._normalize_phone(patient)
        code = self.provider.generate_code()
        updated = record.model_copy(
            update={
                "otp_digest": self._otp_digest(record.challenge_id, code),
                "status": VerificationStatus.PENDING,
                "failed_attempts": 0,
                "resend_count": record.resend_count + 1,
                "last_sent_at": now,
                "expires_at": now + timedelta(seconds=self.settings.otp_expiry_seconds),
                "locked_until": None,
            }
        )
        self.verifications.save(updated)
        self.provider.deliver(normalized_phone=normalized_phone, code=code, challenge_id=record.challenge_id)
        self.audit.record(
            "patient_verification_resent",
            actor_ref=actor.ref,
            action="resend_phone_otp",
            patient_ref=record.patient_id,
            resource_ref=record.workflow_id,
            metadata={"challenge_id": record.challenge_id, "resend_count": updated.resend_count},
        )
        return self._result(updated, code)

    def verify(self, *, challenge_id: str, code: str, actor: Actor) -> VerificationRecord:
        record = self._get(challenge_id)
        self._authorized_context(record.patient_id, record.workflow_id, actor)
        now = utc_now()
        if record.used_at or record.status == VerificationStatus.VERIFIED:
            raise VerificationError("OTP_ALREADY_USED", "The verification code has already been used")
        if record.locked_until and record.locked_until > now:
            raise VerificationError("VERIFICATION_LOCKED", "Verification is temporarily locked")
        if record.expires_at <= now:
            expired = record.model_copy(update={"status": VerificationStatus.EXPIRED})
            self.verifications.save(expired)
            raise VerificationError("OTP_EXPIRED", "The verification code has expired")
        supplied = str(code or "").strip()
        expected = self._otp_digest(record.challenge_id, supplied)
        if len(supplied) != 6 or not supplied.isdecimal() or not hmac.compare_digest(record.otp_digest, expected):
            attempts = record.failed_attempts + 1
            locked_until = None
            status = VerificationStatus.FAILED
            if attempts >= self.settings.otp_max_attempts:
                locked_until = now + timedelta(seconds=self.settings.otp_lock_seconds)
                status = VerificationStatus.LOCKED
            failed = record.model_copy(
                update={
                    "failed_attempts": attempts,
                    "locked_until": locked_until,
                    "status": status,
                }
            )
            self.verifications.save(failed)
            self.audit.record(
                "patient_verification_attempt",
                actor_ref=actor.ref,
                action="verify_phone_otp",
                patient_ref=record.patient_id,
                resource_ref=record.workflow_id,
                result="deny",
                metadata={"challenge_id": record.challenge_id, "failed_attempts": attempts},
            )
            code_name = "VERIFICATION_LOCKED" if locked_until else "OTP_INVALID"
            raise VerificationError(code_name, "The verification code is invalid")

        verified = record.model_copy(
            update={
                "status": VerificationStatus.VERIFIED,
                "verified_at": now,
                "used_at": now,
                "otp_digest": self._otp_digest(record.challenge_id, "USED"),
            }
        )
        self.verifications.save(verified)
        workflow = self.workflows.get(record.workflow_id)
        if workflow and workflow.state == WorkflowState.PATIENT_UNVERIFIED:
            self.orchestrator.perform_action(
                record.workflow_id,
                WorkflowAction.VERIFY_PATIENT,
                actor=actor,
                expected_version=workflow.version,
            )
        self.audit.record(
            "patient_verified",
            actor_ref=actor.ref,
            action="verify_phone_otp",
            patient_ref=record.patient_id,
            resource_ref=record.workflow_id,
            metadata={"challenge_id": record.challenge_id, "method": record.method},
        )
        return verified

    def _authorized_context(self, patient_id: str, workflow_id: str, actor: Actor):
        if actor.role not in {"receptionist", "doctor"} or not is_patient_authorized(actor, patient_id):
            raise VerificationError("FORBIDDEN", "Actor is not authorized for patient verification")
        patient = self.patients.get(patient_id)
        workflow = self.workflows.get(workflow_id)
        if patient is None:
            raise VerificationError("PATIENT_NOT_FOUND", "Patient was not found")
        if workflow is None or workflow.patient_id != patient.patient_id:
            raise VerificationError("WORKFLOW_MISMATCH", "Verification challenge does not match the workflow patient")
        return patient, workflow

    def _latest_for_workflow(self, workflow_id: str) -> VerificationRecord | None:
        method = getattr(self.verifications, "latest_for_workflow", None)
        return method(workflow_id) if callable(method) else None

    def _get(self, challenge_id: str) -> VerificationRecord:
        record = self.verifications.get(challenge_id)
        if record is None:
            raise VerificationError("CHALLENGE_NOT_FOUND", "Verification challenge was not found")
        return record

    def _otp_digest(self, challenge_id: str, code: str) -> str:
        message = f"{challenge_id}:{code}".encode("utf-8")
        return hmac.new(self.settings.otp_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def _phone_reference(self, normalized_phone: str) -> str:
        return hmac.new(
            self.settings.otp_secret.encode("utf-8"),
            f"phone:{normalized_phone}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _normalize_phone(patient: Patient) -> str:
        digits = re.sub(r"\D", "", patient.phone_number)
        if digits.startswith("0") and len(digits) == 11:
            digits = "92" + digits[1:]
        if len(digits) < 10:
            raise VerificationError("PHONE_UNAVAILABLE", "Patient phone number is unavailable")
        return digits

    def _result(self, record: VerificationRecord, code: str) -> VerificationChallengeResult:
        development_otp = code if self.settings.may_expose_dev_otp else None
        return VerificationChallengeResult(
            challenge_id=record.challenge_id,
            patient_id=record.patient_id,
            workflow_id=record.workflow_id,
            phone_last_four=record.phone_last_four,
            expires_at=record.expires_at.isoformat(),
            status=record.status.value,
            resend_available_at=(
                record.last_sent_at + timedelta(seconds=self.settings.otp_resend_cooldown_seconds)
            ).isoformat(),
            development_otp=development_otp,
        )
