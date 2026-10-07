from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from collections import defaultdict
from threading import RLock
import math
import time

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
    confidence: float | None
    evidence_ids: list[str]
    system: str = "ICD-10"
    method: str = "PROVIDER_SUGGESTION"


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
        transcripts=None,
    ) -> None:
        self.notes = notes
        self.suggestions = suggestions
        self.audit = audit
        self.provider = provider or DisabledCodingProvider()
        self.transcripts = transcripts
        self._locks = defaultdict(RLock)

    def generate(
        self,
        *,
        note_id: str,
        actor: Actor,
        force: bool = False,
    ) -> list[CodeSuggestion]:
        with self._locks[note_id]:
            return self._generate(note_id=note_id,actor=actor,force=force)

    def _generate(self, *, note_id, actor, force):
        note = self.notes.get(note_id)
        if note is None:
            raise CodingServiceError("NOTE_NOT_FOUND", "Note was not found")
        self._require(actor, "generate_code_suggestions", note.patient_id)
        version = self.notes.get_version(note.current_version_id)
        if version is None or version.note_id!=note.note_id or note.state not in _ALLOWED_NOTE_STATES:
            raise CodingServiceError(
                "NOTE_NOT_READY",
                "ICD-10/CPT suggestions require a generated SOAP note draft or approved version",
            )
        existing = [item for item in self.suggestions.list_for_note(note_id) if item.note_version_id==version.note_version_id]
        if existing and not force:
            return existing
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
        started = time.perf_counter()
        candidates = self.provider.suggest(version)
        duration_ms = (time.perf_counter()-started)*1000
        if not candidates:
            raise CodingServiceError("EMPTY_CODING_RESULT", "No supported codes were returned. Review the documentation before retrying; a procedure code may need more detail.")

        created: list[CodeSuggestion] = []
        seen = {(item.system,item.code.upper(),tuple(sorted(item.evidence_ids))) for item in existing if item.status!=CodeSuggestionStatus.SUGGESTED}
        for candidate in candidates:
            system = str(candidate.system or "ICD-10").strip().upper()
            if system in {"ICD10", "ICD-10-CM", "ICD10CM"}:
                system = "ICD-10"
            if system in {"CPT4"}:
                system = "CPT"
            if system not in {"ICD-10", "CPT"}:
                raise CodingServiceError("INVALID_CODING_EVIDENCE", "Unsupported coding system returned")
            code = str(candidate.code or "").strip().upper()
            description = str(candidate.description or "").strip()
            evidence_ids = list(dict.fromkeys(str(item) for item in candidate.evidence_ids if item))
            if not code or not description or not evidence_ids or not set(evidence_ids).issubset(valid_claim_ids):
                raise CodingServiceError(
                    "INVALID_CODING_EVIDENCE",
                    "Coding suggestion must reference claims in the current note version",
                )
            try:
                score = float(candidate.confidence) if candidate.confidence is not None else None
                if score is not None and not math.isfinite(score):
                    raise ValueError('Non-finite score')
            except (TypeError,ValueError) as exc:
                raise CodingServiceError("INVALID_CODING_EVIDENCE", "Provider score must be finite") from exc
            identity = (system,code,tuple(sorted(evidence_ids)))
            if identity in seen:
                continue
            seen.add(identity)
            created.append(
                    CodeSuggestion(
                        code_suggestion_id=new_id("CODE"),
                        patient_id=note.patient_id,
                        note_id=note.note_id,
                        note_version_id=version.note_version_id,
                        system=system,
                        code=code,
                        description=description,
                        confidence=max(0.0, min(score, 1.0)) if score is not None else None,
                        evidence_ids=evidence_ids,
                        generation_method=candidate.method,
                        generation_duration_ms=duration_ms,
                        status=CodeSuggestionStatus.SUGGESTED,
                    )
            )
        latest = self.notes.get(note_id)
        if not latest or latest.current_version_id != version.note_version_id:
            raise CodingServiceError("VERSION_CONFLICT", "SOAP changed during generation. Generate codes for its current version.")
        # Validate the entire result before replacing any prior suggestions.
        if force:
            for item in existing:
                if item.status == CodeSuggestionStatus.SUGGESTED:
                    self.suggestions.delete(item.code_suggestion_id)
        for item in created:
            self.suggestions.save(item)
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
        return [item for item in self.suggestions.list_for_note(note_id) if item.note_version_id==version.note_version_id]

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
            raise CodingServiceError('CODE_SUGGESTION_NOT_FOUND','Code suggestion was not found')
        self._require(actor,'review_code_suggestion',suggestion.patient_id)
        with self._locks[suggestion.note_id]:
            return self._review(suggestion_id=suggestion_id,approve=approve,actor=actor)

    def _review(self, *, suggestion_id, approve, actor):
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion is None:
            raise CodingServiceError("CODE_SUGGESTION_NOT_FOUND", "Code suggestion was not found")
        self._require(actor, "review_code_suggestion", suggestion.patient_id)
        note = self.notes.get(suggestion.note_id)
        if not note or note.patient_id!=suggestion.patient_id:
            raise CodingServiceError('INVALID_CODING_EVIDENCE','Suggestion is not attached to this patient note')
        if note.current_version_id != suggestion.note_version_id:
            raise CodingServiceError("VERSION_CONFLICT", "SOAP changed since this suggestion. Generate codes from the current version before review.")
        version=self.notes.get_version(suggestion.note_version_id)
        ids={claim.claim_id for section in ('subjective','objective','assessment','plan') for claim in getattr(version.soap,section)} if version and version.note_id==note.note_id else set()
        if not set(suggestion.evidence_ids).issubset(ids):
            raise CodingServiceError('INVALID_CODING_EVIDENCE','Suggestion references an unavailable SOAP statement')
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

    def evidence(self, *, suggestion_id, actor):
        suggestion = self.suggestions.get(suggestion_id)
        if not suggestion:
            raise CodingServiceError('CODE_SUGGESTION_NOT_FOUND','Code suggestion was not found')
        self._require(actor,'review_code_suggestion',suggestion.patient_id)
        note = self.notes.get(suggestion.note_id)
        version = self.notes.get_version(suggestion.note_version_id)
        if not note or note.patient_id!=suggestion.patient_id or not version or version.note_id!=note.note_id:
            raise CodingServiceError('INVALID_CODING_EVIDENCE','The saved suggestion source is unavailable')
        transcript = self.transcripts.get(version.transcript_id) if self.transcripts and version.transcript_id else None
        if transcript and (transcript.patient_id!=note.patient_id or transcript.encounter_id!=note.encounter_id):
            transcript = None
        turns = {item.utterance_id:item for item in transcript.utterances} if transcript else {}
        claims = []
        for section in ('subjective','objective','assessment','plan'):
            for claim in getattr(version.soap,section):
                if claim.claim_id not in suggestion.evidence_ids:
                    continue
                sources=[]
                for source_id in claim.evidence_ids:
                    turn=turns.get(source_id)
                    sources.append({'utterance_id':source_id,'available':bool(turn),'original_text':turn.original_text if turn else None,'clinical_english':turn.clinical_english if turn else None,'speaker':turn.speaker.value.title() if turn else None})
                claims.append({'claim_id':claim.claim_id,'section':section,'text':claim.text,'sources':sources,'source_ids':claim.evidence_ids})
        missing = [key for key in suggestion.evidence_ids if key not in {item['claim_id'] for item in claims}]
        stale = note.current_version_id != version.note_version_id
        return {'suggestion':suggestion.model_dump(mode='json'),'note_id':note.note_id,'patient_id':note.patient_id,'encounter_id':note.encounter_id,'note_version_id':version.note_version_id,'version':version.version_number,'transcript_id':version.transcript_id,'stale':stale,'claims':claims,'missing_claim_ids':missing,'reference_check':'FAILED' if missing else 'LINKED','clinical_correctness':'UNASSESSED','catalog_validation':'UNASSESSED','confidence_status':'Provider score is uncalibrated; accuracy has not been measured.'}

    @staticmethod
    def _require(actor: Actor, action: str, patient_id: str) -> None:
        try:
            require_authorized(actor, action, patient_id)
        except AuthorizationError as exc:
            raise CodingServiceError("FORBIDDEN", "Actor is not authorized for this patient") from exc
