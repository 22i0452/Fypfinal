from __future__ import annotations

from dataclasses import dataclass
import threading
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.appointment_service import AppointmentError, AppointmentRequest, AppointmentService
from app.services.audit_service import AuditService
from app.repositories.receptionist_sessions import ReceptionistSessionRepository
from app.services.clinic_lifecycle_service import ClinicLifecycleService
from medflow.domain.enums import AppointmentStatus, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import Appointment, Patient, utc_now
from medflow.intake_validation import (
    is_meaningful_text,
    normalize_age,
    normalize_first_visit,
    normalize_name,
    normalize_phone,
)
from medflow.orchestration import WorkflowResourceLinks
from medflow.repositories.protocols import PatientRepository, WorkflowRepository
from security_guardrails import Actor
from security_guardrails.authz import is_patient_authorized


class ReceptionistIntegrationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ReceptionistIntake:
    name: str
    age_text: str
    phone_number: str
    first_visit: str
    past_medical_history: str
    current_complaint: str
    intake_token: str
    revision: int
    confirmed_revision: int


@dataclass(frozen=True)
class ReceptionistBooking:
    patient_id: str
    workflow_id: str
    department_id: str
    practitioner_id: str
    visit_type_id: str
    start_at: datetime
    idempotency_key: str
    intake_token: str
    revision: int


class ReceptionistIntegrationService:
    """Narrow orchestration surface for the external receptionist application."""

    def __init__(
        self,
        *,
        patients: PatientRepository,
        workflows: WorkflowRepository,
        appointments: AppointmentService,
        lifecycle: ClinicLifecycleService,
        clinic,
        auth,
        audit: AuditService,
    ) -> None:
        self.patients = patients
        self.workflows = workflows
        self.appointments = appointments
        self.lifecycle = lifecycle
        self.clinic = clinic
        self.auth = auth
        self.audit = audit
        self.sessions = ReceptionistSessionRepository(clinic.database)
        self._intake_lock = threading.RLock()

    def configuration(self) -> dict:
        clinic = self.clinic.get_clinic()
        if not clinic:
            raise ReceptionistIntegrationError(
                "CLINIC_NOT_FOUND",
                "Clinic scheduling configuration is unavailable",
            )
        practitioners = self._bookable_practitioners()
        department_ids = {str(item["department_id"]) for item in practitioners}
        location_ids = {str(item["location_id"]) for item in practitioners}
        timezone = ZoneInfo(str(clinic["timezone"]))
        return {
            "clinic": {
                "clinic_id": clinic["clinic_id"],
                "name": clinic["name"],
                "timezone": clinic["timezone"],
                "slot_duration_minutes": clinic["slot_duration_minutes"],
                "booking_horizon_days": clinic["booking_horizon_days"],
                "minimum_advance_booking_minutes": clinic["minimum_advance_booking_minutes"],
                "current_time": datetime.now(timezone).isoformat(),
            },
            "departments": [
                item for item in self.clinic.list_departments()
                if str(item["department_id"]) in department_ids
            ],
            "locations": [
                {
                    "location_id": item["location_id"],
                    "name": item["name"],
                }
                for item in self.clinic.list_locations()
                if str(item["location_id"]) in location_ids
            ],
            "practitioners": [
                {
                    "practitioner_id": item["practitioner_id"],
                    "display_name": item["display_name"],
                    "department_id": item["department_id"],
                    "location_id": item["location_id"],
                }
                for item in practitioners
            ],
            "visit_types": self.clinic.list_visit_types(),
            "working_hours": {
                day: [
                    {"start": start, "end": end}
                    for start, end in self.clinic.working_intervals(str(clinic["clinic_id"]), day)
                ]
                for day in (
                    "MONDAY",
                    "TUESDAY",
                    "WEDNESDAY",
                    "THURSDAY",
                    "FRIDAY",
                    "SATURDAY",
                    "SUNDAY",
                )
            },
        }

    def availability(
        self,
        *,
        practitioner_id: str,
        visit_type_id: str,
        start_date: date | None = None,
        days: int = 14,
        limit: int = 12,
    ) -> dict:
        practitioner = next(
            (
                item
                for item in self._bookable_practitioners()
                if str(item["practitioner_id"]) == practitioner_id
            ),
            None,
        )
        if practitioner is None:
            raise ReceptionistIntegrationError(
                "PRACTITIONER_UNAVAILABLE",
                "Selected doctor is unavailable for receptionist booking",
            )
        self._validate_visit_type(visit_type_id)
        clinic = self.clinic.get_clinic()
        if not clinic:
            raise ReceptionistIntegrationError("CLINIC_NOT_FOUND", "Clinic is unavailable")
        timezone = ZoneInfo(str(clinic["timezone"]))
        requested_date = start_date or datetime.now(timezone).date()
        slots = self.appointments.availability(
            patient_id="RECEPTIONIST-SCHEDULE-PREVIEW",
            practitioner_id=practitioner_id,
            visit_type_id=visit_type_id,
            start_date=requested_date,
            days=max(1, min(days, 30)),
        )
        enriched = []
        for slot in slots[: max(1, min(limit, 30))]:
            start = datetime.fromisoformat(str(slot["start_at"])).astimezone(timezone)
            enriched.append(
                {
                    **slot,
                    "practitioner_name": str(practitioner["display_name"]),
                    "label": start.strftime("%A, %d %B %Y at %I:%M %p"),
                }
            )
        return {
            "practitioner_id": practitioner_id,
            "practitioner_name": str(practitioner["display_name"]),
            "visit_type_id": visit_type_id,
            "timezone": str(clinic["timezone"]),
            "slots": enriched,
        }

    def create_intake(self, intake: ReceptionistIntake) -> dict:
        with self._intake_lock:
            self._validate_confirmation(intake)
            existing = self.sessions.get(intake.intake_token)
            if existing:
                patient = self.patients.get(existing["patient_id"])
                data = self._validated_intake(intake)
                requires_update = patient is None or existing["revision"] != intake.revision or any(
                    getattr(patient, key) != value for key, value in data.items()
                )
                return {**self._intake_result(existing), "requires_update": requires_update}
            result = self._create_intake(intake)
            self.sessions.save(
                token=intake.intake_token, patient_id=result["patient_id"],
                workflow_id=result["workflow_id"], revision=intake.revision,
            )
            return {**result, "revision": intake.revision}

    @staticmethod
    def _validate_confirmation(intake: ReceptionistIntake) -> None:
        if len(intake.intake_token) < 32 or intake.revision < 1 or intake.confirmed_revision != intake.revision:
            raise ReceptionistIntegrationError("INTAKE_UNCONFIRMED", "The current intake revision must be confirmed")

    def _intake_result(self, session: dict) -> dict:
        workflow = self.workflows.get(session["workflow_id"])
        return {
            "patient_id": session["patient_id"], "workflow_id": session["workflow_id"],
            "workflow_state": workflow.state.value if workflow else "",
            "revision": session["revision"], "verification_required_at_doctor": True,
        }

    def _session(self, token: str, patient_id: str, workflow_id: str) -> dict:
        session = self.sessions.get(token)
        if not session or session["patient_id"] != patient_id or session["workflow_id"] != workflow_id:
            self.audit.record("authorization_denial", actor_ref="service:receptionist", action="update_intake", result="deny")
            raise ReceptionistIntegrationError("FORBIDDEN", "Intake access denied")
        return session

    def update_intake(self, *, patient_id: str, workflow_id: str, expected_revision: int, intake: ReceptionistIntake) -> dict:
        with self._intake_lock:
            self._validate_confirmation(intake)
            session = self._session(intake.intake_token, patient_id, workflow_id)
            workflow = self.workflows.get(workflow_id)
            if not workflow or workflow.appointment_id or workflow.state != WorkflowState.PATIENT_UNVERIFIED:
                raise ReceptionistIntegrationError("BOOKING_ALREADY_FORWARDED", "Ask the authorized doctor to update this record")
            data = self._validated_intake(intake)
            patient = self.patients.get(patient_id)
            if patient is None:
                raise ReceptionistIntegrationError("PATIENT_NOT_FOUND", "Patient not found")
            if session["revision"] == intake.revision and all(getattr(patient, key) == value for key, value in data.items()):
                return self._intake_result(session)
            if session["revision"] != expected_revision or intake.revision <= expected_revision:
                raise ReceptionistIntegrationError("INTAKE_CONFLICT", "The intake revision has changed")
            updated = patient.model_copy(update={**data, "updated_at": utc_now()})
            self.patients.save(updated)
            if not self.sessions.advance(token=intake.intake_token, revision=intake.revision, expected_revision=expected_revision):
                raise ReceptionistIntegrationError("INTAKE_CONFLICT", "The intake revision has changed")
            self.audit.record("receptionist_intake_corrected", actor_ref="service:receptionist", action="update_intake", patient_ref=patient_id, resource_ref=workflow_id)
            return self._intake_result({**session, "revision": intake.revision})

    def _validated_intake(self, intake: ReceptionistIntake) -> dict:
        name = normalize_name(intake.name)
        if not name:
            raise ReceptionistIntegrationError("INVALID_NAME", "A valid patient name is required")
        age_text = normalize_age(intake.age_text)
        if not age_text:
            raise ReceptionistIntegrationError(
                "INVALID_AGE",
                "Patient age must be a number from 1 to 120",
            )
        phone_number = self._normalize_phone_number(intake.phone_number)
        first_visit = normalize_first_visit(intake.first_visit)
        if not first_visit:
            raise ReceptionistIntegrationError(
                "INVALID_FIRST_VISIT",
                "First-visit status must be yes or no",
            )
        if not is_meaningful_text(intake.past_medical_history):
            raise ReceptionistIntegrationError(
                "INVALID_MEDICAL_HISTORY",
                "Medical history must be provided, or explicitly recorded as none",
            )
        if not is_meaningful_text(intake.current_complaint):
            raise ReceptionistIntegrationError(
                "INVALID_COMPLAINT",
                "A valid current complaint is required",
            )
        return {
            "name": name, "age_text": age_text, "phone_number": phone_number,
            "first_visit": first_visit, "past_medical_history": intake.past_medical_history,
            "current_complaint": intake.current_complaint,
        }

    def correct_forwarded_intake(self, *, patient_id: str, actor: Actor, expected_updated_at: datetime, changes: dict[str, str]) -> Patient:
        with self._intake_lock:
            if actor.role != "doctor" or not is_patient_authorized(actor, patient_id):
                self.audit.record("authorization_denial", actor_ref=actor.ref, action="correct_intake", result="deny")
                raise ReceptionistIntegrationError("FORBIDDEN", "Doctor access to this patient is required")
            allowed = {"name", "age_text", "phone_number", "first_visit", "past_medical_history", "current_complaint"}
            if not changes or not set(changes) <= allowed:
                raise ReceptionistIntegrationError("INVALID_FIELDS", "Only intake fields may be corrected")
            patient = self.patients.get(patient_id)
            if patient is None:
                raise ReceptionistIntegrationError("PATIENT_NOT_FOUND", "Patient not found")
            if patient.updated_at != expected_updated_at:
                raise ReceptionistIntegrationError("INTAKE_CONFLICT", "Reload the current patient record")
            workflows = self.workflows.list(patient_id=patient_id)
            if any(workflow.encounter_id for workflow in workflows):
                raise ReceptionistIntegrationError("INTAKE_LOCKED", "An encounter has started; use clinical documentation review for amendments")
            if "phone_number" in changes and normalize_phone(changes["phone_number"]) != patient.phone_number:
                with self.clinic.database.connection() as connection:
                    challenge = connection.execute(
                        "SELECT 1 FROM verification_challenges WHERE patient_id = ? LIMIT 1", (patient_id,),
                    ).fetchone()
                if challenge:
                    raise ReceptionistIntegrationError("PHONE_VERIFICATION_STARTED", "Phone verification has started; changing this number requires a new verification workflow")
            values = {key: getattr(patient, key) for key in allowed}
            data = self._validated_intake(ReceptionistIntake(
                **{**values, **changes}, intake_token="", revision=1, confirmed_revision=1,
            ))
            updated = self.patients.save(patient.model_copy(update={**data, "updated_at": utc_now()}))
            self.audit.record("doctor_intake_corrected", actor_ref=actor.ref, action="correct_intake", patient_ref=patient_id)
            return updated

    def _create_intake(self, intake: ReceptionistIntake) -> dict:
        data = self._validated_intake(intake)
        now = utc_now()
        patient = self.patients.save(
            Patient(
                patient_id=new_id("PT"),
                **data,
                recorded_at=now.isoformat(),
                created_at=now,
                updated_at=now,
            )
        )
        actor = self._actor(patient.patient_id)
        workflow = self.lifecycle.get_or_create_workflow(
            patient_id=patient.patient_id,
            actor=actor,
        )
        self.audit.record(
            "receptionist_intake_created",
            actor_ref=actor.ref,
            action="create_intake",
            patient_ref=patient.patient_id,
            resource_ref=workflow.workflow_id,
            metadata={"workflow_state": workflow.state.value},
        )
        return {
            "patient_id": patient.patient_id,
            "workflow_id": workflow.workflow_id,
            "workflow_state": workflow.state.value,
            "verification_required_at_doctor": True,
        }

    def book(self, booking: ReceptionistBooking) -> dict:
        with self._intake_lock:
            session = self._session(booking.intake_token, booking.patient_id, booking.workflow_id)
            if session["revision"] != booking.revision:
                raise ReceptionistIntegrationError("INTAKE_CONFLICT", "Confirm and save the current intake before booking")
            return self._book(booking)

    def _book(self, booking: ReceptionistBooking) -> dict:
        actor = self._actor(booking.patient_id)
        workflow = self.lifecycle.orchestrator.get_session(
            booking.workflow_id,
            actor=actor,
        )
        if workflow.patient_id != booking.patient_id:
            raise ReceptionistIntegrationError(
                "WORKFLOW_MISMATCH",
                "Booking workflow belongs to another patient",
            )
        if workflow.appointment_id:
            appointment = self.appointments.appointments.get(workflow.appointment_id)
            if appointment is None:
                raise ReceptionistIntegrationError(
                    "APPOINTMENT_NOT_FOUND",
                    "Workflow appointment is unavailable",
                )
            requested_start = self._local_start(booking.start_at)
            if (
                appointment.patient_id != booking.patient_id
                or appointment.department_id != booking.department_id
                or appointment.visit_type_id != booking.visit_type_id
                or appointment.start_at != requested_start
                or (
                    booking.practitioner_id
                    and appointment.practitioner_id != booking.practitioner_id
                )
            ):
                raise ReceptionistIntegrationError(
                    "BOOKING_ALREADY_FORWARDED",
                    "This workflow is already linked to a different appointment",
                )
            self.auth.assign_patient(appointment.practitioner_id, booking.patient_id)
            return self._booked_result(appointment, workflow)
        if workflow.state not in {
            WorkflowState.PATIENT_UNVERIFIED,
            WorkflowState.BOOKING_REQUIRED,
        }:
            raise ReceptionistIntegrationError(
                "INVALID_WORKFLOW_STATE",
                "The intake cannot be forwarded for booking from its current state",
            )

        candidates = self._booking_candidates(
            department_id=booking.department_id,
            practitioner_id=booking.practitioner_id,
        )
        self._validate_visit_type(booking.visit_type_id)
        local_start = self._local_start(booking.start_at)
        existing = self.appointments.appointments.get_by_idempotency_key(
            booking.idempotency_key
        )
        if existing is not None:
            expected = (
                existing.patient_id == booking.patient_id
                and existing.department_id == booking.department_id
                and existing.visit_type_id == booking.visit_type_id
                and existing.start_at == local_start
                and (
                    not booking.practitioner_id
                    or existing.practitioner_id == booking.practitioner_id
                )
            )
            if not expected:
                raise ReceptionistIntegrationError(
                    "IDEMPOTENCY_CONFLICT",
                    "Booking idempotency key was used for another request",
                )
            workflow = self._link_or_confirm_booking(
                workflow=workflow,
                appointment=existing,
                actor=actor,
            )
            self.auth.assign_patient(existing.practitioner_id, booking.patient_id)
            return self._booked_result(existing, workflow)

        selected = self._available_candidate(
            patient_id=booking.patient_id,
            practitioners=candidates,
            visit_type_id=booking.visit_type_id,
            start_at=local_start,
        )
        if selected is None:
            return self._alternatives_result(
                booking=booking,
                practitioners=candidates,
                start_at=local_start,
            )

        try:
            appointment = self.appointments.create(
                AppointmentRequest(
                    patient_id=booking.patient_id,
                    practitioner_id=str(selected["practitioner_id"]),
                    department_id=str(selected["department_id"]),
                    location_id=str(selected["location_id"]),
                    visit_type_id=booking.visit_type_id,
                    start_at=local_start,
                    idempotency_key=booking.idempotency_key,
                    status=(
                        AppointmentStatus.REQUESTED
                        if workflow.state == WorkflowState.PATIENT_UNVERIFIED
                        else AppointmentStatus.CONFIRMED
                    ),
                ),
                actor=actor,
            )
        except AppointmentError as exc:
            if exc.code != "SLOT_CONFLICT":
                raise
            return self._alternatives_result(
                booking=booking,
                practitioners=candidates,
                start_at=local_start,
            )
        workflow = self._link_or_confirm_booking(
            workflow=workflow,
            appointment=appointment,
            actor=actor,
        )
        self.auth.assign_patient(appointment.practitioner_id, booking.patient_id)
        self.audit.record(
            "receptionist_booking_forwarded",
            actor_ref=actor.ref,
            action="forward_booking",
            patient_ref=booking.patient_id,
            resource_ref=appointment.appointment_id,
            metadata={
                "appointment_status": appointment.status.value,
                "practitioner_id": appointment.practitioner_id,
            },
        )
        return self._booked_result(appointment, workflow)

    def _alternatives_result(
        self,
        *,
        booking: ReceptionistBooking,
        practitioners: list[dict],
        start_at: datetime,
    ) -> dict:
        alternatives = self._alternatives(
            patient_id=booking.patient_id,
            practitioners=practitioners,
            visit_type_id=booking.visit_type_id,
            requested_start=start_at,
        )
        workflow = self.workflows.get(booking.workflow_id)
        return {
            "status": "ALTERNATIVES_REQUIRED",
            "patient_id": booking.patient_id,
            "workflow_id": booking.workflow_id,
            "workflow_state": workflow.state.value if workflow else "",
            "alternatives": alternatives,
        }

    def _link_or_confirm_booking(self, *, workflow, appointment: Appointment, actor: Actor):
        if workflow.patient_id != appointment.patient_id:
            raise ReceptionistIntegrationError(
                "WORKFLOW_MISMATCH",
                "Booking workflow belongs to another patient",
            )
        if workflow.state == WorkflowState.PATIENT_UNVERIFIED:
            if appointment.status != AppointmentStatus.REQUESTED:
                raise ReceptionistIntegrationError(
                    "INVALID_APPOINTMENT_STATUS",
                    "An unverified patient requires a pending appointment",
                )
            return self.lifecycle.orchestrator.link_resources(
                workflow.workflow_id,
                actor=actor,
                links=WorkflowResourceLinks(
                    appointment_id=appointment.appointment_id,
                    assigned_practitioner_id=appointment.practitioner_id,
                ),
                expected_version=workflow.version,
            )
        if appointment.status == AppointmentStatus.REQUESTED:
            appointment = self.appointments.confirm_requested(
                appointment.appointment_id,
                actor=actor,
            )
        return self.lifecycle.confirm_booking(
            workflow.workflow_id,
            appointment=appointment,
            actor=actor,
        )

    def _alternatives(
        self,
        *,
        patient_id: str,
        practitioners: list[dict],
        visit_type_id: str,
        requested_start: datetime,
    ) -> list[dict]:
        collected: list[tuple[datetime, dict, dict]] = []
        for practitioner in practitioners:
            slots = self.appointments.availability(
                patient_id=patient_id,
                practitioner_id=str(practitioner["practitioner_id"]),
                visit_type_id=visit_type_id,
                start_date=requested_start.date(),
                days=14,
            )
            for slot in slots:
                start = datetime.fromisoformat(str(slot["start_at"]))
                if start > requested_start:
                    collected.append((start, practitioner, slot))
        collected.sort(key=lambda item: (item[0], str(item[1]["display_name"])))
        alternatives: list[dict] = []
        seen_starts: set[str] = set()
        for start, practitioner, slot in collected:
            start_key = start.isoformat()
            if start_key in seen_starts:
                continue
            seen_starts.add(start_key)
            alternatives.append(
                {
                    "start_at": start_key,
                    "end_at": slot["end_at"],
                    "practitioner_id": practitioner["practitioner_id"],
                    "practitioner_name": practitioner["display_name"],
                    "department_id": practitioner["department_id"],
                    "location_id": practitioner["location_id"],
                    "visit_type_id": visit_type_id,
                }
            )
            if len(alternatives) == 3:
                break
        return alternatives

    def _available_candidate(
        self,
        *,
        patient_id: str,
        practitioners: list[dict],
        visit_type_id: str,
        start_at: datetime,
    ) -> dict | None:
        for practitioner in practitioners:
            slots = self.appointments.availability(
                patient_id=patient_id,
                practitioner_id=str(practitioner["practitioner_id"]),
                visit_type_id=visit_type_id,
                start_date=start_at.date(),
                days=1,
            )
            if any(datetime.fromisoformat(str(slot["start_at"])) == start_at for slot in slots):
                return practitioner
        return None

    def _booking_candidates(self, *, department_id: str, practitioner_id: str) -> list[dict]:
        practitioners = self._bookable_practitioners()
        department_ids = {str(item["department_id"]) for item in self.clinic.list_departments()}
        if department_id not in department_ids:
            raise ReceptionistIntegrationError(
                "DEPARTMENT_NOT_FOUND",
                "Selected department is unavailable",
            )
        if practitioner_id:
            matches = [
                item for item in practitioners
                if str(item["practitioner_id"]) == practitioner_id
            ]
            if not matches:
                raise ReceptionistIntegrationError(
                    "PRACTITIONER_UNAVAILABLE",
                    "Selected doctor is unavailable for receptionist booking",
                )
            if str(matches[0]["department_id"]) != department_id:
                raise ReceptionistIntegrationError(
                    "PROFILE_MISMATCH",
                    "Selected doctor does not belong to the selected department",
                )
            return matches
        matches = [
            item for item in practitioners
            if str(item["department_id"]) == department_id
        ]
        if not matches:
            raise ReceptionistIntegrationError(
                "PRACTITIONER_UNAVAILABLE",
                "No doctor with an active dashboard account is available in this department",
            )
        return matches

    def _bookable_practitioners(self) -> list[dict]:
        # Prefer the primary authorized doctor at the top of booking lists.
        return sorted(
            [
                item for item in self.clinic.list_practitioners()
                if item.get("doctor_user_id") is not None
            ],
            key=lambda item: (
                0 if "shahzaib" in str(item.get("display_name") or "").lower() else 1,
                str(item["display_name"]),
                str(item["practitioner_id"]),
            ),
        )

    def _validate_visit_type(self, visit_type_id: str) -> None:
        if self.clinic.get_visit_type(visit_type_id) is None:
            raise ReceptionistIntegrationError(
                "VISIT_TYPE_NOT_FOUND",
                "Selected visit type is unavailable",
            )

    def _local_start(self, start_at: datetime) -> datetime:
        clinic = self.clinic.get_clinic()
        if not clinic:
            raise ReceptionistIntegrationError("CLINIC_NOT_FOUND", "Clinic is unavailable")
        timezone = ZoneInfo(str(clinic["timezone"]))
        if start_at.tzinfo is None:
            return start_at.replace(tzinfo=timezone)
        return start_at.astimezone(timezone)

    @staticmethod
    def _normalize_phone_number(value: str) -> str:
        normalized = normalize_phone(value)
        if not normalized:
            raise ReceptionistIntegrationError(
                "PHONE_UNAVAILABLE",
                "A valid patient phone number is required",
            )
        return normalized

    @staticmethod
    def _actor(patient_id: str) -> Actor:
        return Actor(
            actor_id="receptionist-service",
            role="receptionist",
            authorized_patient_ids={patient_id},
            current_patient_id=patient_id,
        )

    def _booked_result(self, appointment: Appointment, workflow) -> dict:
        practitioner = self.clinic.get_practitioner(appointment.practitioner_id) or {}
        visit_type = self.clinic.get_visit_type(appointment.visit_type_id) or {}
        return {
            "status": (
                "REQUESTED"
                if appointment.status == AppointmentStatus.REQUESTED
                else "BOOKED"
            ),
            "patient_id": appointment.patient_id,
            "workflow_id": workflow.workflow_id,
            "workflow_state": workflow.state.value,
            "appointment": {
                **appointment.model_dump(mode="json"),
                "practitioner_name": practitioner.get("display_name", ""),
                "visit_type_name": visit_type.get("name", ""),
            },
            "alternatives": [],
        }
