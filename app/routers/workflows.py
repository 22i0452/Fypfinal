from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
import asyncio
from app.services.consultation_review import ConsultationReviewError

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import (
    AppointmentError,
    ClinicLifecycleError,
    ConsentError,
    DevelopmentQuickStartError,
)
from medflow.orchestration import (
    WorkflowAction,
    WorkflowAccessError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowTransitionError,
)
from medflow.domain.enums import AppointmentStatus, EncounterStatus, NoteStatus, WorkflowState
from medflow.domain.models import utc_now
from security_guardrails.authz import is_patient_authorized


router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class CreateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: str


def _workflow_payload(workflow) -> dict:
    return workflow.model_dump(mode="json")


@router.get("/capabilities")
async def workspace_capabilities(request: Request, user: AuthUser = Depends(get_current_user)):
    settings = get_container(request).settings
    return {"coding_enabled": settings.icd_coding_enabled,
            "previsit_enabled": settings.previsit_summary_enabled,
            "development_quick_start_enabled": settings.development_quick_start_available}


def _context_payload(container, workflow, actor) -> dict:
    appointment = container.appointment_repository.get(workflow.appointment_id) if workflow and workflow.appointment_id else None
    encounter = container.encounter_repository.get(workflow.encounter_id) if workflow and workflow.encounter_id else None
    decisions = container.consent_service.latest_decisions(encounter.encounter_id, actor=actor) if encounter else {}
    note = None
    if workflow and workflow.note_id:
        record, version = container.note_lifecycle_service.get(workflow.note_id, actor=actor)
        patient = container.patient_repository.get(workflow.patient_id)
        note = container.note_lifecycle_service.payload(record, version, patient_name=patient.name if patient else "Patient")
    return {
        "workflow": _workflow_payload(workflow) if workflow else None,
        "details_verification": {"method": verification.method, "verified_at": verification.verified_at.isoformat() if verification.verified_at else None} if workflow and (verification := container.verification_repository.latest_for_workflow(workflow.workflow_id)) and verification.status.value == "VERIFIED" else None,
        "appointment": appointment.model_dump(mode="json") if appointment else None,
        "encounter": encounter.model_dump(mode="json") if encounter else None,
        "consents": [item.model_dump(mode="json") for item in decisions.values() if item],
        "note": note,
        "conversation_review": container.consultation_review.payload(workflow.workflow_id, actor) if workflow else None,
        "process_trace": container.process_trace.latest(encounter.encounter_id, workflow.patient_id) if encounter else None,
        "coding_enabled": container.settings.icd_coding_enabled,
        "development_quick_start_enabled": container.settings.development_quick_start_available,
    }


@router.get("/context/{patient_id}")
async def patient_visit_context(patient_id: str, request: Request, note_id: str | None = None, user: AuthUser = Depends(get_current_user)):
    """Read a visit without creating, checking in, or cancelling any resources."""
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id)
    if not is_patient_authorized(actor, patient_id):
        raise HTTPException(status_code=403, detail="Patient access denied")
    if container.patient_repository.get(patient_id) is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    candidates = sorted(container.workflow_repository.list(patient_id=patient_id), key=lambda item: item.updated_at, reverse=True)
    if note_id:
        candidates = [item for item in candidates if item.note_id == note_id]
        if not candidates:
            raise HTTPException(status_code=404, detail="The visit for this note was not found")
    active = [item for item in candidates if item.state not in {WorkflowState.CANCELLED, WorkflowState.ENCOUNTER_COMPLETED}]
    workflow = next(iter(active or candidates), None)
    if workflow:
        workflow = container.workflow_orchestrator.get_session(workflow.workflow_id, actor=actor)
    return _context_payload(container, workflow, actor)


@router.post("")
async def create_or_resume_workflow(
    payload: CreateWorkflowRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, payload.patient_id)
    try:
        workflow = container.lifecycle_service.get_or_create_workflow(
            patient_id=payload.patient_id,
            actor=actor,
        )
    except (WorkflowAccessError, WorkflowConflictError) as exc:
        raise service_http_error(exc) from exc
    return {
        "workflow": _workflow_payload(workflow),
        "development_mode": container.settings.app_env == "development",
        "development_otp_visible": container.settings.may_expose_dev_otp,
        "development_quick_start_enabled": container.settings.development_quick_start_available,
    }


@router.post("/prepare-consultation")
async def prepare_consultation(
    payload: CreateWorkflowRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Legacy development shortcut; normal patient opening uses the read-only context."""
    container = get_container(request)
    if not container.settings.development_quick_start_available:
        raise HTTPException(status_code=404, detail="Development shortcut is unavailable")
    actor = actor_for_user(container, user, payload.patient_id)
    existing = next((item for item in container.workflow_repository.list(patient_id=payload.patient_id)
                     if item.state not in {WorkflowState.ENCOUNTER_COMPLETED, WorkflowState.CANCELLED}), None)
    if existing and existing.state in {WorkflowState.TRANSCRIPT_REVIEW, WorkflowState.DOCUMENTATION_PROCESSING, WorkflowState.NOTE_REVIEW_REQUIRED, WorkflowState.NOTE_APPROVED, WorkflowState.FAILED}:
        existing = container.workflow_orchestrator.get_session(existing.workflow_id, actor=actor)
        return {**_context_payload(container, existing, actor), "cancelled_workflow_count": 0}
    try:
        result = container.development_quick_start_service.prepare_for_consent(
            patient_id=payload.patient_id,
            practitioner_id=user.practitioner_id or "",
            actor=actor,
            reset_unfinished=False,
            require_synthetic_patient=False,
        )
    except (
        AppointmentError,
        ClinicLifecycleError,
        ConsentError,
        DevelopmentQuickStartError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowTransitionError,
    ) as exc:
        raise service_http_error(exc) from exc
    return {
        "workflow": result.context.workflow.model_dump(mode="json"),
        "appointment": result.context.appointment.model_dump(mode="json"),
        "encounter": result.context.encounter.model_dump(mode="json"),
        "consents": [record.model_dump(mode="json") for record in result.consents],
        "cancelled_workflow_count": result.cancelled_workflow_count,
    }


@router.post("/{workflow_id}/complete")
async def complete_visit(workflow_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    """Complete the same approved visit, with repeat requests remaining idempotent."""
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        workflow = container.workflow_orchestrator.get_session(workflow_id, actor=actor)
        if workflow.state not in {WorkflowState.NOTE_APPROVED, WorkflowState.ENCOUNTER_COMPLETED} or not workflow.note_id:
            raise HTTPException(status_code=409, detail="Approve the note before completing this visit")
        note, _ = container.note_lifecycle_service.get(workflow.note_id, actor=actor)
        if note.state != NoteStatus.APPROVED_BY_DOCTOR or note.encounter_id != workflow.encounter_id:
            raise HTTPException(status_code=409, detail="This encounter needs a current doctor-approved note")
        appointment = container.appointment_repository.get(workflow.appointment_id)
        encounter = container.encounter_repository.get(workflow.encounter_id)
        if not appointment or not encounter or appointment.patient_id != workflow.patient_id or encounter.patient_id != workflow.patient_id:
            raise HTTPException(status_code=409, detail="Visit context is incomplete")
        if appointment.status not in {AppointmentStatus.IN_PROGRESS, AppointmentStatus.COMPLETED}:
            raise HTTPException(status_code=409, detail="Appointment cannot be completed from its current state")
        if workflow.state == WorkflowState.NOTE_APPROVED:
            workflow = container.workflow_orchestrator.perform_action(workflow_id, WorkflowAction.COMPLETE_ENCOUNTER, actor=actor, expected_version=workflow.version)
        if appointment.status != AppointmentStatus.COMPLETED:
            container.appointment_service.complete(appointment.appointment_id, actor=actor)
        if encounter.status != EncounterStatus.COMPLETED:
            container.encounter_repository.save(encounter.model_copy(update={"status": EncounterStatus.COMPLETED, "ended_at": utc_now(), "updated_at": utc_now()}))
        return _context_payload(container, workflow, actor)
    except (AppointmentError, WorkflowAccessError, WorkflowConflictError, WorkflowNotFoundError, WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc


class TranscriptRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    transcript_id: str = Field(min_length=1, max_length=80)


class ConversationCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utterance_id: str = Field(min_length=1, max_length=80)
    speaker: str | None = None
    speaker_relation: str | None = Field(default=None, max_length=40)
    original_text: str | None = Field(default=None, min_length=1, max_length=4000)
    clinical_english: str | None = Field(default=None, min_length=1, max_length=4000)
    medicines_reviewed: bool | None = None
    medicine_spellings: dict[str,str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_correction(self):
        if self.speaker is not None and self.speaker not in {"DOCTOR","PATIENT","NURSE","ATTENDANT","UNKNOWN"}:
            raise ValueError("Unknown speaker role")
        for value in (self.original_text,self.clinical_english):
            if value is not None and not value.strip():
                raise ValueError("Turn text cannot be blank")
        if len(self.medicine_spellings)>20 or any(not key.strip() or len(key)>100 or not value.strip() or len(value)>100 for key,value in self.medicine_spellings.items()):
            raise ValueError('Medicine spellings must be short, nonempty source/name pairs')
        if self.medicine_spellings and not self.medicines_reviewed:
            raise ValueError('Confirm the medicine wording when supplying a spelling')
        if self.speaker is None and self.original_text is None and self.clinical_english is None and not self.medicines_reviewed:
            raise ValueError("Supply a role or wording correction")
        return self


class ConversationEditRequest(TranscriptRevisionRequest):
    corrections: list[ConversationCorrection] = Field(min_length=1, max_length=100)


async def _conversation_action(request, user, workflow_id, payload, action):
    container = get_container(request)
    actor = actor_for_user(container,user)
    try:
        method = getattr(container.consultation_review,action)
        args = [workflow_id,actor,payload.expected_revision,payload.transcript_id]
        if action=='revise':
            args.append([item.model_dump(exclude_none=True) for item in payload.corrections])
        await asyncio.to_thread(method,*args)
        workflow=container.workflow_orchestrator.get_session(workflow_id,actor=actor)
        return _context_payload(container,workflow,actor)
    except (ConsultationReviewError,PermissionError,WorkflowAccessError,WorkflowConflictError,WorkflowNotFoundError,WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc


@router.patch("/{workflow_id}/conversation")
async def revise_conversation(workflow_id: str,payload: ConversationEditRequest,request: Request,user: AuthUser=Depends(get_current_user)):
    return await _conversation_action(request,user,workflow_id,payload,'revise')


@router.post("/{workflow_id}/generate-soap")
async def generate_reviewed_soap(workflow_id: str,payload: TranscriptRevisionRequest,request: Request,user: AuthUser=Depends(get_current_user)):
    return await _conversation_action(request,user,workflow_id,payload,'generate')


@router.post("/{workflow_id}/retry-translation")
async def retry_conversation_translation(workflow_id: str,payload: TranscriptRevisionRequest,request: Request,user: AuthUser=Depends(get_current_user)):
    return await _conversation_action(request,user,workflow_id,payload,'retry_translation')


@router.post("/{workflow_id}/retry-documentation")
async def retry_documentation(workflow_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    """Explicitly allow new audio after a failed pipeline, preserving the encounter."""
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        workflow = container.workflow_orchestrator.get_session(workflow_id, actor=actor)
        encounter = container.encounter_repository.get(workflow.encounter_id) if workflow.encounter_id else None
        if workflow.state != WorkflowState.FAILED or workflow.resume_state != WorkflowState.DOCUMENTATION_PROCESSING or workflow.note_id:
            raise HTTPException(status_code=409, detail="Only failed documentation without a saved note can be recorded again")
        if not encounter or encounter.status in {EncounterStatus.COMPLETED, EncounterStatus.CANCELLED}:
            raise HTTPException(status_code=409, detail="This encounter cannot be recorded again")
        workflow = container.workflow_orchestrator.perform_action(
            workflow_id, WorkflowAction.RETRY_DOCUMENTATION, actor=actor, expected_version=workflow.version,
        )
        if container.consultation_review.store.get(workflow_id):
            container.consultation_review.store.change(workflow_id,lambda row:{**row,'status':'SUPERSEDED','operation_token':None})
        return _context_payload(container, workflow, actor)
    except (WorkflowAccessError, WorkflowConflictError, WorkflowNotFoundError, WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc


@router.post("/development/quick-start")
async def development_quick_start(
    payload: CreateWorkflowRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    if not container.settings.development_quick_start_available:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Development quick start is unavailable",
        )
    actor = actor_for_user(container, user, payload.patient_id)
    try:
        result = container.development_quick_start_service.start(
            patient_id=payload.patient_id,
            practitioner_id=user.practitioner_id or "",
            actor=actor,
        )
    except (
        AppointmentError,
        ClinicLifecycleError,
        ConsentError,
        DevelopmentQuickStartError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowTransitionError,
    ) as exc:
        raise service_http_error(exc) from exc
    return {
        "workflow": result.context.workflow.model_dump(mode="json"),
        "appointment": result.context.appointment.model_dump(mode="json"),
        "encounter": result.context.encounter.model_dump(mode="json"),
        "consents": [
            record.model_dump(mode="json")
            for record in result.consents
        ],
        "cancelled_workflow_count": result.cancelled_workflow_count,
        "development_mode": True,
        "audio_retention": False,
    }


@router.get("/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        workflow = container.workflow_orchestrator.get_session(workflow_id, actor=actor)
        actions = container.workflow_orchestrator.allowed_actions(workflow_id, actor=actor)
    except (WorkflowAccessError, WorkflowNotFoundError) as exc:
        raise service_http_error(exc) from exc
    return {
        "workflow": _workflow_payload(workflow),
        "allowed_actions": [action.value for action in actions],
    }


@router.post("/{workflow_id}/complete-intake")
async def complete_intake(
    workflow_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        workflow = container.lifecycle_service.complete_existing_intake(workflow_id, actor=actor)
    except (ClinicLifecycleError, WorkflowAccessError, WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc
    return {"workflow": _workflow_payload(workflow)}


@router.post("/{workflow_id}/check-in")
async def check_in(
    workflow_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        context = container.lifecycle_service.check_in(workflow_id, actor=actor)
    except (ClinicLifecycleError, WorkflowAccessError, WorkflowTransitionError) as exc:
        raise service_http_error(exc) from exc
    return {
        "workflow": context.workflow.model_dump(mode="json"),
        "appointment": context.appointment.model_dump(mode="json"),
        "encounter": context.encounter.model_dump(mode="json"),
    }
