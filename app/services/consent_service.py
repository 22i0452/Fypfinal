from __future__ import annotations

from dataclasses import dataclass

from app.services.audit_service import AuditService
from medflow.domain.enums import ConsentType, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import ConsentRecord, utc_now
from medflow.repositories.protocols import ConsentRepository, EncounterRepository, WorkflowRepository
from security_guardrails import Actor
from security_guardrails.authz import is_patient_authorized


REQUIRED_AUDIO_CONSENTS = {
    ConsentType.AUDIO_RECORDING,
    ConsentType.AI_TRANSCRIPTION,
    ConsentType.AI_DOCUMENTATION,
}


class ConsentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AudioWorkflowAuthorization:
    patient_id: str
    encounter_id: str
    workflow_id: str
    retain_audio: bool


class ConsentService:
    def __init__(
        self,
        *,
        consents: ConsentRepository,
        encounters: EncounterRepository,
        workflows: WorkflowRepository,
        audit: AuditService,
    ) -> None:
        self.consents = consents
        self.encounters = encounters
        self.workflows = workflows
        self.audit = audit

    def capture_bundle(
        self,
        *,
        encounter_id: str,
        decisions: dict[ConsentType, bool],
        consent_text_version: str,
        capture_method: str,
        actor: Actor,
    ) -> list[ConsentRecord]:
        expected = set(ConsentType)
        if set(decisions) != expected:
            raise ConsentError("INCOMPLETE_CONSENT", "All four consent decisions are required")
        encounter = self._authorized_encounter(encounter_id, actor)
        captured_at = utc_now()
        records: list[ConsentRecord] = []
        for consent_type in ConsentType:
            record = ConsentRecord(
                consent_id=new_id("CNS"),
                patient_id=encounter.patient_id,
                encounter_id=encounter.encounter_id,
                consent_type=consent_type,
                decision=bool(decisions[consent_type]),
                consent_text_version=consent_text_version,
                captured_by=actor.actor_id,
                capture_method=capture_method,
                captured_at=captured_at,
            )
            records.append(self.consents.save(record))
            self.audit.record(
                "recording_consent",
                actor_ref=actor.ref,
                action="capture_consent",
                patient_ref=encounter.patient_id,
                resource_ref=encounter.encounter_id,
                metadata={"consent_type": consent_type.value, "decision": record.decision},
            )
        return records

    def revoke(self, *, consent_id: str, actor: Actor) -> ConsentRecord:
        record = self.consents.get(consent_id)
        if record is None:
            raise ConsentError("CONSENT_NOT_FOUND", "Consent record was not found")
        self._authorized_encounter(record.encounter_id, actor)
        if record.revoked_at is not None:
            return record
        revoked = record.model_copy(update={"revoked_at": utc_now()})
        self.consents.save(revoked)
        self.audit.record(
            "recording_consent_revoked",
            actor_ref=actor.ref,
            action="revoke_consent",
            patient_ref=record.patient_id,
            resource_ref=record.encounter_id,
            metadata={"consent_type": record.consent_type.value},
        )
        return revoked

    def latest_decisions(self, encounter_id: str, *, actor: Actor) -> dict[ConsentType, ConsentRecord | None]:
        self._authorized_encounter(encounter_id, actor)
        return {consent_type: self.consents.latest(encounter_id, consent_type) for consent_type in ConsentType}

    def authorize_audio_start(
        self,
        *,
        encounter_id: str,
        workflow_id: str,
        patient_id: str,
        actor: Actor,
    ) -> AudioWorkflowAuthorization:
        encounter = self._authorized_encounter(encounter_id, actor)
        workflow = self.workflows.get(workflow_id)
        if encounter.patient_id != patient_id:
            raise ConsentError("PATIENT_MISMATCH", "Encounter does not belong to the selected patient")
        if workflow is None or workflow.workflow_id != encounter.workflow_id or workflow.patient_id != patient_id:
            raise ConsentError("WORKFLOW_MISMATCH", "Encounter does not belong to the workflow")
        if workflow.state not in {WorkflowState.CONSULTATION_READY, WorkflowState.CONSULTATION_ACTIVE}:
            raise ConsentError("INVALID_WORKFLOW_STATE", "Workflow is not ready for consultation recording")
        missing: list[str] = []
        for consent_type in REQUIRED_AUDIO_CONSENTS:
            record = self.consents.latest(encounter_id, consent_type)
            if record is None or not record.is_active:
                missing.append(consent_type.value)
        if missing:
            self.audit.record(
                "recording_start_denied",
                actor_ref=actor.ref,
                action="start_recording",
                patient_ref=patient_id,
                resource_ref=encounter_id,
                result="deny",
                metadata={"missing_consent_types": missing},
            )
            raise ConsentError("REQUIRED_CONSENT_MISSING", "Required recording and AI consent is missing")
        retention = self.consents.latest(encounter_id, ConsentType.AUDIO_RETENTION)
        return AudioWorkflowAuthorization(
            patient_id=patient_id,
            encounter_id=encounter_id,
            workflow_id=workflow_id,
            retain_audio=bool(retention and retention.is_active),
        )

    def _authorized_encounter(self, encounter_id: str, actor: Actor):
        encounter = self.encounters.get(encounter_id)
        if encounter is None:
            raise ConsentError("ENCOUNTER_NOT_FOUND", "Encounter was not found")
        if actor.role != "doctor" or not is_patient_authorized(actor, encounter.patient_id):
            raise ConsentError("FORBIDDEN", "Actor is not authorized for this encounter")
        return encounter
