from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status, Response
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import actor_for_user, get_container, get_current_user
from app.repositories import AuthUser
from app.routers.common import service_http_error
from app.services import NoteLifecycleError
from medflow.domain.enums import NoteStatus
from app.services.prescription_service import PrescriptionEdit
import asyncio


router = APIRouter(prefix="/api/notes", tags=["notes"])


class PreparePrescription(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)


@router.post('/{note_id}/prescription/prepare')
async def prepare_prescription(note_id: str, payload: PreparePrescription, request: Request, user: AuthUser = Depends(get_current_user)):
    from app.services.prescription_service import draft
    container = get_container(request); actor = actor_for_user(container, user)
    try:
        service = container.note_lifecycle_service
        note, version = service.get(note_id, actor=actor)
        service._require(actor, 'create_note_draft', note.patient_id)
        if version.version_number != payload.expected_version:
            raise NoteLifecycleError('VERSION_CONFLICT', 'Reopen the latest prescription.')
        patient = container.patient_repository.get(note.patient_id)
        value = await asyncio.to_thread(draft, service, note, version, extract=True,
            patient_context=container.documentation_service._patient_context(patient))
        latest, _ = service.get(note_id, actor=actor)
        if latest.current_version_id != version.note_version_id:
            raise NoteLifecycleError('VERSION_CONFLICT', 'The note changed during preparation. Reopen it.')
        return {'note_id': note_id, 'version': version.version_number, 'prescription': value}
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc


@router.patch('/{note_id}/prescription')
async def save_prescription(note_id: str, payload: PrescriptionEdit, request: Request, user: AuthUser = Depends(get_current_user)):
    from app.services.prescription_service import save
    container = get_container(request)
    try:
        note, version = save(container.note_lifecycle_service, note_id, actor_for_user(container, user), payload)
        return _payload(container, note, version)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc


@router.get('/{note_id}/prescription.pdf')
async def export_prescription(note_id: str, request: Request, user: AuthUser = Depends(get_current_user)):
    from app.services.pdf_reports import prescription_pdf
    container = get_container(request)
    try:
        note, version = container.note_lifecycle_service.get(note_id, actor=actor_for_user(container, user))
        if note.state != NoteStatus.APPROVED_BY_DOCTOR or not version.prescription or not version.prescription.get('confirmed'):
            raise NoteLifecycleError('DOCTOR_APPROVAL_REQUIRED', 'Save the prescription and approve the current note before exporting.')
        doctor = container.auth_repository.get_by_id(note.approved_by_doctor_id) if note.approved_by_doctor_id else None
        content = prescription_pdf(_payload(container, note, version), container.patient_repository.get(note.patient_id),
            doctor.full_name if doctor else user.full_name)
        container.audit_service.record('prescription_exported', actor_ref=f'doctor:{user.user_id}', action='export_pdf',
            patient_ref=note.patient_id, resource_ref=note_id, metadata={'version': version.version_number})
        return Response(content, media_type='application/pdf', headers={'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="medflow-prescription-{note_id}-v{version.version_number}.pdf"'})
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc


@router.get('/{note_id}/export.pdf')
async def export_pdf(note_id: str, request: Request, technical: bool = False,
                     user: AuthUser = Depends(get_current_user)):
    container = get_container(request)
    try:
        note, version = container.note_lifecycle_service.get(note_id, actor=actor_for_user(container,user))
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    from app.services.pdf_reports import visit_pdf
    payload = _payload(container,note,version)
    doctor = container.auth_repository.get_by_id(note.approved_by_doctor_id) if note.approved_by_doctor_id else user
    content = visit_pdf(payload, container.patient_repository.get(note.patient_id), doctor.full_name if doctor else 'Not recorded', technical=technical)
    container.audit_service.record('note_exported',actor_ref=f'doctor:{user.user_id}',action='export_pdf',patient_ref=note.patient_id,
                                   resource_ref=note.note_id,metadata={'version':version.version_number,'technical':technical})
    return Response(content,media_type='application/pdf',headers={'Cache-Control':'no-store',
        'Content-Disposition':f'attachment; filename="medflow-{note.note_id}-v{version.version_number}.pdf"'})


class SOAPSections(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subjective: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    assessment: str = Field(min_length=1)
    plan: str = Field(min_length=1)


class EditNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    soap: SOAPSections
    change_reason: str = "Doctor edit"


class LegacySaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    note_id: str | None = None
    patient_id: str
    soap: SOAPSections


class RejectNoteRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=240)


def _payload(container, note, version):
    patient = container.patient_repository.get(note.patient_id)
    return container.note_lifecycle_service.payload(
        note,
        version,
        patient_name=patient.name if patient else "Patient",
    )


@router.get("")
async def list_notes(
    request: Request,
    patient_id: str | None = None,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user, patient_id or "")
    try:
        notes = container.note_lifecycle_service.list(actor=actor, patient_id=patient_id)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return [_payload(container, note, version) for note, version in notes]


@router.get("/{note_id}")
async def get_note(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.get(note_id, actor=actor)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.patch("/{note_id}")
async def edit_note(
    note_id: str,
    payload: EditNoteRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.edit_legacy_sections(
            note_id,
            sections=payload.soap.model_dump(),
            actor=actor,
            change_reason=payload.change_reason,
        )
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.post("")
async def legacy_save_note(
    payload: LegacySaveRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    """Compatibility adapter for the existing workspace's Save Draft action."""
    container = get_container(request)
    actor = actor_for_user(container, user, payload.patient_id)
    note_id = payload.note_id
    if not note_id:
        workflow = next(
            (
                item
                for item in container.workflow_repository.list(patient_id=payload.patient_id)
                if item.note_id
            ),
            None,
        )
        note_id = workflow.note_id if workflow else None
    if not note_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "NOTE_CONTEXT_REQUIRED",
                "message": "Generate a consultation draft before saving it",
            },
        )
    try:
        note, version = container.note_lifecycle_service.edit_legacy_sections(
            note_id,
            sections=payload.soap.model_dump(),
            actor=actor,
            change_reason="Saved from doctor workspace",
        )
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.post("/{note_id}/submit-for-review")
async def submit_for_review(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.submit_for_review(note_id, actor=actor)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.post("/{note_id}/approve")
async def approve_note(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.approve(note_id, actor=actor)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.post("/{note_id}/reject")
async def reject_note(
    note_id: str,
    payload: RejectNoteRequest,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.reject(
            note_id,
            actor=actor,
            reason=payload.reason,
        )
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return _payload(container, note, version)


@router.get("/{note_id}/versions")
async def note_versions(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        versions = container.note_lifecycle_service.versions(note_id, actor=actor)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    return [version.model_dump(mode="json") for version in versions]


@router.post("/{note_id}/finalize")
async def finalize_note(
    note_id: str,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    container = get_container(request)
    actor = actor_for_user(container, user)
    try:
        note, version = container.note_lifecycle_service.get(note_id, actor=actor)
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
    if note.state != NoteStatus.APPROVED_BY_DOCTOR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "DOCTOR_APPROVAL_REQUIRED", "message": "Only approved notes can be finalized"},
        )
    return {**_payload(container, note, version), "finalized": True}


class RoleCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    utterance_id: str = Field(min_length=1, max_length=64)
    speaker: str = Field(pattern='^(DOCTOR|PATIENT|NURSE|ATTENDANT|UNKNOWN)$')
    speaker_relation: str | None = Field(default=None, max_length=40)


class RoleRevisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    corrections: list[RoleCorrection] = Field(min_length=1, max_length=300)


@router.post('/{note_id}/correct-roles')
async def correct_roles(note_id: str, payload: RoleRevisionRequest, request: Request, user: AuthUser = Depends(get_current_user)):
    import asyncio
    from app.services.transcript_revision import revise_roles
    container = get_container(request)
    try:
        return await asyncio.to_thread(revise_roles, container, note_id, actor_for_user(container,user), payload.expected_version, [item.model_dump() for item in payload.corrections])
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc


class RelevanceCorrection(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    utterance_id: str = Field(min_length=1, max_length=80)
    relevance_status: str = Field(pattern='^(included|excluded|review)$')
    relevance_reason: str = Field(min_length=1, max_length=240)


class RelevanceRevision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
    corrections: list[RelevanceCorrection] = Field(min_length=1, max_length=100)


@router.post('/{note_id}/relevance')
async def correct_relevance(note_id: str, payload: RelevanceRevision, request: Request, user: AuthUser = Depends(get_current_user)):
    from app.services.transcript_revision import revise_relevance
    container = get_container(request)
    try:
        return await asyncio.to_thread(revise_relevance, container, note_id, actor_for_user(container, user),
            payload.expected_version, [c.model_dump() for c in payload.corrections])
    except NoteLifecycleError as exc:
        raise service_http_error(exc) from exc
