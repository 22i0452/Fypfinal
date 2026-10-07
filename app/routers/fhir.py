from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import actor_for_user, get_container, get_current_user
from app.fhir import FHIRMapper, FHIRMappingError
from app.repositories import AuthUser
from medflow.domain.enums import NoteStatus
from security_guardrails import AuthorizationError, require_authorized


router = APIRouter(prefix="/api/fhir", tags=["fhir-export"])


def _container(request: Request):
    container = get_container(request)
    if not container.settings.fhir_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "FEATURE_DISABLED", "message": "FHIR export is disabled"},
        )
    return container


def _authorize(container, user: AuthUser, patient_id: str):
    actor = actor_for_user(container, user, patient_id)
    try:
        require_authorized(actor, "export_fhir", patient_id)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient access denied") from exc
    return actor


@router.get("/patients/{patient_id}")
async def export_patient(
    patient_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = _container(request)
    _authorize(container, user, patient_id)
    patient = container.patient_repository.get(patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return FHIRMapper.patient(patient)


@router.get("/appointments/{appointment_id}")
async def export_appointment(
    appointment_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = _container(request)
    appointment = container.appointment_repository.get(appointment_id)
    if appointment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    _authorize(container, user, appointment.patient_id)
    return FHIRMapper.appointment(appointment)


@router.get("/encounters/{encounter_id}")
async def export_encounter(
    encounter_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = _container(request)
    encounter = container.encounter_repository.get(encounter_id)
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    _authorize(container, user, encounter.patient_id)
    return FHIRMapper.encounter(encounter)


@router.get("/notes/{note_id}")
async def export_note(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = _container(request)
    note = container.note_repository.get(note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    _authorize(container, user, note.patient_id)
    version = container.note_repository.get_version(note.current_version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note version not found")
    try:
        return FHIRMapper.composition(note, version)
    except FHIRMappingError as exc:
        code = status.HTTP_409_CONFLICT if note.state != NoteStatus.APPROVED_BY_DOCTOR else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc)) from exc
