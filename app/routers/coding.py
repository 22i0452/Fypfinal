from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import CodingServiceError


router = APIRouter(tags=["coding"])


def _context(request: Request, user: AuthUser, note_id: str):
    container = get_container(request)
    note = container.note_repository.get(note_id)
    patient_id = note.patient_id if note else ""
    return container, actor_for_user(container, user, patient_id)


@router.post("/api/notes/{note_id}/code-suggestions")
async def generate_code_suggestions(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container, actor = _context(request, user, note_id)
    if not container.settings.icd_coding_enabled:
        raise service_http_error(
            CodingServiceError("FEATURE_DISABLED", "ICD-10/CPT suggestions are disabled")
        )
    force = str(request.query_params.get("force") or "").strip().lower() in {"1", "true", "yes"}
    try:
        suggestions = await asyncio.to_thread(container.coding_service.generate,note_id=note_id,actor=actor,force=force)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
    return _coding_payload(container,note_id,suggestions,actor)


@router.get("/api/notes/{note_id}/code-suggestions")
async def list_code_suggestions(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container, actor = _context(request, user, note_id)
    try:
        suggestions = container.coding_service.list_for_note(note_id=note_id, actor=actor)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
    return _coding_payload(container,note_id,suggestions,actor)


@router.post("/api/code-suggestions/{suggestion_id}/approve")
async def approve_code_suggestion(
    suggestion_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    suggestion = container.code_suggestion_repository.get(suggestion_id)
    patient_id = suggestion.patient_id if suggestion else ""
    actor = actor_for_user(container, user, patient_id)
    try:
        updated = container.coding_service.review(suggestion_id=suggestion_id, approve=True, actor=actor)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
    return updated.model_dump(mode="json")


@router.post("/api/code-suggestions/{suggestion_id}/reject")
async def reject_code_suggestion(
    suggestion_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    suggestion = container.code_suggestion_repository.get(suggestion_id)
    patient_id = suggestion.patient_id if suggestion else ""
    actor = actor_for_user(container, user, patient_id)
    try:
        updated = container.coding_service.review(suggestion_id=suggestion_id, approve=False, actor=actor)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
    return updated.model_dump(mode="json")


def _coding_payload(container,note_id,suggestions,actor):
    note,version=container.note_lifecycle_service.get(note_id,actor=actor)
    patient=container.patient_repository.get(note.patient_id)
    source=container.note_lifecycle_service.payload(note,version,patient_name=patient.name if patient else 'Patient')
    return {'note_id':note_id,'source_note':source,'suggestions':[{**item.model_dump(mode='json'),'stale':note.current_version_id!=item.note_version_id} for item in suggestions]}


@router.get('/api/code-suggestions/{suggestion_id}/evidence')
async def code_evidence(suggestion_id:str,request:Request,user:AuthUser=Depends(get_current_user)):
    container=get_container(request)
    suggestion=container.code_suggestion_repository.get(suggestion_id)
    actor=actor_for_user(container,user,suggestion.patient_id if suggestion else '')
    try:
        return container.coding_service.evidence(suggestion_id=suggestion_id,actor=actor)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
