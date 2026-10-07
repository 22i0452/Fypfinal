from __future__ import annotations

import hmac
from datetime import date, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_container
from app.routers.common import service_http_error
from app.services import (
    AppointmentError,
    ClinicLifecycleError,
    ReceptionistBooking,
    ReceptionistIntake,
    ReceptionistIntegrationError,
)
from medflow.orchestration import (
    WorkflowAccessError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowTransitionError,
)


router = APIRouter(prefix="/api/receptionist", tags=["receptionist"])


class IntakePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=120)
    age_text: str = Field(min_length=1, max_length=40)
    phone_number: str = Field(min_length=10, max_length=32)
    first_visit: str = Field(min_length=1, max_length=40)
    past_medical_history: str = Field(default="", max_length=2000)
    current_complaint: str = Field(min_length=2, max_length=2000)
    intake_token: str = Field(min_length=32, max_length=128)
    revision: int = Field(ge=1)
    confirmed_revision: int = Field(ge=1)


class IntakeUpdatePayload(IntakePayload):
    workflow_id: str = Field(min_length=6, max_length=64)
    expected_revision: int = Field(ge=1)


class BookingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    patient_id: str = Field(min_length=6, max_length=64)
    workflow_id: str = Field(min_length=6, max_length=64)
    department_id: str = Field(min_length=3, max_length=64)
    practitioner_id: str = Field(default="", max_length=64)
    visit_type_id: str = Field(min_length=3, max_length=64)
    start_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=128)
    intake_token: str = Field(min_length=32, max_length=128)
    revision: int = Field(ge=1)


def require_receptionist_service(
    request: Request,
    service_token: str = Header(default="", alias="X-MedFlow-Receptionist-Token"),
) -> None:
    container = get_container(request)
    expected = container.settings.receptionist_service_token
    if expected and service_token and hmac.compare_digest(expected, service_token):
        return
    container.audit_service.record(
        "authorization_denial",
        actor_ref="service:anonymous",
        action="receptionist_api_access",
        result="deny",
        request_id=getattr(request.state, "request_id", ""),
    )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Receptionist service authentication required",
    )


def _service_error(error: Exception) -> HTTPException:
    return service_http_error(error)


@router.get("/configuration")
async def configuration(
    request: Request,
    _: None = Depends(require_receptionist_service),
):
    try:
        return get_container(request).receptionist_integration_service.configuration()
    except ReceptionistIntegrationError as exc:
        raise _service_error(exc) from exc


@router.get("/availability")
async def availability(
    request: Request,
    practitioner_id: str = Query(min_length=3, max_length=64),
    visit_type_id: str = Query(min_length=3, max_length=64),
    start_date: date | None = None,
    days: int = Query(default=14, ge=1, le=30),
    limit: int = Query(default=12, ge=1, le=30),
    _: None = Depends(require_receptionist_service),
):
    try:
        return get_container(request).receptionist_integration_service.availability(
            practitioner_id=practitioner_id,
            visit_type_id=visit_type_id,
            start_date=start_date,
            days=days,
            limit=limit,
        )
    except (ReceptionistIntegrationError, AppointmentError) as exc:
        raise _service_error(exc) from exc


@router.post("/intakes")
async def create_intake(
    payload: IntakePayload,
    request: Request,
    _: None = Depends(require_receptionist_service),
):
    try:
        return get_container(request).receptionist_integration_service.create_intake(
            ReceptionistIntake(
                name=payload.name,
                age_text=payload.age_text,
                phone_number=payload.phone_number,
                first_visit=payload.first_visit,
                past_medical_history=payload.past_medical_history,
                current_complaint=payload.current_complaint,
                intake_token=payload.intake_token,
                revision=payload.revision,
                confirmed_revision=payload.confirmed_revision,
            )
        )
    except (
        ReceptionistIntegrationError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowTransitionError,
    ) as exc:
        raise _service_error(exc) from exc


@router.post("/bookings")
async def book(
    payload: BookingPayload,
    request: Request,
    _: None = Depends(require_receptionist_service),
):
    try:
        return get_container(request).receptionist_integration_service.book(
            ReceptionistBooking(
                patient_id=payload.patient_id,
                workflow_id=payload.workflow_id,
                department_id=payload.department_id,
                practitioner_id=payload.practitioner_id,
                visit_type_id=payload.visit_type_id,
                start_at=payload.start_at,
                idempotency_key=payload.idempotency_key,
                intake_token=payload.intake_token,
                revision=payload.revision,
            )
        )
    except (
        ReceptionistIntegrationError,
        AppointmentError,
        ClinicLifecycleError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowTransitionError,
    ) as exc:
        raise _service_error(exc) from exc


@router.patch("/intakes/{patient_id}")
async def update_intake(
    patient_id: str, payload: IntakeUpdatePayload, request: Request,
    _: None = Depends(require_receptionist_service),
):
    try:
        return get_container(request).receptionist_integration_service.update_intake(
            patient_id=patient_id, workflow_id=payload.workflow_id,
            expected_revision=payload.expected_revision,
            intake=ReceptionistIntake(**payload.model_dump(exclude={"workflow_id", "expected_revision"})),
        )
    except ReceptionistIntegrationError as exc:
        raise _service_error(exc) from exc
