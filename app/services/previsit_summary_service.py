from __future__ import annotations

from app.services.audit_service import AuditService
from medflow.domain.enums import NoteStatus
from medflow.domain.ids import new_id
from medflow.domain.models import PreVisitSummary, SummaryItem, SummarySection
from medflow.repositories.protocols import (
    EncounterRepository,
    NoteRepository,
    PatientRepository,
    PreVisitSummaryRepository,
)
from security_guardrails import Actor, AuthorizationError, require_authorized


class PreVisitSummaryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PreVisitSummaryService:
    def __init__(
        self,
        *,
        patients: PatientRepository,
        encounters: EncounterRepository,
        notes: NoteRepository,
        summaries: PreVisitSummaryRepository,
        audit: AuditService,
    ) -> None:
        self.patients = patients
        self.encounters = encounters
        self.notes = notes
        self.summaries = summaries
        self.audit = audit

    def generate(self, *, patient_id: str, encounter_id: str, actor: Actor) -> PreVisitSummary:
        self._require(actor, patient_id)
        patient = self.patients.get(patient_id)
        if patient is None:
            raise PreVisitSummaryError("PATIENT_NOT_FOUND", "Patient was not found")
        encounter = self.encounters.get(encounter_id)
        if encounter is None:
            raise PreVisitSummaryError("ENCOUNTER_NOT_FOUND", "Encounter was not found")
        if encounter.patient_id != patient_id:
            raise PreVisitSummaryError("PATIENT_MISMATCH", "Encounter does not belong to this patient")

        sections: list[SummarySection] = []
        if patient.current_complaint:
            sections.append(
                SummarySection(
                    title="Reason for visit",
                    items=[
                        SummaryItem(
                            text=patient.current_complaint,
                            evidence_ids=[f"PATIENT:{patient.patient_id}:current_complaint"],
                        )
                    ],
                )
            )
        if patient.past_medical_history:
            sections.append(
                SummarySection(
                    title="Important medical history",
                    items=[
                        SummaryItem(
                            text=patient.past_medical_history,
                            evidence_ids=[f"PATIENT:{patient.patient_id}:past_medical_history"],
                        )
                    ],
                )
            )

        source_versions: list[str] = []
        approved_items: list[SummaryItem] = []
        approved_notes = [
            note for note in self.notes.list(patient_id=patient_id) if note.state == NoteStatus.APPROVED_BY_DOCTOR
        ]
        for note in sorted(approved_notes, key=lambda item: item.updated_at, reverse=True)[:5]:
            version = self.notes.get_version(note.current_version_id)
            if version is None or version.status != NoteStatus.APPROVED_BY_DOCTOR:
                continue
            source_versions.append(version.note_version_id)
            for claim in [*version.soap.assessment, *version.soap.plan]:
                if claim.text and claim.text.lower() != "not documented.":
                    approved_items.append(
                        SummaryItem(
                            text=claim.text,
                            evidence_ids=[f"{version.note_version_id}:{claim.claim_id}"],
                        )
                    )
        if approved_items:
            sections.append(SummarySection(title="Previous approved notes", items=approved_items[:10]))

        warnings = [] if source_versions else ["No previous approved clinical note is available."]
        summary = self.summaries.save(
            PreVisitSummary(
                summary_id=new_id("PVS"),
                patient_id=patient_id,
                encounter_id=encounter_id,
                sections=sections,
                warnings=warnings,
                source_note_version_ids=source_versions,
            )
        )
        self.audit.record(
            "previsit_summary_generated",
            actor_ref=actor.ref,
            action="generate_previsit_summary",
            patient_ref=patient_id,
            resource_ref=summary.summary_id,
            metadata={"approved_source_count": len(source_versions)},
        )
        return summary

    def latest(self, *, patient_id: str, actor: Actor) -> PreVisitSummary | None:
        self._require(actor, patient_id)
        return self.summaries.latest(patient_id)

    @staticmethod
    def _require(actor: Actor, patient_id: str) -> None:
        try:
            require_authorized(actor, "generate_previsit_summary", patient_id)
        except AuthorizationError as exc:
            raise PreVisitSummaryError("FORBIDDEN", "Actor is not authorized for this patient") from exc
