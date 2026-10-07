from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    AppointmentStatus,
    ClaimSupportStatus,
    CodeSuggestionStatus,
    ConsentType,
    EncounterStatus,
    NoteStatus,
    Speaker,
    SummaryLanguage,
    UserRole,
    VerificationStatus,
    WorkflowState,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, str_strip_whitespace=True)


class Patient(DomainModel):
    patient_id: str
    legacy_ref: str | None = None
    name: str = ""
    phone_number: str = ""
    email: str = ""
    date_of_birth: str | None = None
    age_text: str = ""
    medical_record_number: str = ""
    first_visit: str = ""
    past_medical_history: str = ""
    current_complaint: str = ""
    blood_pressure: str = ""
    recorded_at: str = ""
    active: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class PractitionerUser(DomainModel):
    practitioner_id: str
    role: UserRole
    full_name: str
    email: str = ""
    active: bool = True
    assigned_patient_ids: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=utc_now)


class Appointment(DomainModel):
    appointment_id: str
    patient_id: str
    practitioner_id: str
    department_id: str
    location_id: str
    visit_type_id: str
    start_at: datetime
    end_at: datetime
    status: AppointmentStatus = AppointmentStatus.REQUESTED
    idempotency_key: str
    cancellation_reason: str = ""
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_time_range(self) -> "Appointment":
        if self.end_at <= self.start_at:
            raise ValueError("Appointment end_at must be after start_at")
        return self


class Encounter(DomainModel):
    encounter_id: str
    patient_id: str
    practitioner_id: str
    appointment_id: str
    workflow_id: str
    status: EncounterStatus = EncounterStatus.PLANNED
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class WorkflowSession(DomainModel):
    workflow_id: str
    patient_id: str
    appointment_id: str | None = None
    encounter_id: str | None = None
    note_id: str | None = None
    assigned_practitioner_id: str | None = None
    state: WorkflowState = WorkflowState.PATIENT_UNVERIFIED
    resume_state: WorkflowState | None = None
    version: int = Field(default=1, ge=1)
    last_error_code: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class VerificationRecord(DomainModel):
    challenge_id: str
    patient_id: str
    workflow_id: str
    method: str
    status: VerificationStatus = VerificationStatus.PENDING
    normalized_phone_reference: str
    phone_last_four: str
    otp_digest: str
    created_at: datetime = Field(default_factory=utc_now)
    last_sent_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime
    failed_attempts: int = Field(default=0, ge=0)
    resend_count: int = Field(default=0, ge=0)
    locked_until: datetime | None = None
    verified_at: datetime | None = None
    used_at: datetime | None = None


class ConsentRecord(DomainModel):
    consent_id: str
    patient_id: str
    encounter_id: str
    consent_type: ConsentType
    decision: bool
    consent_text_version: str
    captured_by: str
    capture_method: str
    captured_at: datetime = Field(default_factory=utc_now)
    revoked_at: datetime | None = None
    expires_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        now = utc_now()
        return self.decision and self.revoked_at is None and (self.expires_at is None or self.expires_at > now)


class TranscriptUtterance(DomainModel):
    transcript_id: str
    utterance_id: str
    segment_id: str | None = None
    speaker: Speaker = Speaker.UNKNOWN
    # Relationship of an ATTENDANT to the patient, e.g. "Mother".
    speaker_relation: str | None = Field(default=None, max_length=40)
    # Who the utterance is directed at, e.g. a Doctor instruction to the NURSE.
    addressed_to: Speaker | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    original_text: str
    clinical_english: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    needs_review: bool = False

    @model_validator(mode="after")
    def validate_timestamps(self) -> "TranscriptUtterance":
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms cannot be earlier than start_ms")
        if self.speaker == Speaker.UNKNOWN:
            object.__setattr__(self, "needs_review", True)
        return self


class TranscriptRecord(DomainModel):
    transcript_id: str
    patient_id: str
    encounter_id: str
    utterances: list[TranscriptUtterance] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class EvidenceReference(DomainModel):
    evidence_id: str
    source_type: str
    source_id: str
    excerpt: str = ""


class ClinicalClaim(DomainModel):
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimSupportStatus = ClaimSupportStatus.REVIEW_REQUIRED


class StructuredSOAP(DomainModel):
    subjective: list[ClinicalClaim] = Field(default_factory=list)
    objective: list[ClinicalClaim] = Field(default_factory=list)
    assessment: list[ClinicalClaim] = Field(default_factory=list)
    plan: list[ClinicalClaim] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    unsupported_claims: list[ClinicalClaim] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SOAPNoteVersion(DomainModel):
    note_version_id: str
    note_id: str
    version_number: int = Field(ge=1)
    status: NoteStatus
    soap: StructuredSOAP
    evidence: list[EvidenceReference] = Field(default_factory=list)
    transcript_id: str | None = None
    template_id: str | None = None
    created_by_actor_id: str
    created_at: datetime = Field(default_factory=utc_now)
    change_reason: str = ""


class SOAPNote(DomainModel):
    note_id: str
    patient_id: str
    encounter_id: str
    current_version_id: str
    state: NoteStatus = NoteStatus.REVIEW_REQUIRED
    approved_by_doctor_id: str | None = None
    approved_at: datetime | None = None
    rejected_by_doctor_id: str | None = None
    rejected_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SummaryItem(DomainModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class SummarySection(DomainModel):
    title: str
    items: list[SummaryItem] = Field(default_factory=list)


class PreVisitSummary(DomainModel):
    summary_id: str
    patient_id: str
    encounter_id: str
    sections: list[SummarySection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_note_version_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ClinicalTemplate(DomainModel):
    template_id: str
    name: str
    sections: list[str]
    active: bool = True
    custom: bool = False
    created_by_actor_id: str = "system"
    created_at: datetime = Field(default_factory=utc_now)


class AfterVisitSummary(DomainModel):
    after_visit_summary_id: str
    patient_id: str
    encounter_id: str
    note_version_id: str
    language: SummaryLanguage
    sections: list[SummarySection] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class CodeSuggestion(DomainModel):
    code_suggestion_id: str
    patient_id: str
    note_id: str
    note_version_id: str
    system: str = "ICD-10"
    code: str
    description: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)
    status: CodeSuggestionStatus = CodeSuggestionStatus.SUGGESTED
    reviewed_by_actor_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)


class AuditEvent(DomainModel):
    audit_event_id: str
    event_type: str
    actor_ref: str
    action: str
    patient_ref: str = ""
    resource_ref: str = ""
    result: str
    request_id: str
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
