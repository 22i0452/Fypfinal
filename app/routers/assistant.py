from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.services import NoteLifecycleError
from medflow.domain.enums import NoteStatus
from security_guardrails.authz import is_patient_authorized


ROOT = Path(__file__).resolve().parents[2]
MODULE2_DIR = ROOT / "scribe"
router = APIRouter(tags=["patient-assistant"])
_assistant = None


class AssistantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    patient_id: str
    question: str = Field(min_length=1, max_length=2000)


def _component():
    global _assistant
    if _assistant is None:
        if str(MODULE2_DIR) not in sys.path:
            sys.path.insert(0, str(MODULE2_DIR))
        from patient_assistant import PatientAssistant

        _assistant = PatientAssistant()
    return _assistant


@router.post("/api/patient-assistant")
async def patient_assistant(
    payload: AssistantRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    if user.actor_role != "doctor":
        container.audit_service.record(
            "authorization_denial",
            actor_ref=f"{user.actor_role}:{user.user_id}",
            action="patient_assistant_answer",
            patient_ref=payload.patient_id,
            result="deny",
            request_id=getattr(request.state, "request_id", ""),
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Doctor access required")
    actor = actor_for_user(container, user, payload.patient_id)
    if not is_patient_authorized(actor, payload.patient_id):
        container.audit_service.record(
            "authorization_denial",
            actor_ref=actor.ref,
            action="patient_assistant_answer",
            patient_ref=payload.patient_id,
            result="deny",
            request_id=getattr(request.state, "request_id", ""),
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Patient access denied")
    patient = container.patient_repository.get(payload.patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    latest_approved = None
    try:
        candidates = container.note_lifecycle_service.list(actor=actor, patient_id=patient.patient_id)
        approved = [item for item in candidates if item[0].state == NoteStatus.APPROVED_BY_DOCTOR]
        if approved:
            latest_approved = container.note_lifecycle_service.payload(
                approved[0][0],
                approved[0][1],
                patient_name=patient.name,
            )
    except NoteLifecycleError:
        latest_approved = None

    patient_payload = {
        "_id": patient.patient_id,
        "age": patient.age_text,
        "first_visit": patient.first_visit,
        "past_medical_history": patient.past_medical_history,
        "current_complaint": patient.current_complaint,
    }
    result = _component().answer(
        question=payload.question,
        patient=patient_payload,
        latest_note=latest_approved,
        actor=actor,
    )
    return {
        "patient_id": patient.patient_id,
        "has_note": latest_approved is not None,
        "result": result,
    }
