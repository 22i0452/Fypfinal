from __future__ import annotations

from dataclasses import dataclass

from app.services.appointment_service import AppointmentError, AppointmentService
from app.services.audit_service import AuditService
from medflow.domain.enums import AppointmentStatus, EncounterStatus, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import Appointment, Encounter, WorkflowSession, utc_now
from medflow.orchestration import (
    ClinicWorkflowOrchestrator,
    WorkflowAction,
    WorkflowResourceLinks,
)
from medflow.repositories.protocols import EncounterRepository, WorkflowRepository
from security_guardrails import Actor


class ClinicLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ConsultationContext:
    workflow: WorkflowSession
    appointment: Appointment
    encounter: Encounter


class ClinicLifecycleService:
    """Coordinates deterministic cross-resource steps around the workflow state machine."""

    def __init__(
        self,
        *,
        workflows: WorkflowRepository,
        encounters: EncounterRepository,
        orchestrator: ClinicWorkflowOrchestrator,
        appointments: AppointmentService,
        audit: AuditService,
    ) -> None:
        self.workflows = workflows
        self.encounters = encounters
        self.orchestrator = orchestrator
        self.appointments = appointments
        self.audit = audit

    def get_or_create_workflow(self, *, patient_id: str, actor: Actor) -> WorkflowSession:
        reusable = next(
            (
                item
                for item in self.workflows.list(patient_id=patient_id)
                if item.state not in {WorkflowState.ENCOUNTER_COMPLETED, WorkflowState.CANCELLED}
            ),
            None,
        )
        if reusable is not None:
            return self.orchestrator.get_session(reusable.workflow_id, actor=actor)
        return self.orchestrator.create_session(patient_id=patient_id, actor=actor)

    def complete_existing_intake(self, workflow_id: str, *, actor: Actor) -> WorkflowSession:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if workflow.state == WorkflowState.PATIENT_VERIFIED:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.START_INTAKE,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state == WorkflowState.INTAKE_IN_PROGRESS:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.COMPLETE_INTAKE,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state == WorkflowState.INTAKE_COMPLETED:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.REQUIRE_BOOKING,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state == WorkflowState.BOOKING_REQUIRED and workflow.appointment_id:
            appointment = self.appointments.appointments.get(workflow.appointment_id)
            if appointment is None or appointment.patient_id != workflow.patient_id:
                raise ClinicLifecycleError(
                    "APPOINTMENT_MISMATCH",
                    "The pending appointment is unavailable",
                )
            if appointment.status == AppointmentStatus.REQUESTED:
                appointment = self.appointments.confirm_requested(
                    appointment.appointment_id,
                    actor=actor,
                )
            if appointment.status != AppointmentStatus.CONFIRMED:
                raise ClinicLifecycleError(
                    "INVALID_APPOINTMENT_STATUS",
                    "The pending appointment cannot be confirmed",
                )
            return self.confirm_booking(
                workflow_id,
                appointment=appointment,
                actor=actor,
            )
        if workflow.state != WorkflowState.BOOKING_REQUIRED:
            raise ClinicLifecycleError(
                "INVALID_WORKFLOW_STATE",
                "Verified intake cannot be completed from the current workflow state",
            )
        return workflow

    def confirm_booking(
        self,
        workflow_id: str,
        *,
        appointment: Appointment,
        actor: Actor,
    ) -> WorkflowSession:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if workflow.patient_id != appointment.patient_id:
            raise ClinicLifecycleError("PATIENT_MISMATCH", "Appointment belongs to another patient")
        if workflow.state == WorkflowState.INTAKE_COMPLETED:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.REQUIRE_BOOKING,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state != WorkflowState.BOOKING_REQUIRED:
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Workflow is not ready for booking")
        workflow = self.orchestrator.link_resources(
            workflow_id,
            actor=actor,
            links=WorkflowResourceLinks(
                appointment_id=appointment.appointment_id,
                assigned_practitioner_id=appointment.practitioner_id,
            ),
            expected_version=workflow.version,
        )
        return self.orchestrator.perform_action(
            workflow_id,
            WorkflowAction.CONFIRM_BOOKING,
            actor=actor,
            expected_version=workflow.version,
        )

    def check_in(self, workflow_id: str, *, actor: Actor) -> ConsultationContext:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if not workflow.appointment_id:
            raise ClinicLifecycleError("APPOINTMENT_REQUIRED", "Workflow has no confirmed appointment")
        appointment = self.appointments.appointments.get(workflow.appointment_id)
        if appointment is None or appointment.patient_id != workflow.patient_id:
            raise ClinicLifecycleError("APPOINTMENT_MISMATCH", "Workflow appointment is unavailable")
        if appointment.status == AppointmentStatus.CANCELLED:
            raise ClinicLifecycleError("APPOINTMENT_CANCELLED", "A cancelled appointment cannot check in")
        if appointment.status == AppointmentStatus.CONFIRMED:
            appointment = self.appointments.check_in(appointment.appointment_id, actor=actor)
        if appointment.status != AppointmentStatus.CHECKED_IN:
            raise ClinicLifecycleError("INVALID_APPOINTMENT_STATUS", "Appointment cannot check in")

        if workflow.state == WorkflowState.BOOKING_CONFIRMED:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.CHECK_IN,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state != WorkflowState.PATIENT_CHECKED_IN:
            existing = self._linked_encounter(workflow)
            if workflow.state == WorkflowState.CONSULTATION_READY and existing:
                return ConsultationContext(workflow, appointment, existing)
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Workflow cannot check in")

        encounter = self._linked_encounter(workflow)
        if encounter is None:
            now = utc_now()
            encounter = self.encounters.save(
                Encounter(
                    encounter_id=new_id("ENC"),
                    patient_id=workflow.patient_id,
                    practitioner_id=appointment.practitioner_id,
                    appointment_id=appointment.appointment_id,
                    workflow_id=workflow.workflow_id,
                    status=EncounterStatus.READY,
                    created_at=now,
                    updated_at=now,
                )
            )
            workflow = self.orchestrator.link_resources(
                workflow_id,
                actor=actor,
                links=WorkflowResourceLinks(encounter_id=encounter.encounter_id),
                expected_version=workflow.version,
            )
        workflow = self.orchestrator.perform_action(
            workflow_id,
            WorkflowAction.PREPARE_CONSULTATION,
            actor=actor,
            expected_version=workflow.version,
        )
        self.audit.record(
            "consultation_prepared",
            actor_ref=actor.ref,
            action="prepare_consultation",
            patient_ref=workflow.patient_id,
            resource_ref=encounter.encounter_id,
            metadata={"workflow_id": workflow.workflow_id},
        )
        return ConsultationContext(workflow, appointment, encounter)

    def start_consultation(self, workflow_id: str, *, actor: Actor) -> ConsultationContext:
        context = self._context(workflow_id, actor=actor)
        workflow = context.workflow
        appointment = context.appointment
        encounter = context.encounter
        if appointment.status == AppointmentStatus.CANCELLED:
            raise ClinicLifecycleError("APPOINTMENT_CANCELLED", "A cancelled appointment cannot start")
        if workflow.state == WorkflowState.CONSULTATION_ACTIVE:
            return context
        if workflow.state != WorkflowState.CONSULTATION_READY:
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Consultation is not ready")
        if appointment.status == AppointmentStatus.CHECKED_IN:
            appointment = self.appointments.start(appointment.appointment_id, actor=actor)
        if appointment.status != AppointmentStatus.IN_PROGRESS:
            raise ClinicLifecycleError("INVALID_APPOINTMENT_STATUS", "Appointment cannot start")
        workflow = self.orchestrator.perform_action(
            workflow_id,
            WorkflowAction.START_CONSULTATION,
            actor=actor,
            expected_version=workflow.version,
        )
        encounter = self.encounters.save(
            encounter.model_copy(
                update={
                    "status": EncounterStatus.IN_PROGRESS,
                    "started_at": encounter.started_at or utc_now(),
                    "updated_at": utc_now(),
                }
            )
        )
        self.audit.record(
            "consultation_started",
            actor_ref=actor.ref,
            action="start_consultation",
            patient_ref=workflow.patient_id,
            resource_ref=encounter.encounter_id,
            metadata={"workflow_id": workflow.workflow_id},
        )
        return ConsultationContext(workflow, appointment, encounter)

    def start_documentation(self, workflow_id: str, *, actor: Actor) -> ConsultationContext:
        context = self._context(workflow_id, actor=actor)
        workflow = context.workflow
        if workflow.state == WorkflowState.CONSULTATION_ACTIVE:
            workflow = self.orchestrator.perform_action(
                workflow_id,
                WorkflowAction.START_DOCUMENTATION,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state != WorkflowState.DOCUMENTATION_PROCESSING:
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Documentation cannot start")
        encounter = self.encounters.save(
            context.encounter.model_copy(
                update={"status": EncounterStatus.DOCUMENTATION, "updated_at": utc_now()}
            )
        )
        return ConsultationContext(workflow, context.appointment, encounter)

    def documentation_ready(
        self,
        workflow_id: str,
        *,
        note_id: str,
        actor: Actor,
    ) -> WorkflowSession:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if workflow.state != WorkflowState.DOCUMENTATION_PROCESSING:
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Documentation is not processing")
        workflow = self.orchestrator.link_resources(
            workflow_id,
            actor=actor,
            links=WorkflowResourceLinks(note_id=note_id),
            expected_version=workflow.version,
        )
        return self.orchestrator.perform_action(
            workflow_id,
            WorkflowAction.DOCUMENTATION_READY,
            actor=actor,
            expected_version=workflow.version,
        )

    def link_note_draft(self, workflow_id: str, *, note_id: str, actor: Actor) -> WorkflowSession:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if workflow.state != WorkflowState.DOCUMENTATION_PROCESSING:
            raise ClinicLifecycleError("INVALID_WORKFLOW_STATE", "Documentation is not processing")
        return self.orchestrator.link_resources(
            workflow_id,
            actor=actor,
            links=WorkflowResourceLinks(note_id=note_id),
            expected_version=workflow.version,
        )

    def _context(self, workflow_id: str, *, actor: Actor) -> ConsultationContext:
        workflow = self.orchestrator.get_session(workflow_id, actor=actor)
        if not workflow.appointment_id or not workflow.encounter_id:
            raise ClinicLifecycleError("CONSULTATION_CONTEXT_MISSING", "Consultation context is incomplete")
        appointment = self.appointments.appointments.get(workflow.appointment_id)
        encounter = self.encounters.get(workflow.encounter_id)
        if appointment is None or encounter is None:
            raise ClinicLifecycleError("CONSULTATION_CONTEXT_MISSING", "Consultation resources are unavailable")
        if appointment.patient_id != workflow.patient_id or encounter.patient_id != workflow.patient_id:
            raise ClinicLifecycleError("PATIENT_MISMATCH", "Consultation resources belong to another patient")
        return ConsultationContext(workflow, appointment, encounter)

    def _linked_encounter(self, workflow: WorkflowSession) -> Encounter | None:
        return self.encounters.get(workflow.encounter_id) if workflow.encounter_id else None
