from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from medflow.domain.enums import ClaimSupportStatus, ConsentType, NoteStatus, SummaryLanguage
from medflow.domain.ids import legacy_patient_id
from medflow.domain.models import (
    AfterVisitSummary,
    Appointment,
    AuditEvent,
    ClinicalClaim,
    ClinicalTemplate,
    CodeSuggestion,
    ConsentRecord,
    Encounter,
    Patient,
    PreVisitSummary,
    SOAPNote,
    SOAPNoteVersion,
    StructuredSOAP,
    TranscriptRecord,
    VerificationRecord,
    WorkflowSession,
)


T = TypeVar("T", bound=BaseModel)
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,127}$")


class RepositoryConflictError(RuntimeError):
    pass


class JsonRepositoryError(RuntimeError):
    pass


def _safe_key(value: str) -> str:
    key = str(value or "").strip()
    if not _KEY_RE.fullmatch(key) or ".." in key:
        raise JsonRepositoryError("Unsafe repository identifier")
    return key


class _AtomicJsonStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def path_for(self, key: str) -> Path:
        return self.root / f"{_safe_key(key)}.json"

    def read_path(self, path: Path) -> dict | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def read(self, key: str) -> dict | None:
        return self.read_path(self.path_for(key))

    def list_documents(self) -> list[tuple[Path, dict]]:
        documents: list[tuple[Path, dict]] = []
        for path in sorted(self.root.glob("*.json")):
            value = self.read_path(path)
            if value is not None:
                documents.append((path, value))
        return documents

    def write(self, key: str, payload: dict) -> None:
        target = self.path_for(key)
        temporary = self.root / f".{target.name}.{uuid.uuid4().hex}.tmp"
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        with self._lock:
            try:
                temporary.write_text(encoded, encoding="utf-8")
                os.replace(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink(missing_ok=True)

    def delete(self, key: str) -> None:
        target = self.path_for(key)
        with self._lock:
            target.unlink(missing_ok=True)


class _JsonModelRepository(Generic[T]):
    def __init__(self, root: str | Path, model_type: type[T], id_field: str) -> None:
        self.store = _AtomicJsonStore(root)
        self.model_type = model_type
        self.id_field = id_field

    def get_model(self, identifier: str) -> T | None:
        payload = self.store.read(identifier)
        if payload is None:
            return None
        try:
            return self.model_type.model_validate(payload)
        except ValidationError:
            return None

    def list_models(self) -> list[T]:
        values: list[T] = []
        for _, payload in self.store.list_documents():
            try:
                values.append(self.model_type.model_validate(payload))
            except ValidationError:
                continue
        return values

    def save_model(self, model: T) -> T:
        identifier = str(getattr(model, self.id_field))
        self.store.write(identifier, model.model_dump(mode="json"))
        return model.model_copy(deep=True)

    def delete_model(self, identifier: str) -> None:
        self.store.delete(identifier)


class JsonPatientRepository:
    """Reads legacy intake files and writes new patients under opaque patient IDs."""

    def __init__(self, root: str | Path) -> None:
        self.store = _AtomicJsonStore(root)

    @staticmethod
    def _from_document(path: Path, payload: dict) -> Patient | None:
        if "patient_id" in payload:
            try:
                return Patient.model_validate(payload)
            except ValidationError:
                return None

        name = str(payload.get("name") or payload.get("patient_name") or "").strip()
        if not name:
            return None
        return Patient(
            patient_id=legacy_patient_id(path.name),
            legacy_ref=path.name,
            name=name,
            phone_number=str(payload.get("phone_number") or payload.get("phone") or ""),
            email=str(payload.get("email") or ""),
            date_of_birth=payload.get("date_of_birth") or None,
            age_text=str(payload.get("age") or ""),
            medical_record_number=str(payload.get("medical_record_number") or payload.get("mrn") or ""),
            first_visit=str(payload.get("first_visit") or ""),
            past_medical_history=str(payload.get("past_medical_history") or ""),
            current_complaint=str(payload.get("current_complaint") or ""),
            blood_pressure=str(payload.get("blood_pressure") or ""),
            recorded_at=str(payload.get("recorded_at") or ""),
        )

    def get(self, patient_id_or_legacy_ref: str) -> Patient | None:
        query = str(patient_id_or_legacy_ref or "").strip()
        if not query:
            return None
        direct = self.store.root / query
        if direct.suffix == ".json" and direct.parent.resolve() == self.store.root.resolve() and direct.exists():
            payload = self.store.read_path(direct)
            return self._from_document(direct, payload or {})
        payload = self.store.read(query)
        if payload is not None:
            return self._from_document(self.store.path_for(query), payload)
        for path, value in self.store.list_documents():
            patient = self._from_document(path, value)
            if patient and query in {patient.patient_id, patient.legacy_ref}:
                return patient
        return None

    def list(self) -> list[Patient]:
        patients: list[Patient] = []
        for path, payload in self.store.list_documents():
            patient = self._from_document(path, payload)
            if patient is not None:
                patients.append(patient)
        return patients

    def save(self, patient: Patient) -> Patient:
        _safe_key(patient.patient_id)
        self.store.write(patient.patient_id, patient.model_dump(mode="json"))
        return patient.model_copy(deep=True)


class JsonAppointmentRepository(_JsonModelRepository[Appointment]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, Appointment, "appointment_id")

    def get(self, appointment_id: str) -> Appointment | None:
        return self.get_model(appointment_id)

    def list(self, *, patient_id: str | None = None, practitioner_id: str | None = None) -> list[Appointment]:
        return [
            item
            for item in self.list_models()
            if (patient_id is None or item.patient_id == patient_id)
            and (practitioner_id is None or item.practitioner_id == practitioner_id)
        ]

    def get_by_idempotency_key(self, idempotency_key: str) -> Appointment | None:
        return next((item for item in self.list_models() if item.idempotency_key == idempotency_key), None)

    def save(self, appointment: Appointment) -> Appointment:
        return self.save_model(appointment)


class JsonEncounterRepository(_JsonModelRepository[Encounter]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, Encounter, "encounter_id")

    def get(self, encounter_id: str) -> Encounter | None:
        return self.get_model(encounter_id)

    def list(self, *, patient_id: str | None = None) -> list[Encounter]:
        return [item for item in self.list_models() if patient_id is None or item.patient_id == patient_id]

    def save(self, encounter: Encounter) -> Encounter:
        return self.save_model(encounter)


class JsonWorkflowRepository(_JsonModelRepository[WorkflowSession]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, WorkflowSession, "workflow_id")

    def get(self, workflow_id: str) -> WorkflowSession | None:
        return self.get_model(workflow_id)

    def list(self, *, patient_id: str | None = None) -> list[WorkflowSession]:
        return [item for item in self.list_models() if patient_id is None or item.patient_id == patient_id]

    def save(self, workflow: WorkflowSession, *, expected_version: int | None = None) -> WorkflowSession:
        current = self.get(workflow.workflow_id)
        if expected_version is not None:
            current_version = current.version if current else 0
            if current_version != expected_version:
                raise RepositoryConflictError("Workflow version conflict")
        return self.save_model(workflow)


class JsonVerificationRepository(_JsonModelRepository[VerificationRecord]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, VerificationRecord, "challenge_id")

    def get(self, challenge_id: str) -> VerificationRecord | None:
        return self.get_model(challenge_id)

    def latest_for_patient(self, patient_id: str) -> VerificationRecord | None:
        values = [item for item in self.list_models() if item.patient_id == patient_id]
        return max(values, key=lambda item: item.created_at, default=None)

    def save(self, verification: VerificationRecord) -> VerificationRecord:
        return self.save_model(verification)


class JsonConsentRepository(_JsonModelRepository[ConsentRecord]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, ConsentRecord, "consent_id")

    def get(self, consent_id: str) -> ConsentRecord | None:
        return self.get_model(consent_id)

    def list_for_encounter(self, encounter_id: str) -> list[ConsentRecord]:
        return [item for item in self.list_models() if item.encounter_id == encounter_id]

    def latest(self, encounter_id: str, consent_type: ConsentType) -> ConsentRecord | None:
        values = [
            item
            for item in self.list_for_encounter(encounter_id)
            if item.consent_type == consent_type
        ]
        return max(values, key=lambda item: item.captured_at, default=None)

    def save(self, consent: ConsentRecord) -> ConsentRecord:
        return self.save_model(consent)


def _legacy_claim(note_id: str, section: str, text: str, evidence_ids: list[str]) -> list[ClinicalClaim]:
    clean = str(text or "").strip()
    if not clean:
        return []
    return [
        ClinicalClaim(
            claim_id=f"{note_id}-{section.upper()}-001",
            text=clean,
            evidence_ids=evidence_ids,
            status=ClaimSupportStatus.REVIEW_REQUIRED,
        )
    ]


class JsonNoteRepository:
    def __init__(self, notes_root: str | Path, versions_root: str | Path | None = None) -> None:
        self.notes = _AtomicJsonStore(notes_root)
        self.versions = _AtomicJsonStore(versions_root or (Path(notes_root) / "_versions"))

    def _legacy_models(self, path: Path, payload: dict) -> tuple[SOAPNote, SOAPNoteVersion] | None:
        note_id = str(payload.get("note_id") or path.stem)
        patient_id = str(payload.get("patient_id") or "").strip()
        soap_payload = payload.get("soap")
        if not patient_id or not isinstance(soap_payload, dict):
            return None
        evidence_ids = [
            str(item.get("utterance_id"))
            for item in soap_payload.get("evidence", [])
            if isinstance(item, dict) and item.get("utterance_id")
        ]
        structured = StructuredSOAP(
            subjective=_legacy_claim(note_id, "subjective", soap_payload.get("subjective", ""), evidence_ids),
            objective=_legacy_claim(note_id, "objective", soap_payload.get("objective", ""), evidence_ids),
            assessment=_legacy_claim(note_id, "assessment", soap_payload.get("assessment", ""), evidence_ids),
            plan=_legacy_claim(note_id, "plan", soap_payload.get("plan", ""), evidence_ids),
            warnings=["Legacy note normalized for review; claim-level evidence was not available."],
        )
        version_number = max(1, int(payload.get("version") or 1))
        version_id = f"{note_id}-V{version_number}"
        raw_state = str(payload.get("state") or NoteStatus.REVIEW_REQUIRED.value)
        try:
            status = NoteStatus(raw_state)
        except ValueError:
            status = NoteStatus.REVIEW_REQUIRED
        version = SOAPNoteVersion(
            note_version_id=version_id,
            note_id=note_id,
            version_number=version_number,
            status=status,
            soap=structured,
            created_by_actor_id="legacy-import",
            change_reason="Read-only legacy normalization",
        )
        approval = payload.get("approval") if isinstance(payload.get("approval"), dict) else {}
        note = SOAPNote(
            note_id=note_id,
            patient_id=patient_id,
            encounter_id=str(payload.get("encounter_id") or f"LEGACY-{note_id}"),
            current_version_id=version_id,
            state=status,
            approved_by_doctor_id=approval.get("doctor_id"),
        )
        return note, version

    def _read_pair(self, path: Path, payload: dict) -> tuple[SOAPNote, SOAPNoteVersion | None] | None:
        if "current_version_id" in payload:
            try:
                return SOAPNote.model_validate(payload), None
            except ValidationError:
                return None
        return self._legacy_models(path, payload)

    def get(self, note_id: str) -> SOAPNote | None:
        for path, payload in self.notes.list_documents():
            pair = self._read_pair(path, payload)
            if pair and pair[0].note_id == note_id:
                return pair[0]
        return None

    def list(self, *, patient_id: str | None = None, encounter_id: str | None = None) -> list[SOAPNote]:
        values: list[SOAPNote] = []
        for path, payload in self.notes.list_documents():
            pair = self._read_pair(path, payload)
            if not pair:
                continue
            note = pair[0]
            if patient_id is not None and note.patient_id != patient_id:
                continue
            if encounter_id is not None and note.encounter_id != encounter_id:
                continue
            values.append(note)
        return values

    def save(self, note: SOAPNote) -> SOAPNote:
        self.notes.write(note.note_id, note.model_dump(mode="json"))
        return note.model_copy(deep=True)

    def get_version(self, note_version_id: str) -> SOAPNoteVersion | None:
        payload = self.versions.read(note_version_id)
        if payload is not None:
            try:
                return SOAPNoteVersion.model_validate(payload)
            except ValidationError:
                return None
        for path, note_payload in self.notes.list_documents():
            pair = self._read_pair(path, note_payload)
            if pair and pair[1] and pair[1].note_version_id == note_version_id:
                return pair[1]
        return None

    def list_versions(self, note_id: str) -> list[SOAPNoteVersion]:
        values: list[SOAPNoteVersion] = []
        for _, payload in self.versions.list_documents():
            try:
                version = SOAPNoteVersion.model_validate(payload)
            except ValidationError:
                continue
            if version.note_id == note_id:
                values.append(version)
        if not values:
            for path, note_payload in self.notes.list_documents():
                pair = self._read_pair(path, note_payload)
                if pair and pair[0].note_id == note_id and pair[1]:
                    values.append(pair[1])
                    break
        return sorted(values, key=lambda item: item.version_number)

    def save_version(self, version: SOAPNoteVersion) -> SOAPNoteVersion:
        existing = self.get_version(version.note_version_id)
        if existing and existing != version:
            raise RepositoryConflictError("Note versions are immutable")
        self.versions.write(version.note_version_id, version.model_dump(mode="json"))
        return version.model_copy(deep=True)


class JsonTranscriptRepository(_JsonModelRepository[TranscriptRecord]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, TranscriptRecord, "transcript_id")

    def get(self, transcript_id: str) -> TranscriptRecord | None:
        return self.get_model(transcript_id)

    def save(self, transcript: TranscriptRecord) -> TranscriptRecord:
        return self.save_model(transcript)


class JsonPreVisitSummaryRepository(_JsonModelRepository[PreVisitSummary]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, PreVisitSummary, "summary_id")

    def latest(self, patient_id: str) -> PreVisitSummary | None:
        values = [item for item in self.list_models() if item.patient_id == patient_id]
        return max(values, key=lambda item: item.created_at, default=None)

    def save(self, summary: PreVisitSummary) -> PreVisitSummary:
        return self.save_model(summary)


class JsonAfterVisitSummaryRepository(_JsonModelRepository[AfterVisitSummary]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, AfterVisitSummary, "after_visit_summary_id")

    def get_for_encounter(
        self,
        encounter_id: str,
        *,
        language: SummaryLanguage | None = None,
    ) -> AfterVisitSummary | None:
        values = [
            item
            for item in self.list_models()
            if item.encounter_id == encounter_id and (language is None or item.language == language)
        ]
        return max(values, key=lambda item: item.created_at, default=None)

    def save(self, summary: AfterVisitSummary) -> AfterVisitSummary:
        return self.save_model(summary)


class JsonTemplateRepository(_JsonModelRepository[ClinicalTemplate]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, ClinicalTemplate, "template_id")

    def get(self, template_id: str) -> ClinicalTemplate | None:
        return self.get_model(template_id)

    def list(self, *, active_only: bool = True) -> list[ClinicalTemplate]:
        return [item for item in self.list_models() if not active_only or item.active]

    def save(self, template: ClinicalTemplate) -> ClinicalTemplate:
        return self.save_model(template)


class JsonCodeSuggestionRepository(_JsonModelRepository[CodeSuggestion]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, CodeSuggestion, "code_suggestion_id")

    def get(self, suggestion_id: str) -> CodeSuggestion | None:
        return self.get_model(suggestion_id)

    def list_for_note(self, note_id: str) -> list[CodeSuggestion]:
        return [item for item in self.list_models() if item.note_id == note_id]

    def save(self, suggestion: CodeSuggestion) -> CodeSuggestion:
        return self.save_model(suggestion)

    def delete(self, suggestion_id: str) -> None:
        self.delete_model(suggestion_id)


class JsonAuditRepository(_JsonModelRepository[AuditEvent]):
    def __init__(self, root: str | Path) -> None:
        super().__init__(root, AuditEvent, "audit_event_id")

    def append(self, event: AuditEvent) -> AuditEvent:
        return self.save_model(event)

    def list(self, *, patient_ref: str | None = None, event_type: str | None = None) -> list[AuditEvent]:
        return [
            item
            for item in self.list_models()
            if (patient_ref is None or item.patient_ref == patient_ref)
            and (event_type is None or item.event_type == event_type)
        ]
