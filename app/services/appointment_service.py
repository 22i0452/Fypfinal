from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.repositories.sqlite_repositories import SQLiteAppointmentRepository, SQLiteClinicRepository
from app.services.audit_service import AuditService
from medflow.domain.enums import AppointmentStatus
from medflow.domain.ids import new_id
from medflow.domain.models import Appointment, utc_now
from medflow.repositories.json_repositories import RepositoryConflictError
from security_guardrails import Actor
from security_guardrails.authz import is_patient_authorized


class AppointmentError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class AppointmentRequest:
    patient_id: str
    practitioner_id: str
    department_id: str
    location_id: str
    visit_type_id: str
    start_at: datetime
    idempotency_key: str
    status: AppointmentStatus = AppointmentStatus.CONFIRMED


class AppointmentService:
    def __init__(
        self,
        *,
        appointments: SQLiteAppointmentRepository,
        clinic: SQLiteClinicRepository,
        audit: AuditService,
        clinic_id: str = "CLINIC-DEMO-001",
    ) -> None:
        self.appointments = appointments
        self.clinic = clinic
        self.audit = audit
        self.clinic_id = clinic_id

    def availability(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        visit_type_id: str,
        start_date: date,
        days: int = 7,
        now: datetime | None = None,
    ) -> list[dict[str, str]]:
        config, practitioner, visit_type, timezone = self._configuration(practitioner_id, visit_type_id)
        current = self._localize(now or datetime.now(timezone), timezone)
        horizon_end = current + timedelta(days=int(config["booking_horizon_days"]))
        requested_end = min(start_date + timedelta(days=max(1, days)), horizon_end.date() + timedelta(days=1))
        slots: list[dict[str, str]] = []
        day = start_date
        while day < requested_end:
            weekday = day.strftime("%A").upper()
            for start_text, end_text in self.clinic.working_intervals(self.clinic_id, weekday):
                interval_start = datetime.combine(day, time.fromisoformat(start_text), tzinfo=timezone)
                interval_end = datetime.combine(day, time.fromisoformat(end_text), tzinfo=timezone)
                candidate = interval_start
                duration = timedelta(minutes=int(visit_type["duration_minutes"]))
                step = timedelta(minutes=int(config["slot_duration_minutes"]))
                while candidate + duration <= interval_end:
                    if self._slot_is_available(
                        patient_id=patient_id,
                        practitioner_id=practitioner_id,
                        start_at=candidate,
                        end_at=candidate + duration,
                        current=current,
                        horizon_end=horizon_end,
                        minimum_advance_minutes=int(config["minimum_advance_booking_minutes"]),
                    ):
                        slots.append(
                            {
                                "start_at": candidate.isoformat(),
                                "end_at": (candidate + duration).isoformat(),
                                "practitioner_id": practitioner["practitioner_id"],
                                "visit_type_id": visit_type["visit_type_id"],
                            }
                        )
                    candidate += step
            day += timedelta(days=1)
        return slots

    def get(self, appointment_id: str, *, actor: Actor) -> Appointment:
        appointment = self._get(appointment_id)
        self._require_manage(actor, appointment.patient_id)
        return appointment

    def create(self, request: AppointmentRequest, *, actor: Actor, now: datetime | None = None) -> Appointment:
        self._require_manage(actor, request.patient_id)
        config, practitioner, visit_type, timezone = self._configuration(
            request.practitioner_id, request.visit_type_id
        )
        self._validate_profile_selection(practitioner, request.department_id, request.location_id)
        start_at = self._localize(request.start_at, timezone)
        end_at = start_at + timedelta(minutes=int(visit_type["duration_minutes"]))
        request_payload = {
            "patient_id": request.patient_id,
            "practitioner_id": request.practitioner_id,
            "department_id": request.department_id,
            "location_id": request.location_id,
            "visit_type_id": request.visit_type_id,
            "start_at": start_at.isoformat(),
        }
        if request.status != AppointmentStatus.CONFIRMED:
            request_payload["status"] = request.status.value
        request_hash = self._hash_request("CREATE", request_payload)
        existing_operation = self.appointments.get_operation(request.idempotency_key)
        if existing_operation:
            if existing_operation["operation"] != "CREATE" or existing_operation["request_hash"] != request_hash:
                raise AppointmentError("IDEMPOTENCY_CONFLICT", "Idempotency key was used for another request")
            existing = self.appointments.get(existing_operation["appointment_id"])
            if existing:
                return existing
        current = self._localize(now or datetime.now(timezone), timezone)
        self._validate_slot(
            patient_id=request.patient_id,
            practitioner_id=request.practitioner_id,
            start_at=start_at,
            end_at=end_at,
            current=current,
            config=config,
        )
        created_at = utc_now()
        appointment = Appointment(
            appointment_id=new_id("APT"),
            patient_id=request.patient_id,
            practitioner_id=request.practitioner_id,
            department_id=request.department_id,
            location_id=request.location_id,
            visit_type_id=request.visit_type_id,
            start_at=start_at,
            end_at=end_at,
            status=request.status,
            idempotency_key=request.idempotency_key,
            created_at=created_at,
            updated_at=created_at,
        )
        try:
            saved = self.appointments.create_atomic(appointment, request_hash=request_hash)
        except RepositoryConflictError as exc:
            raise AppointmentError("SLOT_CONFLICT", str(exc)) from exc
        self.audit.record(
            "appointment_created",
            actor_ref=actor.ref,
            action="create_appointment",
            patient_ref=request.patient_id,
            resource_ref=saved.appointment_id,
            metadata={"status": saved.status.value, "practitioner_id": saved.practitioner_id},
        )
        return saved

    def reschedule(
        self,
        appointment_id: str,
        *,
        new_start_at: datetime,
        idempotency_key: str,
        actor: Actor,
        now: datetime | None = None,
    ) -> Appointment:
        current_appointment = self._get(appointment_id)
        self._require_manage(actor, current_appointment.patient_id)
        if current_appointment.status not in {AppointmentStatus.REQUESTED, AppointmentStatus.CONFIRMED}:
            raise AppointmentError("INVALID_STATUS", "Only requested or confirmed appointments can be rescheduled")
        config, _, visit_type, timezone = self._configuration(
            current_appointment.practitioner_id, current_appointment.visit_type_id
        )
        start_at = self._localize(new_start_at, timezone)
        end_at = start_at + timedelta(minutes=int(visit_type["duration_minutes"]))
        current = self._localize(now or datetime.now(timezone), timezone)
        self._validate_slot(
            patient_id=current_appointment.patient_id,
            practitioner_id=current_appointment.practitioner_id,
            start_at=start_at,
            end_at=end_at,
            current=current,
            config=config,
            exclude_appointment_id=current_appointment.appointment_id,
        )
        request_hash = self._hash_request(
            "RESCHEDULE",
            {"appointment_id": appointment_id, "start_at": start_at.isoformat()},
        )
        updated = current_appointment.model_copy(
            update={
                "start_at": start_at,
                "end_at": end_at,
                "version": current_appointment.version + 1,
                "updated_at": utc_now(),
            }
        )
        try:
            saved = self.appointments.update_atomic(
                updated,
                operation="RESCHEDULE",
                operation_idempotency_key=idempotency_key,
                request_hash=request_hash,
                previous_version=current_appointment.version,
                check_overlap=True,
            )
        except RepositoryConflictError as exc:
            raise AppointmentError("SLOT_CONFLICT", str(exc)) from exc
        self.audit.record(
            "appointment_rescheduled",
            actor_ref=actor.ref,
            action="reschedule_appointment",
            patient_ref=saved.patient_id,
            resource_ref=saved.appointment_id,
            metadata={"version": saved.version},
        )
        return saved

    def cancel(
        self,
        appointment_id: str,
        *,
        reason_code: str,
        idempotency_key: str,
        actor: Actor,
    ) -> Appointment:
        current = self._get(appointment_id)
        self._require_manage(actor, current.patient_id)
        if current.status == AppointmentStatus.CANCELLED:
            return current
        if current.status == AppointmentStatus.COMPLETED:
            raise AppointmentError("INVALID_STATUS", "A completed appointment cannot be cancelled")
        request_hash = self._hash_request(
            "CANCEL", {"appointment_id": appointment_id, "reason_code": reason_code}
        )
        updated = current.model_copy(
            update={
                "status": AppointmentStatus.CANCELLED,
                "cancellation_reason": str(reason_code or "CANCELLED_BY_USER")[:80],
                "version": current.version + 1,
                "updated_at": utc_now(),
            }
        )
        try:
            saved = self.appointments.update_atomic(
                updated,
                operation="CANCEL",
                operation_idempotency_key=idempotency_key,
                request_hash=request_hash,
                previous_version=current.version,
                check_overlap=False,
            )
        except RepositoryConflictError as exc:
            raise AppointmentError("APPOINTMENT_CONFLICT", str(exc)) from exc
        self.audit.record(
            "appointment_cancelled",
            actor_ref=actor.ref,
            action="cancel_appointment",
            patient_ref=saved.patient_id,
            resource_ref=saved.appointment_id,
            metadata={"reason_code": saved.cancellation_reason},
        )
        return saved

    def check_in(self, appointment_id: str, *, actor: Actor) -> Appointment:
        return self._simple_status_change(
            appointment_id,
            actor=actor,
            expected={AppointmentStatus.CONFIRMED},
            target=AppointmentStatus.CHECKED_IN,
            event_type="appointment_checked_in",
        )

    def confirm_requested(self, appointment_id: str, *, actor: Actor) -> Appointment:
        current = self._get(appointment_id)
        self._require_manage(actor, current.patient_id)
        if current.status == AppointmentStatus.CONFIRMED:
            return current
        return self._simple_status_change(
            appointment_id,
            actor=actor,
            expected={AppointmentStatus.REQUESTED},
            target=AppointmentStatus.CONFIRMED,
            event_type="appointment_confirmed",
        )

    def start(self, appointment_id: str, *, actor: Actor) -> Appointment:
        return self._simple_status_change(
            appointment_id,
            actor=actor,
            expected={AppointmentStatus.CHECKED_IN},
            target=AppointmentStatus.IN_PROGRESS,
            event_type="appointment_started",
        )

    def complete(self, appointment_id: str, *, actor: Actor) -> Appointment:
        return self._simple_status_change(
            appointment_id,
            actor=actor,
            expected={AppointmentStatus.IN_PROGRESS},
            target=AppointmentStatus.COMPLETED,
            event_type="appointment_completed",
        )

    def _simple_status_change(
        self,
        appointment_id: str,
        *,
        actor: Actor,
        expected: set[AppointmentStatus],
        target: AppointmentStatus,
        event_type: str,
    ) -> Appointment:
        current = self._get(appointment_id)
        self._require_manage(actor, current.patient_id)
        if current.status not in expected:
            raise AppointmentError("INVALID_STATUS", f"Appointment cannot move from {current.status.value}")
        updated = current.model_copy(
            update={"status": target, "version": current.version + 1, "updated_at": utc_now()}
        )
        saved = self.appointments.save(updated)
        self.audit.record(
            event_type,
            actor_ref=actor.ref,
            action=event_type,
            patient_ref=saved.patient_id,
            resource_ref=saved.appointment_id,
            metadata={"status": target.value},
        )
        return saved

    def _validate_slot(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        start_at: datetime,
        end_at: datetime,
        current: datetime,
        config: dict,
        exclude_appointment_id: str | None = None,
    ) -> None:
        horizon_end = current + timedelta(days=int(config["booking_horizon_days"]))
        minimum = current + timedelta(minutes=int(config["minimum_advance_booking_minutes"]))
        if start_at < minimum:
            raise AppointmentError("MINIMUM_ADVANCE", "Appointment does not satisfy minimum advance time")
        if start_at > horizon_end:
            raise AppointmentError("BOOKING_HORIZON", "Appointment is outside the booking horizon")
        intervals = self.clinic.working_intervals(self.clinic_id, start_at.strftime("%A").upper())
        inside_hours = any(
            start_at.time() >= time.fromisoformat(begin) and end_at.time() <= time.fromisoformat(end)
            for begin, end in intervals
        )
        if not inside_hours:
            raise AppointmentError("OUTSIDE_WORKING_HOURS", "Appointment is outside clinic working hours")
        if self.clinic.practitioner_is_blocked(practitioner_id, start_at, end_at):
            raise AppointmentError("PRACTITIONER_BLOCKED", "Practitioner is unavailable")
        conflicts = self.appointments.find_overlaps(
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            start_at=start_at,
            end_at=end_at,
            exclude_appointment_id=exclude_appointment_id,
        )
        if conflicts:
            raise AppointmentError("SLOT_CONFLICT", "Doctor or patient already has an overlapping appointment")

    def _slot_is_available(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        start_at: datetime,
        end_at: datetime,
        current: datetime,
        horizon_end: datetime,
        minimum_advance_minutes: int,
    ) -> bool:
        if start_at < current + timedelta(minutes=minimum_advance_minutes) or start_at > horizon_end:
            return False
        if self.clinic.practitioner_is_blocked(practitioner_id, start_at, end_at):
            return False
        return not self.appointments.find_overlaps(
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            start_at=start_at,
            end_at=end_at,
        )

    def _configuration(self, practitioner_id: str, visit_type_id: str):
        config = self.clinic.get_clinic(self.clinic_id)
        practitioner = self.clinic.get_practitioner(practitioner_id)
        visit_type = self.clinic.get_visit_type(visit_type_id)
        if not config:
            raise AppointmentError("CLINIC_NOT_FOUND", "Clinic configuration is unavailable")
        if not practitioner or not bool(practitioner["active"]):
            raise AppointmentError("PRACTITIONER_UNAVAILABLE", "Practitioner is inactive or unavailable")
        if not visit_type:
            raise AppointmentError("VISIT_TYPE_NOT_FOUND", "Visit type is unavailable")
        return config, practitioner, visit_type, ZoneInfo(str(config["timezone"]))

    @staticmethod
    def _validate_profile_selection(practitioner: dict, department_id: str, location_id: str) -> None:
        if practitioner["department_id"] != department_id or practitioner["location_id"] != location_id:
            raise AppointmentError("PROFILE_MISMATCH", "Doctor, department, and location do not match")

    @staticmethod
    def _localize(value: datetime, timezone: ZoneInfo) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)

    @staticmethod
    def _hash_request(operation: str, payload: dict) -> str:
        encoded = json.dumps({"operation": operation, **payload}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_manage(actor: Actor, patient_id: str) -> None:
        if actor.role not in {"receptionist", "doctor"} or not is_patient_authorized(actor, patient_id):
            raise AppointmentError("FORBIDDEN", "Actor is not authorized for this appointment")

    def _get(self, appointment_id: str) -> Appointment:
        appointment = self.appointments.get(appointment_id)
        if appointment is None:
            raise AppointmentError("APPOINTMENT_NOT_FOUND", "Appointment was not found")
        return appointment
