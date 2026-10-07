from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Settings
from app.repositories.sqlite_repositories import SQLiteClinicRepository
from app.services.appointment_service import AppointmentRequest, AppointmentService
from app.services.audit_service import AuditService
from app.services.clinic_lifecycle_service import ClinicLifecycleService, ConsultationContext
from app.services.consent_service import ConsentService
from medflow.domain.enums import AppointmentStatus, ConsentType, EncounterStatus, WorkflowState
from medflow.domain.models import ConsentRecord, utc_now
from medflow.orchestration import ClinicWorkflowOrchestrator, WorkflowAction
from medflow.repositories.protocols import (
    EncounterRepository,
    PatientRepository,
    WorkflowRepository,
)
from security_guardrails import Actor
from security_guardrails.authz import is_patient_authorized


SYNTHETIC_PATIENT_PREFIX = "PT-DEMO-SYNTHETIC-"
DEVELOPMENT_CONSENT_VERSION = "CONSENT-V1"


class DevelopmentQuickStartError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class DevelopmentQuickStartResult:
    context: ConsultationContext
    consents: tuple[ConsentRecord, ...]
    cancelled_workflow_count: int


class DevelopmentQuickStartService:
    """Builds a valid synthetic visit context for local workspace testing."""

    def __init__(
        self,
        *,
        settings: Settings,
        patients: PatientRepository,
        workflows: WorkflowRepository,
        encounters: EncounterRepository,
        orchestrator: ClinicWorkflowOrchestrator,
        appointments: AppointmentService,
        lifecycle: ClinicLifecycleService,
        consents: ConsentService,
        clinic: SQLiteClinicRepository,
        audit: AuditService,
    ) -> None:
        self.settings = settings
        self.patients = patients
        self.workflows = workflows
        self.encounters = encounters
        self.orchestrator = orchestrator
        self.appointments = appointments
        self.lifecycle = lifecycle
        self.consents = consents
        self.clinic = clinic
        self.audit = audit

    def start(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        actor: Actor,
    ) -> DevelopmentQuickStartResult:
        self._require_allowed(patient_id=patient_id, practitioner_id=practitioner_id, actor=actor)
        prepared = self.prepare_for_consent(
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            actor=actor,
            reset_unfinished=True,
            require_synthetic_patient=True,
        )
        consent_records = self.consents.capture_bundle(
            encounter_id=prepared.context.encounter.encounter_id,
            decisions={
                ConsentType.AUDIO_RECORDING: True,
                ConsentType.AI_TRANSCRIPTION: True,
                ConsentType.AI_DOCUMENTATION: True,
                ConsentType.AUDIO_RETENTION: False,
            },
            consent_text_version=DEVELOPMENT_CONSENT_VERSION,
            capture_method="DEVELOPMENT_QUICK_START",
            actor=actor,
        )
        self.audit.record(
            "development_quick_start",
            actor_ref=actor.ref,
            action="prepare_synthetic_test_visit",
            patient_ref=patient_id,
            resource_ref=prepared.context.workflow.workflow_id,
            metadata={
                "cancelled_workflow_count": prepared.cancelled_workflow_count,
                "retention_enabled": False,
            },
        )
        return DevelopmentQuickStartResult(
            context=prepared.context,
            consents=tuple(consent_records),
            cancelled_workflow_count=prepared.cancelled_workflow_count,
        )

    def prepare_for_consent(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        actor: Actor,
        reset_unfinished: bool = False,
        require_synthetic_patient: bool = False,
    ) -> DevelopmentQuickStartResult:
        """Advance a visit to CONSULTATION_READY so only consent remains in the UI."""
        self._require_doctor(patient_id=patient_id, practitioner_id=practitioner_id, actor=actor)
        if require_synthetic_patient and not patient_id.startswith(SYNTHETIC_PATIENT_PREFIX):
            raise DevelopmentQuickStartError(
                "SYNTHETIC_PATIENT_REQUIRED",
                "Quick test visits are restricted to seeded synthetic patients",
            )
        if self.patients.get(patient_id) is None:
            raise DevelopmentQuickStartError("PATIENT_NOT_FOUND", "Patient was not found")

        profile = self.clinic.get_practitioner(practitioner_id)
        if profile is None or not bool(profile.get("active")):
            raise DevelopmentQuickStartError(
                "PRACTITIONER_NOT_FOUND",
                "The authenticated doctor has no active clinic profile",
            )

        cancelled_count = 0
        if reset_unfinished:
            cancelled_count = self._cancel_unfinished_visits(patient_id=patient_id, actor=actor)

        workflow = self.lifecycle.get_or_create_workflow(patient_id=patient_id, actor=actor)

        # A prior note leaves the visit in NOTE_REVIEW_* / APPROVED. Those states
        # are not recordable, so start a fresh consultation cycle.
        if workflow.state in {
            WorkflowState.DOCUMENTATION_PROCESSING,
            WorkflowState.NOTE_REVIEW_REQUIRED,
            WorkflowState.NOTE_APPROVED,
            WorkflowState.ENCOUNTER_COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }:
            cancelled_count += self._cancel_unfinished_visits(patient_id=patient_id, actor=actor)
            workflow = self.lifecycle.get_or_create_workflow(patient_id=patient_id, actor=actor)

        if (
            workflow.state in {WorkflowState.CONSULTATION_READY, WorkflowState.CONSULTATION_ACTIVE}
            and workflow.encounter_id
            and workflow.appointment_id
        ):
            context = ConsultationContext(
                workflow=workflow,
                appointment=self.appointments.appointments.get(workflow.appointment_id),
                encounter=self.encounters.get(workflow.encounter_id),
            )
            if context.appointment is None or context.encounter is None:
                raise DevelopmentQuickStartError(
                    "CONSULTATION_CONTEXT_MISSING",
                    "The existing consultation context is incomplete",
                )
            decisions = self.consents.latest_decisions(context.encounter.encounter_id, actor=actor)
            consents = tuple(record for record in decisions.values() if record is not None)
            return DevelopmentQuickStartResult(context, consents, cancelled_count)

        if workflow.state == WorkflowState.PATIENT_UNVERIFIED:
            workflow = self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.VERIFY_PATIENT,
                actor=actor,
                expected_version=workflow.version,
            )
        if workflow.state in {
            WorkflowState.PATIENT_VERIFIED,
            WorkflowState.INTAKE_IN_PROGRESS,
            WorkflowState.INTAKE_COMPLETED,
            WorkflowState.BOOKING_REQUIRED,
        }:
            workflow = self.lifecycle.complete_existing_intake(workflow.workflow_id, actor=actor)

        if workflow.state == WorkflowState.BOOKING_REQUIRED and not workflow.appointment_id:
            visit_type = self._visit_type()
            slot = self._first_available_slot(
                patient_id=patient_id,
                practitioner_id=practitioner_id,
                visit_type_id=str(visit_type["visit_type_id"]),
            )
            appointment = self.appointments.create(
                AppointmentRequest(
                    patient_id=patient_id,
                    practitioner_id=practitioner_id,
                    department_id=str(profile["department_id"]),
                    location_id=str(profile["location_id"]),
                    visit_type_id=str(visit_type["visit_type_id"]),
                    start_at=datetime.fromisoformat(slot["start_at"]),
                    idempotency_key=f"prepare-consultation-{workflow.workflow_id}",
                ),
                actor=actor,
            )
            workflow = self.lifecycle.confirm_booking(
                workflow.workflow_id,
                appointment=appointment,
                actor=actor,
            )

        if workflow.state == WorkflowState.BOOKING_CONFIRMED:
            context = self.lifecycle.check_in(workflow.workflow_id, actor=actor)
        elif workflow.state in {
            WorkflowState.PATIENT_CHECKED_IN,
            WorkflowState.CONSULTATION_READY,
            WorkflowState.CONSULTATION_ACTIVE,
        }:
            context = self.lifecycle.check_in(workflow.workflow_id, actor=actor)
        else:
            raise DevelopmentQuickStartError(
                "INVALID_WORKFLOW_STATE",
                f"Unable to prepare consultation from state {workflow.state.value}",
            )

        decisions = self.consents.latest_decisions(context.encounter.encounter_id, actor=actor)
        consents = tuple(record for record in decisions.values() if record is not None)
        self.audit.record(
            "consultation_prep",
            actor_ref=actor.ref,
            action="prepare_for_consent",
            patient_ref=patient_id,
            resource_ref=context.workflow.workflow_id,
            metadata={"cancelled_workflow_count": cancelled_count},
        )
        return DevelopmentQuickStartResult(
            context=context,
            consents=consents,
            cancelled_workflow_count=cancelled_count,
        )

    def _require_doctor(self, *, patient_id: str, practitioner_id: str, actor: Actor) -> None:
        if actor.role != "doctor" or not is_patient_authorized(actor, patient_id):
            raise DevelopmentQuickStartError(
                "FORBIDDEN",
                "Only an authorized doctor may prepare this consultation",
            )
        if not practitioner_id:
            raise DevelopmentQuickStartError(
                "PRACTITIONER_NOT_FOUND",
                "The authenticated doctor has no clinic profile",
            )

    def _require_allowed(self, *, patient_id: str, practitioner_id: str, actor: Actor) -> None:
        if not self.settings.development_quick_start_available:
            raise DevelopmentQuickStartError(
                "FEATURE_DISABLED",
                "Development quick start is unavailable",
            )
        self._require_doctor(patient_id=patient_id, practitioner_id=practitioner_id, actor=actor)
        if not patient_id.startswith(SYNTHETIC_PATIENT_PREFIX):
            raise DevelopmentQuickStartError(
                "SYNTHETIC_PATIENT_REQUIRED",
                "Quick test visits are restricted to seeded synthetic patients",
            )
        if self.patients.get(patient_id) is None:
            raise DevelopmentQuickStartError("PATIENT_NOT_FOUND", "Synthetic patient was not found")

    def _cancel_unfinished_visits(self, *, patient_id: str, actor: Actor) -> int:
        cancelled = 0
        for workflow in self.workflows.list(patient_id=patient_id):
            if workflow.state in {WorkflowState.ENCOUNTER_COMPLETED, WorkflowState.CANCELLED}:
                continue
            if workflow.appointment_id:
                appointment = self.appointments.appointments.get(workflow.appointment_id)
                if appointment and appointment.status not in {
                    AppointmentStatus.CANCELLED,
                    AppointmentStatus.COMPLETED,
                }:
                    self.appointments.cancel(
                        appointment.appointment_id,
                        reason_code="DEVELOPMENT_QUICK_START_RESET",
                        idempotency_key=f"development-quick-cancel-{workflow.workflow_id}",
                        actor=actor,
                    )
            if workflow.encounter_id:
                encounter = self.encounters.get(workflow.encounter_id)
                if encounter and encounter.status not in {
                    EncounterStatus.CANCELLED,
                    EncounterStatus.COMPLETED,
                }:
                    self.encounters.save(
                        encounter.model_copy(
                            update={
                                "status": EncounterStatus.CANCELLED,
                                "ended_at": encounter.ended_at or utc_now(),
                                "updated_at": utc_now(),
                            }
                        )
                    )
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.CANCEL,
                actor=actor,
                expected_version=workflow.version,
            )
            cancelled += 1
        return cancelled

    def _visit_type(self) -> dict:
        visit_types = self.clinic.list_visit_types()
        if not visit_types:
            raise DevelopmentQuickStartError(
                "VISIT_TYPE_NOT_FOUND",
                "No active clinic visit type is configured",
            )
        return next(
            (item for item in visit_types if item["visit_type_id"] == "VISIT-NEW"),
            visit_types[0],
        )

    def _first_available_slot(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        visit_type_id: str,
    ) -> dict[str, str]:
        clinic = self.clinic.get_clinic()
        if clinic is None:
            raise DevelopmentQuickStartError("CLINIC_NOT_FOUND", "Clinic configuration was not found")
        timezone = ZoneInfo(str(clinic["timezone"]))
        slots = self.appointments.availability(
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            visit_type_id=visit_type_id,
            start_date=datetime.now(timezone).date(),
            days=max(1, int(clinic["booking_horizon_days"])),
        )
        if not slots:
            raise DevelopmentQuickStartError(
                "NO_AVAILABLE_SLOT",
                "No valid clinic slot is available for the synthetic test visit",
            )
        return slots[0]
