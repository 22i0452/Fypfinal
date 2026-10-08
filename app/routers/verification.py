from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, ConfigDict

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import VerificationError
from medflow.orchestration import WorkflowAccessError,WorkflowConflictError,WorkflowNotFoundError,WorkflowTransitionError


router = APIRouter(prefix="/api/verification", tags=["verification"])


class RequestChallenge(BaseModel):
    patient_id: str
    workflow_id: str


class VerifyChallenge(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ReviewDetails(BaseModel):
    model_config = ConfigDict(extra='forbid')
    patient_id: str
    workflow_id: str
    expected_version: int = Field(ge=1)
    details_checked: bool


@router.post('/review-details')
async def review_details(payload: ReviewDetails,request: Request,user: AuthUser=Depends(get_current_user)):
    container=get_container(request)
    actor=actor_for_user(container,user,payload.patient_id)
    if not payload.details_checked:
        raise service_http_error(VerificationError('DETAILS_REQUIRED','Check the patient name and intake before continuing'))
    try:
        with container.database.transaction():
            result=container.verification_service.review_details(patient_id=payload.patient_id,
                workflow_id=payload.workflow_id,expected_version=payload.expected_version,actor=actor)
        return result.model_dump(mode='json')
    except (VerificationError,WorkflowAccessError,WorkflowConflictError,WorkflowNotFoundError,WorkflowTransitionError) as exc:raise service_http_error(exc) from exc


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
