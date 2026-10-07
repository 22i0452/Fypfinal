from __future__ import annotations

import re
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class NoteState(str, Enum):
    AI_DRAFT = "AI_DRAFT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVED_BY_DOCTOR = "APPROVED_BY_DOCTOR"
    REJECTED = "REJECTED"


class SOAPValidationError(ValueError):
    def __init__(self, issues: list[str]) -> None:
        self.issues = issues
        super().__init__("; ".join(issues))


class EvidenceReference(BaseModel):
    utterance_id: str
    quote: str = ""

    model_config = ConfigDict(extra="forbid")


class ClaimAttribution(BaseModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")


class SOAPDraftSchema(BaseModel):
    subjective: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    plan: str = Field(min_length=1)
    visit_date: str = Field(min_length=4)
    generated_by: str = "AI Medical Scribe"
    evidence: list[EvidenceReference] = Field(default_factory=list)
    claim_sources: dict[str, list[ClaimAttribution]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


AI_DIFFERENTIAL_LABEL = "AI-suggested differential (requires doctor confirmation):"
AI_MANAGEMENT_LABEL = (
    "AI-suggested management considerations (requires doctor confirmation):"
)
_AI_DIFFERENTIAL_LABEL_LOWER = AI_DIFFERENTIAL_LABEL.lower()
_AI_MANAGEMENT_LABEL_LOWER = AI_MANAGEMENT_LABEL.lower()

_DANGEROUS_FIELDS = {
    "approved",
    "approved_by_doctor",
    "doctor_approved",
    "final",
    "finalized",
    "prescription_authorized",
    "export_authorized",
}
_OBJECTIVE_CLAIM_RE = re.compile(
    r"\b(?:normal vitals|vital signs?|blood pressure|temperature|heart rate|pulse|"
    r"respiratory rate|oxygen saturation|physical examination|exam(?:ination)?|"
    r"laboratory|lab result|x-ray|ultrasound|ct scan|mri|ecg|ekg)\b",
    re.I,
)
_MEDICATION_RE = re.compile(
    r"\b(?:mg|mcg|tablet|capsule|injection|dose|dosage|twice daily|once daily|tds|bd|od|"
    r"paracetamol|ibuprofen|amoxicillin|azithromycin|metformin|insulin|antibiotic)\b",
    re.I,
)
_MEDICATION_NAME_RE = re.compile(
    r"\b(?:paracetamol|ibuprofen|amoxicillin|azithromycin|metformin|insulin|antibiotic)\b",
    re.I,
)
_DOSAGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?)\b", re.I)
_FREQUENCY_RE = re.compile(
    r"\b(?:twice daily|once daily|three times daily|every \d+ hours?|tds|bd|od)\b",
    re.I,
)
_DOSAGE_FORM_RE = re.compile(r"\b(?:tablet|capsule|injection)\b", re.I)
_DIAGNOSIS_TERM_RE = re.compile(
    r"\b(?:[a-z]{4,}(?:itis|emia|opathy)|viral syndrome|food poisoning|infection|"
    r"pneumonia|diabetes|hypertension|migraine|asthma|cancer|fracture)\b",
    re.I,
)

_SUPPORT_STOPWORDS = {
    "acute",
    "assessment",
    "based",
    "clinician",
    "confirmation",
    "consider",
    "considerations",
    "differential",
    "doctor",
    "documented",
    "encounter",
    "management",
    "patient",
    "reported",
    "requires",
    "review",
    "suggested",
    "symptom",
    "symptoms",
}


def _transcript_text(transcript: list[dict[str, Any]] | str | None) -> str:
    if isinstance(transcript, str):
        return transcript.lower()
    if not transcript:
        return ""
    return " ".join(str(entry.get("text", "")) for entry in transcript if isinstance(entry, dict)).lower()


def has_ai_differential_label(value: str) -> bool:
    return _AI_DIFFERENTIAL_LABEL_LOWER in str(value or "").lower()


def has_ai_management_label(value: str) -> bool:
    return _AI_MANAGEMENT_LABEL_LOWER in str(value or "").lower()


def _token_key(word: str) -> str:
    if len(word) > 5 and word.endswith("ies"):
        return f"{word[:-3]}y"
    if (
        len(word) > 5
        and word.endswith("s")
        and not word.endswith(("ss", "itis", "osis"))
    ):
        return word[:-1]
    return word


def _supported_words(claim_text: str, transcript_text: str) -> set[str]:
    words = {
        _token_key(word)
        for word in re.findall(r"[a-zA-Z]{4,}", claim_text.lower())
        if word not in _SUPPORT_STOPWORDS
        and word not in {"available", "information", "provided", "stated", "that", "this", "with"}
    }
    transcript_words = {
        _token_key(word)
        for word in re.findall(r"[a-zA-Z]{4,}", transcript_text.lower())
    }
    return words & transcript_words


def _has_support(claim_text: str, transcript_text: str) -> bool:
    if not claim_text.strip():
        return True
    meaningful_words = _supported_words(claim_text, claim_text)
    if not meaningful_words:
        return True
    return bool(_supported_words(claim_text, transcript_text))


def _suggestion_is_grounded(value: str, transcript_text: str) -> bool:
    return bool(_supported_words(value, transcript_text))


def _normalized_phrase(value: str) -> str:
    return " ".join(value.lower().split())


def _medication_details_are_supported(plan: str, transcript_text: str) -> bool:
    details: list[str] = []
    for pattern in (
        _MEDICATION_NAME_RE,
        _DOSAGE_RE,
        _FREQUENCY_RE,
        _DOSAGE_FORM_RE,
    ):
        details.extend(match.group(0) for match in pattern.finditer(plan))
    if not details:
        return _has_support(plan, transcript_text)
    normalized_transcript = _normalized_phrase(transcript_text)
    return all(
        _normalized_phrase(detail) in normalized_transcript
        for detail in details
    )


def _doctor_source_text(transcript: list[dict[str, Any]] | str | None) -> str:
    if isinstance(transcript, str):
        return transcript.lower()
    if not transcript:
        return ""
    return " ".join(
        str(entry.get("text", ""))
        for entry in transcript
        if isinstance(entry, dict)
        and "doctor" in str(entry.get("speaker", "")).lower()
    ).lower()


def _diagnosis_terms_are_supported(
    assessment: str,
    transcript: list[dict[str, Any]] | str | None,
) -> bool:
    terms = [match.group(0).lower() for match in _DIAGNOSIS_TERM_RE.finditer(assessment)]
    if not terms:
        return True
    doctor_text = _doctor_source_text(transcript)
    return bool(doctor_text) and all(term in doctor_text for term in terms)


def _is_explicitly_missing_objective(objective: str) -> bool:
    lowered = objective.strip().lower()
    if lowered in {"not documented", "not documented.", "not available", "n/a"}:
        return True
    missing_prefixes = (
        "no vital signs",
        "no objective findings",
        "no examination findings",
        "no physical examination",
    )
    missing_markers = ("documented", "recorded", "provided", "supplied", "available")
    return lowered.startswith(missing_prefixes) and any(marker in lowered for marker in missing_markers)


def _is_explicitly_missing_section(value: str, section: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"not documented", "not documented.", "not available", "n/a"}:
        return True
    if len(lowered.split()) > 24:
        return False
    section_terms = {
        "assessment": ("assessment", "diagnosis", "impression"),
        "plan": ("plan", "treatment", "follow-up", "management"),
    }
    return "not documented" in lowered and any(
        term in lowered for term in section_terms.get(section, (section,))
    )


def validate_soap_output(soap: dict[str, Any], transcript: list[dict[str, Any]] | str | None = None) -> dict[str, Any]:
    issues: list[str] = []
    if not isinstance(soap, dict):
        raise SOAPValidationError(["soap_output_not_object"])

    for field in _DANGEROUS_FIELDS:
        if field in {str(key).lower() for key in soap}:
            issues.append(f"dangerous_field:{field}")

    try:
        parsed = SOAPDraftSchema.model_validate(soap)
    except ValidationError as exc:
        issues.append("schema_validation_failed")
        issues.extend(error["type"] for error in exc.errors())
        raise SOAPValidationError(issues) from exc

    transcript_text = _transcript_text(transcript)
    unsupported: list[str] = []

    objective = parsed.objective.lower()
    if transcript_text and _OBJECTIVE_CLAIM_RE.search(objective):
        if not _is_explicitly_missing_objective(objective) and not _has_support(
            parsed.objective,
            transcript_text,
        ):
            unsupported.append("objective")

    plan = parsed.plan.lower()
    plan_has_support = _has_support(parsed.plan, transcript_text)
    if transcript_text and _MEDICATION_RE.search(plan):
        if not _medication_details_are_supported(parsed.plan, transcript_text):
            unsupported.append("medication_or_dosage")

    if transcript_text and not _is_explicitly_missing_section(parsed.plan, "plan"):
        suggested_management = has_ai_management_label(parsed.plan)
        if not plan_has_support and not (
            suggested_management and _suggestion_is_grounded(parsed.plan, transcript_text)
        ):
            unsupported.append("plan")

    if transcript_text and not _is_explicitly_missing_section(parsed.assessment, "assessment"):
        assessment_has_support = _has_support(parsed.assessment, transcript_text)
        suggested_differential = has_ai_differential_label(parsed.assessment)
        if suggested_differential:
            if not _suggestion_is_grounded(parsed.assessment, transcript_text):
                unsupported.append("assessment")
        elif (
            not assessment_has_support
            or not _diagnosis_terms_are_supported(parsed.assessment, transcript)
        ):
            unsupported.append("assessment")

    if unsupported:
        issues.extend(
            f"unsupported_clinical_fact:{item}" for item in dict.fromkeys(unsupported)
        )

    if issues:
        raise SOAPValidationError(issues)

    return parsed.model_dump()


def create_draft_note_record(
    *,
    note_id: str,
    patient_id: str,
    patient_name: str,
    soap: dict[str, Any],
    transcript: list[dict[str, Any]],
    state: NoteState = NoteState.REVIEW_REQUIRED,
) -> dict[str, Any]:
    return {
        "note_id": note_id,
        "patient_id": patient_id,
        "patient_name": patient_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "state": state.value,
        "version": 1,
        "approval": None,
        "excerpt": str(soap.get("assessment") or soap.get("subjective") or "")[:220].strip(),
        "soap": soap,
        "transcript": transcript,
    }


def approve_note_record(note: dict[str, Any], *, doctor_id: str) -> dict[str, Any]:
    updated = dict(note)
    if updated.get("state") not in {NoteState.AI_DRAFT.value, NoteState.REVIEW_REQUIRED.value}:
        raise SOAPValidationError(["note_not_approvable"])
    updated["state"] = NoteState.APPROVED_BY_DOCTOR.value
    updated["version"] = int(updated.get("version") or 1) + 1
    updated["approval"] = {
        "doctor_id": doctor_id,
        "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": updated["version"],
    }
    return updated


def finalize_note_record(note: dict[str, Any]) -> dict[str, Any]:
    if note.get("state") != NoteState.APPROVED_BY_DOCTOR.value:
        raise SOAPValidationError(["unapproved_note_finalization_blocked"])
    finalized = dict(note)
    finalized["finalized_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return finalized
