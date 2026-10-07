from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import AppointmentError, AppointmentRequest, ClinicLifecycleError
from medflow.domain.enums import AppointmentStatus
from medflow.orchestration import WorkflowAccessError, WorkflowTransitionError
from security_guardrails.authz import is_patient_authorized


router = APIRouter(prefix="/api/appointments", tags=["appointments"])


class CreateAppointmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str
    practitioner_id: str
    department_id: str
    location_id: str
    visit_type_id: str
    start_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=128)
    workflow_id: str | None = None


class ReschedulePayload(BaseModel):
    new_start_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=128)


class CancelPayload(BaseModel):
    reason_code: str = "CANCELLED_BY_USER"
    idempotency_key: str = Field(min_length=8, max_length=128)


@router.get("/configuration")
async def appointment_configuration(request: Request, _: AuthUser = Depends(get_current_user)):
    clinic = get_container(request).clinic_repository
    return {
        "clinic": clinic.get_clinic(),
        "locations": clinic.list_locations(),
        "departments": clinic.list_departments(),
        "practitioners": clinic.list_practitioners(),
        "visit_types": clinic.list_visit_types(),
    }


@router.get("/availability")
async def availability(
    request: Request,
    patient_id: str,
    practitioner_id: str,
    visit_type_id: str,
    start_date: date,
    days: int = Query(default=7, ge=1, le=31),
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id)
    if not is_patient_authorized(actor, patient_id):
        raise service_http_error(AppointmentError("FORBIDDEN", "Patient access denied"))
    try:
        slots = container.appointment_service.availability(
            patient_id=patient_id,
            practitioner_id=practitioner_id,
            visit_type_id=visit_type_id,
            start_date=start_date,
            days=days,
        )
    except AppointmentError as exc:
        raise service_http_error(exc) from exc
    return {"slots": slots}


@router.get("")
async def list_appointments(
    request: Request,
    patient_id: str | None = None,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    allowed = container.auth_repository.authorized_patient_ids(user)
    allow_all = "*" in allowed
    if patient_id and not allow_all and patient_id not in allowed:
        raise service_http_error(AppointmentError("FORBIDDEN", "Patient access denied"))
    appointments = container.appointment_repository.list(patient_id=patient_id)
    return [
        item.model_dump(mode="json")
        for item in appointments
        if allow_all or item.patient_id in allowed
    ]


@router.get("/doctor-queue")
async def doctor_queue(
    request: Request,
    days: int = Query(default=60, ge=1, le=90),
    user: AuthUser = Depends(get_current_user),
):
    if user.actor_role != "doctor" or not user.practitioner_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Doctor access required",
        )
    container = get_container(request)
    clinic = container.clinic_repository.get_clinic()
    if not clinic:
        raise service_http_error(AppointmentError("CLINIC_NOT_FOUND", "Clinic configuration is unavailable"))
    timezone = ZoneInfo(str(clinic["timezone"]))
    current = datetime.now(timezone)
    start_of_today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    queue_end = start_of_today + timedelta(days=days)
    active_statuses = {
        AppointmentStatus.REQUESTED,
        AppointmentStatus.CONFIRMED,
        AppointmentStatus.CHECKED_IN,
        AppointmentStatus.IN_PROGRESS,
    }
    departments = {
        str(item["department_id"]): str(item["name"])
        for item in container.clinic_repository.list_departments()
    }
    visit_types = {
        str(item["visit_type_id"]): str(item["name"])
        for item in container.clinic_repository.list_visit_types()
    }
    locations = {
        str(item["location_id"]): str(item["name"])
        for item in container.clinic_repository.list_locations()
    }
    items: list[dict] = []
    for appointment in container.appointment_repository.list(
        practitioner_id=user.practitioner_id
    ):
        appointment_start = appointment.start_at
        if appointment_start.tzinfo is None:
            appointment_start = appointment_start.replace(tzinfo=timezone)
        else:
            appointment_start = appointment_start.astimezone(timezone)
        if (
            appointment.status not in active_statuses
            or appointment_start < start_of_today
            or appointment_start >= queue_end
        ):
            continue
        patient = container.patient_repository.get(appointment.patient_id)
        if patient is None:
            continue
        workflow = next(
            (
                item for item in container.workflow_repository.list(patient_id=patient.patient_id)
                if item.appointment_id == appointment.appointment_id
            ),
            None,
        )
        items.append(
            {
                "appointment_id": appointment.appointment_id,
                "patient_id": patient.patient_id,
                "patient_name": patient.name,
                "age": patient.age_text,
                "current_complaint": patient.current_complaint,
                "past_medical_history": patient.past_medical_history,
                "blood_pressure": patient.blood_pressure,
                "first_visit": patient.first_visit,
                "intake_recorded_at": patient.recorded_at,
                "start_at": appointment_start.isoformat(),
                "end_at": appointment.end_at.astimezone(timezone).isoformat(),
                "status": appointment.status.value,
                "department": departments.get(appointment.department_id, ""),
                "visit_type": visit_types.get(appointment.visit_type_id, ""),
                "location": locations.get(appointment.location_id, ""),
                "workflow_id": workflow.workflow_id if workflow else "",
                "workflow_state": workflow.state.value if workflow else "",
            }
        )
    items.sort(key=lambda item: item["start_at"])
    return {
        "timezone": str(clinic["timezone"]),
        "generated_at": current.isoformat(),
        "appointments": items,
    }


@router.get("/{appointment_id}")
async def get_appointment(
    appointment_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        appointment = container.appointment_service.get(appointment_id, actor=actor)
    except AppointmentError as exc:
        raise service_http_error(exc) from exc
    return appointment.model_dump(mode="json")


@router.post("")
async def create_appointment(
    payload: CreateAppointmentPayload,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, payload.patient_id)
    try:
        appointment = container.appointment_service.create(
            AppointmentRequest(
                patient_id=payload.patient_id,
                practitioner_id=payload.practitioner_id,
                department_id=payload.department_id,
                location_id=payload.location_id,
                visit_type_id=payload.visit_type_id,
                start_at=payload.start_at,
                idempotency_key=payload.idempotency_key,
            ),
            actor=actor,
        )
        workflow = None
        if payload.workflow_id:
            workflow = container.lifecycle_service.confirm_booking(
                payload.workflow_id,
                appointment=appointment,
                actor=actor,
            )
    except (AppointmentError, ClinicLifecycleError, WorkflowAccessError, WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc
    return {
        "appointment": appointment.model_dump(mode="json"),
        "workflow": workflow.model_dump(mode="json") if workflow else None,
    }


@router.post("/{appointment_id}/reschedule")
async def reschedule_appointment(
    appointment_id: str,
    payload: ReschedulePayload,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        appointment = container.appointment_service.reschedule(
            appointment_id,
            new_start_at=payload.new_start_at,
            idempotency_key=payload.idempotency_key,
            actor=actor,
        )
    except AppointmentError as exc:
        raise service_http_error(exc) from exc
    return appointment.model_dump(mode="json")


@router.post("/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: str,
    payload: CancelPayload,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        appointment = container.appointment_service.cancel(
            appointment_id,
            reason_code=payload.reason_code,
            idempotency_key=payload.idempotency_key,
            actor=actor,
        )
    except AppointmentError as exc:
        raise service_http_error(exc) from exc
    return appointment.model_dump(mode="json")
