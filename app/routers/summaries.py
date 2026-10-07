from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import AfterVisitSummaryError, PreVisitSummaryError
from medflow.domain.enums import SummaryLanguage


router = APIRouter(tags=["clinical-summaries"])


class PreVisitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter_id: str


class AfterVisitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: SummaryLanguage = SummaryLanguage.BILINGUAL


@router.post("/api/patients/{patient_id}/previsit-summaries")
async def generate_previsit_summary(
    patient_id: str,
    payload: PreVisitRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    if not container.settings.previsit_summary_enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pre-visit summaries are disabled")
    actor = actor_for_user(container, user, patient_id)
    try:
        summary = container.previsit_summary_service.generate(
            patient_id=patient_id,
            encounter_id=payload.encounter_id,
            actor=actor,
        )
    except PreVisitSummaryError as exc:
        raise service_http_error(exc) from exc
    return summary.model_dump(mode="json")


@router.get("/api/patients/{patient_id}/previsit-summaries/latest")
async def latest_previsit_summary(
    patient_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id)
    try:
        summary = container.previsit_summary_service.latest(patient_id=patient_id, actor=actor)
    except PreVisitSummaryError as exc:
        raise service_http_error(exc) from exc
    if summary is None:
        return {"summary": None, "exists": False}
    return {**summary.model_dump(mode="json"), "exists": True}


@router.post("/api/notes/{note_id}/after-visit-summary")
async def generate_after_visit_summary(
    note_id: str,
    payload: AfterVisitRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    note = container.note_repository.get(note_id)
    patient_id = note.patient_id if note else ""
    actor = actor_for_user(container, user, patient_id)
    try:
        summary = container.after_visit_summary_service.generate(
            note_id=note_id,
            language=payload.language,
            actor=actor,
        )
    except AfterVisitSummaryError as exc:
        raise service_http_error(exc) from exc
    return summary.model_dump(mode="json")


@router.get("/api/encounters/{encounter_id}/after-visit-summary")
async def get_after_visit_summary(
    encounter_id: str,
    request: Request,
    language: SummaryLanguage | None = Query(default=None),
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    encounter = container.encounter_repository.get(encounter_id)
    if encounter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
    actor = actor_for_user(container, user, encounter.patient_id)
    try:
        summary = container.after_visit_summary_service.get_for_encounter(
            encounter_id=encounter_id,
            actor=actor,
            language=language,
        )
    except AfterVisitSummaryError as exc:
        raise service_http_error(exc) from exc
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="After-visit summary not found")
    return summary.model_dump(mode="json")
