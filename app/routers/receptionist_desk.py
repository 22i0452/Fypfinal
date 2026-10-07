"""Public receptionist desk UI on the main Medflow port."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.dependencies import get_container
from app.routers.common import service_http_error
from app.routers.receptionist import BookingPayload, IntakePayload, IntakeUpdatePayload
from app.services import (
    AppointmentError,
    ClinicLifecycleError,
    ConfirmationCallError,
    InboundCallError,
    ReceptionistBooking,
    ReceptionistIntake,
    ReceptionistIntegrationError,
)
from app.services.demo_call_service import DemoCallError
from security_guardrails import Actor, get_gateway
from medflow.orchestration import (
    WorkflowAccessError,
    WorkflowConflictError,
    WorkflowNotFoundError,
    WorkflowTransitionError,
)


ROOT = Path(__file__).resolve().parents[2]
RECEPTIONIST_WEB_DIR = ROOT / "receptionist" / "web"

router = APIRouter(tags=["receptionist-desk"])


class DemoStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario_id: str = Field(min_length=3, max_length=64)


class DemoTurnPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario_id: str = Field(min_length=3, max_length=64)
    user_message: str = Field(min_length=1, max_length=800)
    history: list[dict[str, str]] = Field(default_factory=list)


class DemoFinishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scenario_id: str = Field(min_length=3, max_length=64)
    history: list[dict[str, str]] = Field(default_factory=list)


class DemoTtsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=800)


def _service_error(error: Exception):
    return service_http_error(error)


@router.get("/Receptionist")
@router.get("/receptionist")
async def receptionist_desk_page():
    index = RECEPTIONIST_WEB_DIR / "index.html"
    if not index.exists():
        return RedirectResponse("/", status_code=302)
    return FileResponse(index, media_type="text/html")


@router.get("/api/desk/health")
async def desk_health(request: Request):
    container = get_container(request)
    return {
        "ok": True,
        "service": "receptionist-desk",
        "token_configured": bool(container.settings.receptionist_service_token),
        "inbound_calls": container.inbound_call_service.status(),
        "clinic_number": container.settings.telnyx_number or None,
    }


@router.get("/api/desk/configuration")
async def desk_configuration(request: Request):
    try:
        return get_container(request).receptionist_integration_service.configuration()
    except ReceptionistIntegrationError as exc:
        raise _service_error(exc) from exc


@router.get("/api/desk/availability")
async def desk_availability(
    request: Request,
    practitioner_id: str = Query(min_length=3, max_length=64),
    visit_type_id: str = Query(min_length=3, max_length=64),
    start_date: date | None = None,
    days: int = Query(default=14, ge=1, le=30),
    limit: int = Query(default=12, ge=1, le=30),
):
    try:
        return get_container(request).receptionist_integration_service.availability(
            practitioner_id=practitioner_id,
            visit_type_id=visit_type_id,
            start_date=start_date,
            days=days,
            limit=limit,
        )
    except (ReceptionistIntegrationError, AppointmentError) as exc:
        raise _service_error(exc) from exc


@router.post("/api/desk/intakes")
async def desk_create_intake(payload: IntakePayload, request: Request):
    try:
        service = get_container(request).receptionist_integration_service
        intake = ReceptionistIntake(**payload.model_dump())
        result = service.create_intake(intake)
        if result.get("requires_update"):
            return service.update_intake(
                patient_id=str(result["patient_id"]),
                workflow_id=str(result["workflow_id"]),
                expected_revision=int(result["revision"]),
                intake=ReceptionistIntake(
                    **{
                        **payload.model_dump(),
                        "revision": int(result["revision"]) + 1,
                        "confirmed_revision": int(result["revision"]) + 1,
                    }
                ),
            )
        return result
    except (
        ReceptionistIntegrationError,
        ClinicLifecycleError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowTransitionError,
    ) as exc:
        raise _service_error(exc) from exc


@router.patch("/api/desk/intakes/{patient_id}")
async def desk_update_intake(patient_id: str, payload: IntakeUpdatePayload, request: Request):
    try:
        return get_container(request).receptionist_integration_service.update_intake(
            patient_id=patient_id,
            workflow_id=payload.workflow_id,
            expected_revision=payload.expected_revision,
            intake=ReceptionistIntake(
                name=payload.name,
                age_text=payload.age_text,
                phone_number=payload.phone_number,
                first_visit=payload.first_visit,
                past_medical_history=payload.past_medical_history,
                current_complaint=payload.current_complaint,
                intake_token=payload.intake_token,
                revision=payload.revision,
                confirmed_revision=payload.confirmed_revision,
            ),
        )
    except (
        ReceptionistIntegrationError,
        ClinicLifecycleError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowTransitionError,
    ) as exc:
        raise _service_error(exc) from exc


@router.post("/api/desk/bookings")
async def desk_book(payload: BookingPayload, request: Request):
    try:
        return get_container(request).receptionist_integration_service.book(
            ReceptionistBooking(**payload.model_dump())
        )
    except (
        ReceptionistIntegrationError,
        AppointmentError,
        ClinicLifecycleError,
        WorkflowAccessError,
        WorkflowConflictError,
        WorkflowNotFoundError,
        WorkflowTransitionError,
    ) as exc:
        raise _service_error(exc) from exc


@router.get("/api/desk/demo-scenarios")
async def desk_demo_scenarios(request: Request):
    return get_container(request).demo_call_service.list_scenarios()


@router.post("/api/desk/demo-calls/start")
async def desk_demo_start(payload: DemoStartPayload, request: Request):
    try:
        return get_container(request).demo_call_service.start(payload.scenario_id)
    except DemoCallError as exc:
        raise _service_error(exc) from exc


@router.post("/api/desk/demo-calls/turn")
async def desk_demo_turn(payload: DemoTurnPayload, request: Request):
    try:
        return get_container(request).demo_call_service.turn(
            scenario_id=payload.scenario_id,
            history=payload.history,
            user_message=payload.user_message,
        )
    except DemoCallError as exc:
        raise _service_error(exc) from exc


@router.post("/api/desk/demo-calls/finish")
async def desk_demo_finish(payload: DemoFinishPayload, request: Request):
    container = get_container(request)
    try:
        return container.demo_call_service.finish(
            scenario_id=payload.scenario_id,
            history=payload.history,
            integration=container.receptionist_integration_service,
        )
    except (DemoCallError, ClinicLifecycleError, WorkflowAccessError, WorkflowConflictError,
            WorkflowNotFoundError, WorkflowTransitionError) as exc:
        raise _service_error(exc) from exc


@router.post("/api/desk/demo-calls/stt")
async def desk_demo_stt(request: Request, audio: UploadFile = File(...)):
    from app.services.demo_stt import DEMO_STT_PROMPT, looks_garbled_urdu, wav_bytes_from_upload

    raw = await audio.read()
    if not raw:
        raise _service_error(DemoCallError("EMPTY_AUDIO", "No audio received"))
    wav_bytes = wav_bytes_from_upload(raw)
    gateway = get_gateway()
    actor = Actor(
        actor_id="demo-call-ui",
        role="receptionist",
        authorized_patient_ids={"*"},
        current_patient_id="",
    )
    settings = get_container(request).settings
    # Prefer Groq Whisper (same medical family, much lower latency), then OpenRouter Whisper.
    attempts: list[tuple[str, str]] = []
    if settings.groq_api_key:
        attempts.append(("groq", "whisper-large-v3"))
    attempts.append(("openrouter", settings.openrouter_stt_model or "openai/whisper-large-v3"))
    text = ""
    used_provider = ""
    last_error: Exception | None = None
    for provider, model in attempts:
        try:
            text = gateway.transcribe_audio(
                task_type="stt_intake",
                audio_bytes=wav_bytes or raw,
                actor=actor,
                provider=provider,
                model=model,
                language="ur",
                prompt=DEMO_STT_PROMPT,
                response_format="text",
            )
            if (text or "").strip():
                used_provider = f"{provider}/{model}"
                break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            text = ""
    clean = (text or "").strip()
    if not clean:
        raise _service_error(
            DemoCallError("STT_FAILED", str(last_error) if last_error else "Demo STT failed")
        )
    if looks_garbled_urdu(clean):
        return {
            "text": "",
            "garbled": True,
            "hint": "آواز واضح نہیں ملی۔ دوبارہ آہستہ اور صاف بولیں۔ / Speech unclear — please speak again clearly.",
        }
    return {"text": clean, "provider": used_provider}


@router.post("/api/desk/demo-calls/tts")
async def desk_demo_tts(payload: DemoTtsPayload, request: Request):
    """Synthesize Urdu speech for demo voice-call mode (OpenRouter Gemini/Grok)."""
    from app.services.demo_call_service import DemoCallService

    speech = DemoCallService.urdu_for_speech(payload.text)
    if not speech:
        raise _service_error(DemoCallError("EMPTY_TTS", "Nothing to speak"))
    try:
        media_id, backend, ext = get_container(request).inbound_call_service.tts.synthesize(speech)
    except Exception as exc:  # noqa: BLE001
        raise _service_error(DemoCallError("TTS_FAILED", str(exc) or "Demo TTS failed")) from exc
    return {
        "media_id": media_id,
        "audio_url": f"/api/desk/media/{media_id}.{ext}",
        "speech_text": speech,
        "backend": backend,
        "format": ext,
    }


@router.get("/api/desk/live-calls")
async def desk_live_calls(request: Request):
    return {"calls": get_container(request).inbound_call_service.list_live_calls()}


@router.get("/api/desk/live-calls/{call_control_id}")
async def desk_live_call_detail(call_control_id: str, request: Request):
    session = get_container(request).inbound_call_service.get_live_call(call_control_id)
    if session is None:
        raise _service_error(InboundCallError("CALL_NOT_FOUND", "Live call not found"))
    return session


@router.get("/api/desk/media/{media_filename}")
async def desk_call_media(media_filename: str, request: Request):
    name = (media_filename or "").strip()
    if "." in name:
        media_id, ext = name.rsplit(".", 1)
    else:
        media_id, ext = name, ""
    ext = ext.lower()
    if ext and ext not in {"mp3", "wav"}:
        return Response(status_code=404, content="Media not found")
    path = get_container(request).inbound_call_service.media_store.path_for(
        media_id,
        ext=ext or None,
    )
    if path is None:
        return Response(status_code=404, content="Media not found")
    media_type = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.websocket("/api/desk/media-stream")
async def desk_media_stream(websocket: WebSocket):
    """Telnyx inbound audio stream → OpenRouter STT utterance pipeline."""
    await websocket.accept()
    service = websocket.app.state.container.inbound_call_service
    try:
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict):
                service.handle_stream_message(message)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            return


@router.post("/api/webhooks/telnyx")
async def telnyx_voice_webhook(request: Request) -> dict[str, Any]:
    """Telnyx Call Control webhook — must be publicly reachable via ngrok."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}

    container = get_container(request)
    try:
        inbound_result = container.inbound_call_service.handle_webhook(body)
        if inbound_result.get("action") != "not_inbound":
            return inbound_result
        return container.confirmation_call_service.handle_webhook(body)
    except (InboundCallError, ConfirmationCallError) as exc:
        return {"ok": False, "code": exc.code, "message": str(exc)}
