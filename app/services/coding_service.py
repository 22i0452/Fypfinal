from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.audit_service import AuditService
from medflow.domain.enums import CodeSuggestionStatus, NoteStatus
from medflow.domain.ids import new_id
from medflow.domain.models import CodeSuggestion, SOAPNoteVersion, utc_now
from medflow.repositories.protocols import CodeSuggestionRepository, NoteRepository
from security_guardrails import Actor, AuthorizationError, require_authorized


class CodingServiceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class CodingCandidate:
    code: str
    description: str
    confidence: float
    evidence_ids: list[str]
    system: str = "ICD-10"


class CodingProvider(Protocol):
    def suggest(self, version: SOAPNoteVersion) -> list[CodingCandidate]: ...


class DisabledCodingProvider:
    def suggest(self, version: SOAPNoteVersion) -> list[CodingCandidate]:
        raise CodingServiceError(
            "REQUIRES_EXTERNAL_SERVICE",
            "No approved ICD-10/CPT coding source/provider is configured",
        )


_ALLOWED_NOTE_STATES = {
    NoteStatus.AI_DRAFT,
    NoteStatus.REVIEW_REQUIRED,
    NoteStatus.APPROVED_BY_DOCTOR,
    NoteStatus.AMENDED,
}


class CodingService:
    def __init__(
        self,
        *,
        notes: NoteRepository,
        suggestions: CodeSuggestionRepository,
        audit: AuditService,
        provider: CodingProvider | None = None,
    ) -> None:
        self.notes = notes
        self.suggestions = suggestions
        self.audit = audit
        self.provider = provider or DisabledCodingProvider()

    def generate(
        self,
        *,
        note_id: str,
        actor: Actor,
        force: bool = False,
    ) -> list[CodeSuggestion]:
        note = self.notes.get(note_id)
        if note is None:
            raise CodingServiceError("NOTE_NOT_FOUND", "Note was not found")
        self._require(actor, "generate_code_suggestions", note.patient_id)
        version = self.notes.get_version(note.current_version_id)
        if version is None or note.state not in _ALLOWED_NOTE_STATES:
            raise CodingServiceError(
                "NOTE_NOT_READY",
                "ICD-10/CPT suggestions require a generated SOAP note draft or approved version",
            )
        existing = self.suggestions.list_for_note(note_id)
        if existing and not force:
            return existing
        if force and existing:
            for item in existing:
                if item.status == CodeSuggestionStatus.SUGGESTED:
                    self.suggestions.delete(item.code_suggestion_id)

        valid_claim_ids = {
            claim.claim_id
            for claims in (
                version.soap.subjective,
                version.soap.objective,
                version.soap.assessment,
                version.soap.plan,
            )
            for claim in claims
        }
        candidates = self.provider.suggest(version)
        if not candidates:
            raise CodingServiceError("EMPTY_CODING_RESULT", "Coding provider returned no suggestions")

        created: list[CodeSuggestion] = []
        for candidate in candidates:
            system = str(candidate.system or "ICD-10").strip().upper()
            if system in {"ICD10", "ICD-10-CM", "ICD10CM"}:
                system = "ICD-10"
            if system in {"CPT4", "HCPCS"}:
                system = "CPT"
            if system not in {"ICD-10", "CPT"}:
                system = "ICD-10"
            code = str(candidate.code or "").strip()
            description = str(candidate.description or "").strip()
            evidence_ids = list(dict.fromkeys(str(item) for item in candidate.evidence_ids if item))
            if not code or not description or not evidence_ids or not set(evidence_ids).issubset(valid_claim_ids):
                raise CodingServiceError(
                    "INVALID_CODING_EVIDENCE",
                    "Coding suggestion must reference claims in the current note version",
                )
            created.append(
                self.suggestions.save(
                    CodeSuggestion(
                        code_suggestion_id=new_id("CODE"),
                        patient_id=note.patient_id,
                        note_id=note.note_id,
                        note_version_id=version.note_version_id,
                        system=system,
                        code=code,
                        description=description,
                        confidence=max(0.0, min(float(candidate.confidence), 1.0)),
                        evidence_ids=evidence_ids,
                        status=CodeSuggestionStatus.SUGGESTED,
                    )
                )
            )
        self.audit.record(
            "code_suggestions_generated",
            actor_ref=actor.ref,
            action="generate_code_suggestions",
            patient_ref=note.patient_id,
            resource_ref=note.note_id,
            metadata={
                "suggestion_count": len(created),
                "note_version_ref": version.note_version_id,
                "systems": sorted({item.system for item in created}),
                "force": force,
            },
        )
        return self.suggestions.list_for_note(note_id)

    def list_for_note(self, *, note_id: str, actor: Actor) -> list[CodeSuggestion]:
        note = self.notes.get(note_id)
        if note is None:
            raise CodingServiceError("NOTE_NOT_FOUND", "Note was not found")
        self._require(actor, "generate_code_suggestions", note.patient_id)
        return self.suggestions.list_for_note(note_id)

    def review(
        self,
        *,
        suggestion_id: str,
        approve: bool,
        actor: Actor,
    ) -> CodeSuggestion:
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion is None:
            raise CodingServiceError("CODE_SUGGESTION_NOT_FOUND", "Code suggestion was not found")
        self._require(actor, "review_code_suggestion", suggestion.patient_id)
        if suggestion.status != CodeSuggestionStatus.SUGGESTED:
            raise CodingServiceError("INVALID_CODE_STATE", "Code suggestion was already reviewed")
        updated = suggestion.model_copy(
            update={
                "status": CodeSuggestionStatus.APPROVED if approve else CodeSuggestionStatus.REJECTED,
                "reviewed_by_actor_id": actor.actor_id,
                "reviewed_at": utc_now(),
            }
        )
        self.suggestions.save(updated)
        self.audit.record(
            "code_suggestion_reviewed",
            actor_ref=actor.ref,
            action="review_code_suggestion",
            patient_ref=updated.patient_id,
            resource_ref=updated.code_suggestion_id,
            metadata={"decision": updated.status.value, "system": updated.system},
        )
        return updated

    @staticmethod
    def _require(actor: Actor, action: str, patient_id: str) -> None:
        try:
            require_authorized(actor, action, patient_id)
        except AuthorizationError as exc:
            raise CodingServiceError("FORBIDDEN", "Actor is not authorized for this patient") from exc
