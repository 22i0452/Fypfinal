from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import VerificationError


router = APIRouter(prefix="/api/verification", tags=["verification"])


class RequestChallenge(BaseModel):
    patient_id: str
    workflow_id: str


class VerifyChallenge(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


@router.post("/challenges")
async def request_challenge(
    payload: RequestChallenge,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, payload.patient_id)
    try:
        result = container.verification_service.request_challenge(
            patient_id=payload.patient_id,
            workflow_id=payload.workflow_id,
            actor=actor,
        )
    except VerificationError as exc:
        raise service_http_error(exc) from exc
    return result.__dict__


@router.post("/challenges/{challenge_id}/resend")
async def resend_challenge(
    challenge_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        result = container.verification_service.resend(challenge_id=challenge_id, actor=actor)
    except VerificationError as exc:
        raise service_http_error(exc) from exc
    return result.__dict__


@router.post("/challenges/{challenge_id}/verify")
async def verify_challenge(
    challenge_id: str,
    payload: VerifyChallenge,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        result = container.verification_service.verify(
            challenge_id=challenge_id,
            code=payload.code,
            actor=actor,
        )
    except VerificationError as exc:
        raise service_http_error(exc) from exc
    return {
        "challenge_id": result.challenge_id,
        "patient_id": result.patient_id,
        "workflow_id": result.workflow_id,
        "status": result.status.value,
        "verified_at": result.verified_at.isoformat() if result.verified_at else None,
    }
