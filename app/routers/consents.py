from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import ConsentError
from medflow.domain.enums import ConsentType


router = APIRouter(prefix="/api/consents", tags=["consents"])


class ConsentBundleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    encounter_id: str
    audio_recording: bool
    ai_transcription: bool
    ai_documentation: bool
    audio_retention: bool = False
    consent_text_version: str = "CONSENT-V1"
    capture_method: str = "DOCTOR_ATTESTATION"


@router.post("")
async def capture_consents(
    payload: ConsentBundleRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    decisions = {
        ConsentType.AUDIO_RECORDING: payload.audio_recording,
        ConsentType.AI_TRANSCRIPTION: payload.ai_transcription,
        ConsentType.AI_DOCUMENTATION: payload.ai_documentation,
        ConsentType.AUDIO_RETENTION: payload.audio_retention,
    }
    try:
        records = container.consent_service.capture_bundle(
            encounter_id=payload.encounter_id,
            decisions=decisions,
            consent_text_version=payload.consent_text_version,
            capture_method=payload.capture_method,
            actor=actor,
        )
    except ConsentError as exc:
        raise service_http_error(exc) from exc
    return {"consents": [record.model_dump(mode="json") for record in records]}


@router.get("/encounters/{encounter_id}")
async def get_consents(
    encounter_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        records = container.consent_service.latest_decisions(encounter_id, actor=actor)
    except ConsentError as exc:
        raise service_http_error(exc) from exc
    return {
        consent_type.value: record.model_dump(mode="json") if record else None
        for consent_type, record in records.items()
    }


@router.post("/{consent_id}/revoke")
async def revoke_consent(
    consent_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        record = container.consent_service.revoke(consent_id=consent_id, actor=actor)
    except ConsentError as exc:
        raise service_http_error(exc) from exc
    return record.model_dump(mode="json")
