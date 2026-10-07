from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from medflow.domain.models import Patient
from security_guardrails.authz import is_patient_authorized
from app.services.receptionist_integration_service import ReceptionistIntegrationError
from app.routers.common import service_http_error


router = APIRouter(tags=["patients"])


def _patient_payload(patient, appointment=None) -> dict:
    return {
        "_id": patient.patient_id,
        "patient_id": patient.patient_id,
        "legacy_ref": patient.legacy_ref,
        "file_name": patient.legacy_ref or f"{patient.patient_id}.json",
        "name": patient.name,
        "age": patient.age_text,
        "phone_number": patient.phone_number,
        "email": patient.email,
        "first_visit": patient.first_visit,
        "past_medical_history": patient.past_medical_history,
        "current_complaint": patient.current_complaint,
        "blood_pressure": patient.blood_pressure,
        "recorded_at": patient.recorded_at,
        "updated_at": patient.updated_at.isoformat(),
        "booking_slot_time": appointment.start_at.isoformat() if appointment else "",
        "appointment_id": appointment.appointment_id if appointment else "",
        "appointment_status": appointment.status.value if appointment else "",
    }


def _next_practitioner_appointment(container, patient_id: str, practitioner_id: str | None):
    if not practitioner_id:
        return None
    clinic = container.clinic_repository.get_clinic()
    timezone = ZoneInfo(str(clinic["timezone"])) if clinic else ZoneInfo("UTC")
    today = datetime.now(timezone).date()
    candidates = []
    for appointment in container.appointment_repository.list(
        patient_id=patient_id,
        practitioner_id=practitioner_id,
    ):
        if appointment.status.value in {"CANCELLED", "NO_SHOW", "COMPLETED"}:
            continue
        start_at = appointment.start_at
        if start_at.tzinfo is None:
            start_at = start_at.replace(tzinfo=timezone)
        else:
            start_at = start_at.astimezone(timezone)
        if start_at.date() >= today:
            candidates.append((start_at, appointment))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None


def _authorized_patient(request: Request, patient_id: str, user: AuthUser):
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id)
    if not is_patient_authorized(actor, patient_id):
        container.audit_service.record(
            "authorization_denial",
            actor_ref=actor.ref,
            action="read_patient",
            patient_ref=patient_id,
            result="deny",
            request_id=getattr(request.state, "request_id", ""),
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient access denied")
    patient = container.patient_repository.get(patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return patient


@router.get("/api/patients")
async def list_patients(request: Request, user: AuthUser = Depends(get_current_user)):
    container = get_container(request)
    allowed = container.auth_repository.authorized_patient_ids(user)
    allow_all = "*" in allowed
    return [
        _patient_payload(
            patient,
            _next_practitioner_appointment(container, patient.patient_id, user.practitioner_id),
        )
        for patient in container.patient_repository.list()
        if allow_all or patient.patient_id in allowed
    ]


@router.get("/api/patient/{patient_id}")
@router.get("/api/patients/{patient_id}")
async def get_patient(patient_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    container = get_container(request)
    patient = _authorized_patient(request, patient_id, user)
    return _patient_payload(
        patient,
        _next_practitioner_appointment(container, patient.patient_id, user.practitioner_id),
    )


# Legacy consultation dashboard compatibility.
router.add_api_route("/api/consultation/patients", list_patients, methods=["GET"])


class DoctorIntakeCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime
    changes: dict[str, str]
    confirmed: bool = Field(strict=True)


@router.patch("/api/patients/{patient_id}/intake")
async def correct_patient_intake(
    patient_id: str, payload: DoctorIntakeCorrection, request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    _authorized_patient(request, patient_id, user)
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Confirm the intake corrections")
    try:
        patient = container.receptionist_integration_service.correct_forwarded_intake(
            patient_id=patient_id, actor=actor_for_user(container, user, patient_id),
            expected_updated_at=payload.expected_updated_at, changes=payload.changes,
        )
    except ReceptionistIntegrationError as exc:
        raise service_http_error(exc) from exc
    return _patient_payload(patient)


@router.get("/api/consultation/patient/{patient_ref}")
async def legacy_patient(patient_ref: str, request: Request, user: AuthUser = Depends(get_current_user)):
    container = get_container(request)
    patient = container.patient_repository.get(patient_ref)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    patient = _authorized_patient(request, patient.patient_id, user)
    return _patient_payload(
        patient,
        _next_practitioner_appointment(container, patient.patient_id, user.practitioner_id),
    )


@router.post("/api/consultation/patients/seed")
async def seed_synthetic_patients(request: Request, user: AuthUser = Depends(get_current_user)):
    container = get_container(request)
    if container.settings.app_env not in {"development", "test"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Development seed endpoint unavailable")
    if user.actor_role != "doctor" or not user.practitioner_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor access required")
    samples = [
        Patient(
            patient_id="PT-DEMO-SYNTHETIC-001",
            name="Synthetic Demo Patient One",
            phone_number="03000000001",
            age_text="42 years",
            first_visit="No",
            past_medical_history="Synthetic controlled condition",
            current_complaint="Synthetic follow-up complaint",
            recorded_at="2030-01-02T09:00:00+05:00",
        ),
        Patient(
            patient_id="PT-DEMO-SYNTHETIC-002",
            name="Synthetic Demo Patient Two",
            phone_number="03000000002",
            age_text="29 years",
            first_visit="Yes",
            past_medical_history="No synthetic history reported",
            current_complaint="Synthetic acute complaint",
            recorded_at="2030-01-02T09:15:00+05:00",
        ),
    ]
    for sample in samples:
        if container.patient_repository.get(sample.patient_id) is None:
            container.patient_repository.save(sample)
        container.auth_repository.assign_patient(user.practitioner_id, sample.patient_id)
    return {"ok": True, "count": len(samples)}
