from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from security_guardrails import AuthorizationError, require_authorized


router = APIRouter(prefix="/api/audio", tags=["audio"])
_AUDIO_REF = re.compile(r"^audio_[0-9]{10,16}$")


@router.get("/{audio_ref}")
async def play_retained_audio(
    audio_ref: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    if not _AUDIO_REF.fullmatch(audio_ref):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
    retention_dir = Path(os.getenv("MEDFLOW_AUDIO_RETENTION_DIR", "scribe/retained_audio")).resolve()
    metadata_path = retention_dir / f"{audio_ref}.json"
    audio_path = retention_dir / f"{audio_ref}.wav"
    if not metadata_path.is_file() or not audio_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio not found") from exc
    patient_id = str(metadata.get("patient_ref") or "")
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id)
    try:
        require_authorized(actor, "audio_playback", patient_id)
    except AuthorizationError as exc:
        container.audit_service.record(
            "authorization_denial",
            actor_ref=actor.ref,
            action="audio_playback",
            patient_ref=patient_id,
            resource_ref=audio_ref,
            result="deny",
            request_id=getattr(request.state, "request_id", ""),
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Audio access denied") from exc
    container.audit_service.record(
        "retained_audio_accessed",
        actor_ref=actor.ref,
        action="audio_playback",
        patient_ref=patient_id,
        resource_ref=audio_ref,
        request_id=getattr(request.state, "request_id", ""),
    )
    return FileResponse(audio_path, media_type="audio/wav", filename=f"{audio_ref}.wav")
