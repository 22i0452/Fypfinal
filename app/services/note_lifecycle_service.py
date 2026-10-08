from __future__ import annotations

from typing import Any

from app.services.audit_service import AuditService
from app.services.documentation_service import DocumentationService
from medflow.domain.enums import ClaimSupportStatus, NoteStatus, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import ClinicalClaim, SOAPNote, SOAPNoteVersion, StructuredSOAP, utc_now
from medflow.orchestration import ClinicWorkflowOrchestrator, WorkflowAction
from medflow.repositories.protocols import NoteRepository, TranscriptRepository, WorkflowRepository
from security_guardrails import Actor, AuthorizationError, require_authorized
from medflow.medicines import report as medicine_report, soap_issues


class NoteLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class NoteLifecycleService:
    def __init__(
        self,
        *,
        notes: NoteRepository,
        transcripts: TranscriptRepository,
        workflows: WorkflowRepository,
        orchestrator: ClinicWorkflowOrchestrator,
        audit: AuditService,
    ) -> None:
        self.notes = notes
        self.transcripts = transcripts
        self.workflows = workflows
        self.orchestrator = orchestrator
        self.audit = audit

    def get(self, note_id: str, *, actor: Actor) -> tuple[SOAPNote, SOAPNoteVersion]:
        note = self.notes.get(note_id)
        if note is None:
            raise NoteLifecycleError("NOTE_NOT_FOUND", "Note was not found")
        self._require(actor, "read_notes", note.patient_id)
        version = self.notes.get_version(note.current_version_id)
        if version is None:
            raise NoteLifecycleError("NOTE_VERSION_NOT_FOUND", "Current note version was not found")
        return note, version

    def list(self, *, actor: Actor, patient_id: str | None = None) -> list[tuple[SOAPNote, SOAPNoteVersion]]:
        if patient_id:
            self._require(actor, "read_notes", patient_id)
        values: list[tuple[SOAPNote, SOAPNoteVersion]] = []
        for note in self.notes.list(patient_id=patient_id):
            try:
                self._require(actor, "read_notes", note.patient_id)
            except NoteLifecycleError:
                continue
            version = self.notes.get_version(note.current_version_id)
            if version:
                values.append((note, version))
        return sorted(values, key=lambda item: item[0].updated_at, reverse=True)

    def edit_legacy_sections(
        self,
        note_id: str,
        *,
        sections: dict[str, str],
        actor: Actor,
        change_reason: str = "Doctor edit",
    ) -> tuple[SOAPNote, SOAPNoteVersion]:
        note, current = self.get(note_id, actor=actor)
        self._require(actor, "create_note_draft", note.patient_id)
        next_state = (
            NoteStatus.AMENDED
            if note.state == NoteStatus.APPROVED_BY_DOCTOR
            else NoteStatus.AI_DRAFT
        )
        structured = current.soap.model_copy(
            update={
                section: self._edited_claims(note_id, section, getattr(current.soap, section), sections[section])
                for section in ("subjective", "objective", "assessment", "plan")
            }
        )
        version = self._new_version(
            note,
            current,
            status=next_state,
            soap=structured,
            actor=actor,
            change_reason=change_reason,
        )
        if any(sections[k] != DocumentationService.legacy_soap(current.soap)[k] for k in ('subjective', 'objective', 'assessment', 'plan')):
            version.prescription = None
        updated = note.model_copy(
            update={
                "current_version_id": version.note_version_id,
                "state": next_state,
                "approved_by_doctor_id": None,
                "approved_at": None,
                "rejected_by_doctor_id": None,
                "rejected_at": None,
                "updated_at": utc_now(),
            }
        )
        self.notes.save_version(version)
        self.notes.save(updated)
        self._audit(updated, actor, "note_edited", {"version": version.version_number})
        return updated, version

    def submit_for_review(self, note_id: str, *, actor: Actor) -> tuple[SOAPNote, SOAPNoteVersion]:
        note, current = self.get(note_id, actor=actor)
        self._require(actor, "create_note_draft", note.patient_id)
        if note.state not in {NoteStatus.AI_DRAFT, NoteStatus.AMENDED, NoteStatus.REJECTED}:
            raise NoteLifecycleError("INVALID_NOTE_STATE", "Note cannot be submitted for review")
        version = self._new_version(
            note,
            current,
            status=NoteStatus.REVIEW_REQUIRED,
            soap=current.soap,
            actor=actor,
            change_reason="Submitted for doctor review",
        )
        updated = note.model_copy(
            update={
                "current_version_id": version.note_version_id,
                "state": NoteStatus.REVIEW_REQUIRED,
                "rejected_by_doctor_id": None,
                "rejected_at": None,
                "updated_at": utc_now(),
            }
        )
        self.notes.save_version(version)
        self.notes.save(updated)
        workflow = self._workflow_for_note(updated)
        if workflow and workflow.state == WorkflowState.DOCUMENTATION_PROCESSING:
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.DOCUMENTATION_READY,
                actor=actor,
                expected_version=workflow.version,
            )
        self._audit(updated, actor, "note_submitted", {"version": version.version_number})
        return updated, version

    def reject(self, note_id: str, *, actor: Actor, reason: str) -> tuple[SOAPNote, SOAPNoteVersion]:
        note, current = self.get(note_id, actor=actor)
        self._require(actor, "approve_note", note.patient_id)
        if note.state != NoteStatus.REVIEW_REQUIRED:
            raise NoteLifecycleError("INVALID_NOTE_STATE", "Only a review-required note can be rejected")
        version = self._new_version(
            note,
            current,
            status=NoteStatus.REJECTED,
            soap=current.soap,
            actor=actor,
            change_reason=str(reason or "Rejected by doctor")[:240],
        )
        now = utc_now()
        updated = note.model_copy(
            update={
                "current_version_id": version.note_version_id,
                "state": NoteStatus.REJECTED,
                "rejected_by_doctor_id": actor.actor_id,
                "rejected_at": now,
                "updated_at": now,
            }
        )
        self.notes.save_version(version)
        self.notes.save(updated)
        self._audit(updated, actor, "note_rejected", {"version": version.version_number})
        return updated, version

    def approve(self, note_id: str, *, actor: Actor) -> tuple[SOAPNote, SOAPNoteVersion]:
        note, current = self.get(note_id, actor=actor)
        self._require(actor, "approve_note", note.patient_id)
        if note.state != NoteStatus.REVIEW_REQUIRED:
            raise NoteLifecycleError("INVALID_NOTE_STATE", "Only a review-required note can be approved")
        transcript=self.transcripts.get(current.transcript_id) if current.transcript_id else None
        if transcript and soap_issues(transcript.utterances,DocumentationService.legacy_soap(current.soap)):
            raise NoteLifecycleError('MEDICINE_REVIEW_REQUIRED','Medicine wording or its stated dose differs from the conversation. Correct the SOAP section before approval.')
        unsupported = current.soap.unsupported_claims + [
            claim
            for section in (current.soap.subjective, current.soap.objective, current.soap.assessment, current.soap.plan)
            for claim in section
            if claim.status == ClaimSupportStatus.UNSUPPORTED
        ]
        if unsupported:
            raise NoteLifecycleError("UNSUPPORTED_CLAIMS", "Unsupported clinical claims must be resolved")
        version = self._new_version(
            note,
            current,
            status=NoteStatus.APPROVED_BY_DOCTOR,
            soap=current.soap,
            actor=actor,
            change_reason="Approved by authenticated doctor",
        )
        now = utc_now()
        updated = note.model_copy(
            update={
                "current_version_id": version.note_version_id,
                "state": NoteStatus.APPROVED_BY_DOCTOR,
                "approved_by_doctor_id": actor.actor_id,
                "approved_at": now,
                "rejected_by_doctor_id": None,
                "rejected_at": None,
                "updated_at": now,
            }
        )
        self.notes.save_version(version)
        self.notes.save(updated)
        workflow = self._workflow_for_note(updated)
        if workflow and workflow.state == WorkflowState.NOTE_REVIEW_REQUIRED:
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.APPROVE_NOTE,
                actor=actor,
                expected_version=workflow.version,
            )
        self._audit(updated, actor, "doctor_approval", {"version": version.version_number})
        return updated, version

    def versions(self, note_id: str, *, actor: Actor) -> list[SOAPNoteVersion]:
        note, _ = self.get(note_id, actor=actor)
        return self.notes.list_versions(note.note_id)

    def payload(self, note: SOAPNote, version: SOAPNoteVersion, *, patient_name: str = "") -> dict[str, Any]:
        transcript = self.transcripts.get(version.transcript_id) if version.transcript_id else None
        legacy = DocumentationService.legacy_soap(version.soap)
        medicines=medicine_report(transcript.utterances) if transcript else {'checks':[],'requires_review':False}
        medicines['soap_issues']=soap_issues(transcript.utterances,legacy) if transcript else []
        medicines['requires_review']=medicines['requires_review'] or bool(medicines['soap_issues'])
        from app.services.medicine_evidence import medicine_evidence
        medicine_receipts = medicine_evidence(transcript.utterances if transcript else [], legacy, version.version_number)
        from app.services.evidence_checks import note_evidence_report
        from app.services.conversation_relevance import report as relevance_report
        report = note_evidence_report(version.soap, transcript, state=version.status, version=version.version_number, note_id=note.note_id, approval={"doctor_id": note.approved_by_doctor_id, "approved_at": note.approved_at.isoformat() if note.approved_at else None} if version.status == NoteStatus.APPROVED_BY_DOCTOR else None)
        return {
            "note_id": note.note_id,
            "patient_id": note.patient_id,
            "patient_name": patient_name or "Patient",
            "encounter_id": note.encounter_id,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
            "state": note.state.value,
            "version": version.version_number,
            "approval": {
                "doctor_id": note.approved_by_doctor_id,
                "approved_at": note.approved_at.isoformat() if note.approved_at else None,
                "version": version.version_number,
            }
            if note.approved_by_doctor_id
            else None,
            "excerpt": legacy["assessment"][:220],
            "soap": {
                **legacy,
                "structured_soap": version.soap.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in version.evidence],
                "generated_by": "AI Medical Scribe",
                "medicine_report":medicines,
                "medicine_evidence":medicine_receipts,
                "symptom_patterns":transcript.symptom_patterns if transcript else {},
                "evidence_report": report,
                "relevance_report": relevance_report(transcript.utterances if transcript else [], version.soap),
                "prescription": version.prescription,
            },
            "transcript": [DocumentationService.utterance_payload(item, translated=True) for item in transcript.utterances]
            if transcript
            else [],
        }

    def _new_version(
        self,
        note: SOAPNote,
        current: SOAPNoteVersion,
        *,
        status: NoteStatus,
        soap: StructuredSOAP,
        actor: Actor,
        change_reason: str,
    ) -> SOAPNoteVersion:
        return SOAPNoteVersion(
            note_version_id=new_id("NV"),
            note_id=note.note_id,
            version_number=max([item.version_number for item in self.notes.list_versions(note.note_id)] or [0]) + 1,
            status=status,
            soap=soap,
            evidence=current.evidence,
            transcript_id=current.transcript_id,
            template_id=current.template_id,
            created_by_actor_id=actor.actor_id,
            change_reason=change_reason,
            prescription=current.prescription,
        )

    @staticmethod
    def _edited_claims(
        note_id: str,
        section: str,
        current: list[ClinicalClaim],
        text: str,
    ) -> list[ClinicalClaim]:
        clean = str(text or "").strip() or "Not documented."
        current_text = "\n".join(item.text for item in current).strip()
        if clean == current_text:
            return [item.model_copy(deep=True) for item in current]
        return [
            ClinicalClaim(
                claim_id=f"{note_id}-{section.upper()}-{new_id('CLM')}",
                text=clean,
                evidence_ids=[],
                status=ClaimSupportStatus.REVIEW_REQUIRED,
            )
        ]

    def _workflow_for_note(self, note: SOAPNote):
        return next(
            (
                item
                for item in self.workflows.list(patient_id=note.patient_id)
                if item.note_id == note.note_id or item.encounter_id == note.encounter_id
            ),
            None,
        )

    @staticmethod
    def _require(actor: Actor, action: str, patient_id: str) -> None:
        try:
            require_authorized(actor, action, patient_id)
        except AuthorizationError as exc:
            raise NoteLifecycleError("FORBIDDEN", "Actor is not authorized for this note") from exc

    def _audit(self, note: SOAPNote, actor: Actor, event_type: str, metadata: dict[str, Any]) -> None:
        self.audit.record(
            event_type,
            actor_ref=actor.ref,
            action=event_type,
            patient_ref=note.patient_id,
            resource_ref=note.note_id,
            metadata={"state": note.state.value, **metadata},
        )
