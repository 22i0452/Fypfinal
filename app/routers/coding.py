from __future__ import annotations

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
        suggestions = container.coding_service.generate(note_id=note_id, actor=actor, force=force)
    except CodingServiceError as exc:
        raise service_http_error(exc) from exc
    return {
        "note_id": note_id,
        "suggestions": [item.model_dump(mode="json") for item in suggestions],
    }


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
    return {"suggestions": [item.model_dump(mode="json") for item in suggestions]}


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
