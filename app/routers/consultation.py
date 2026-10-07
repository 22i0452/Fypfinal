from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dependencies import actor_for_user, websocket_user
from app.services import ClinicLifecycleError, ConsentError, DocumentationError
from medflow.domain.ids import new_id
from medflow.orchestration import WorkflowAction
from security_guardrails import Actor
from security_guardrails.telemetry import collect_provider_events
from security_guardrails.audio_retention import cleanup_audio_session


router = APIRouter(tags=["consultation"])
SAMPLE_RATE = 16_000


@router.websocket("/ws")
async def consultation_websocket(websocket: WebSocket):
    await websocket.accept()
    user = websocket_user(websocket)
    if user is None:
        await websocket.send_json({"type": "error", "code": "AUTHENTICATION_REQUIRED", "message": "Sign in before opening a consultation."})
        await websocket.close(code=4401)
        return

    container = websocket.app.state.container
    session: dict[str, Any] = {
        "recording": False,
        "audio_chunks": [],
        "patient_id": "",
        "workflow_id": "",
        "encounter_id": "",
        "input_sample_rate": SAMPLE_RATE,
        "audio_retention_consent": False,
        "audio_retention_requested": False,
        "audio_retention_days": 30,
        "template_id": "TPL-GP-01",
    }

    connection_open = True

    async def send(payload: dict[str, Any]) -> None:
        nonlocal connection_open
        if not connection_open:
            return
        encoded = json.dumps({
            "patient_id": session.get("patient_id", ""),
            "workflow_id": session.get("workflow_id", ""),
            "encounter_id": session.get("encounter_id", ""),
            "capture_id": session.get("capture_id", ""),
            **payload,
        })
        try:
            await websocket.send_text(encoded)
        except (WebSocketDisconnect, RuntimeError):
            # A page reload must not discard a submitted recording or its draft.
            connection_open = False

    async def start_recording(message: dict[str, Any]) -> None:
        patient_id = str(message.get("patient_id") or "").strip()
        workflow_id = str(message.get("workflow_id") or "").strip()
        encounter_id = str(message.get("encounter_id") or "").strip()
        template_id = str(message.get("template_id") or "TPL-GP-01").strip()
        if session["recording"]:
            await send({"type": "error", "code": "RECORDING_ACTIVE", "message": "Finish the active recording before starting another."})
            return
        session.update({"patient_id": patient_id, "workflow_id": workflow_id, "encounter_id": encounter_id,
                        "capture_id": str(message.get("capture_id") or "")[:64]})
        if not patient_id or not workflow_id or not encounter_id:
            await send(
                {
                    "type": "error",
                    "code": "CONSULTATION_CONTEXT_REQUIRED",
                    "message": "Verify, book, check in, and record consent before recording.",
                }
            )
            return
        actor = actor_for_user(container, user, patient_id)
        try:
            template = container.template_service.require_active(template_id)
            authorization = container.consent_service.authorize_audio_start(
                encounter_id=encounter_id,
                workflow_id=workflow_id,
                patient_id=patient_id,
                actor=actor,
            )
            context = container.lifecycle_service.start_consultation(workflow_id, actor=actor)
        except (ConsentError, ClinicLifecycleError, ValueError) as exc:
            container.audit_service.record(
                "recording_start_denied",
                actor_ref=actor.ref,
                action="start_recording",
                patient_ref=patient_id,
                resource_ref=encounter_id,
                result="deny",
                metadata={"reason_code": str(getattr(exc, "code", "REQUEST_REJECTED"))},
            )
            await send(
                {
                    "type": "error",
                    "code": str(getattr(exc, "code", "REQUEST_REJECTED")),
                    "message": str(exc),
                }
            )
            return
        patient = container.patient_repository.get(patient_id)
        if patient is None or context.encounter.encounter_id != encounter_id:
            await send({"type": "error", "code": "PATIENT_NOT_FOUND", "message": "Consultation patient is unavailable."})
            return
        try:
            sample_rate = int(message.get("sample_rate") or SAMPLE_RATE)
        except (TypeError, ValueError):
            sample_rate = SAMPLE_RATE
        session.update(
            {
                "recording": True,
                "audio_chunks": [],
                "patient_id": patient_id,
                "workflow_id": workflow_id,
                "encounter_id": encounter_id,
                "patient": patient,
                "input_sample_rate": max(8_000, min(sample_rate, 192_000)),
                "audio_retention_consent": authorization.retain_audio,
                "audio_retention_requested": authorization.retain_audio,
                "template_id": template.template_id,
            }
        )
        await send(
            {
                "type": "recording_started",
                "workflow_id": workflow_id,
                "encounter_id": encounter_id,
                "audio_retention": authorization.retain_audio,
                "template_id": template.template_id,
            }
        )

    async def process_recording() -> None:
        patient_id = str(session.get("patient_id") or "")
        workflow_id = str(session.get("workflow_id") or "")
        encounter_id = str(session.get("encounter_id") or "")
        actor = actor_for_user(container, user, patient_id)
        if not session["audio_chunks"]:
            cleanup_audio_session(session, patient_ref=patient_id, allow_retention=False)
            await send({"type": "error", "code": "AUDIO_EMPTY", "message": "No audio was recorded."})
            return
        run_id = container.process_trace.start(patient_id, encounter_id, str(session.get("capture_id") or ""))
        stage = "audio"
        started = time.perf_counter()

        provider_calls = []

        async def call_provider(function, *args, **kwargs):
            nonlocal provider_calls
            with collect_provider_events() as calls:
                try:
                    return await asyncio.to_thread(function, *args, **kwargs)
                finally:
                    provider_calls = calls

        async def trace(name, status, artifact=None):
            nonlocal stage, started
            if status == "running":
                stage, started = name, time.perf_counter()
            if status == "running":
                provider_calls.clear()
            elif provider_calls:
                artifact = {**(artifact or {}), "provider_calls":list(provider_calls)}
            event = container.process_trace.append(run_id, name, status, artifact=artifact, duration_ms=(time.perf_counter()-started)*1000 if status != "running" else None)
            await send({"type":"process_event", **event})

        try:
            container.lifecycle_service.start_documentation(workflow_id, actor=actor)
            await trace("audio", "running")
            audio = np.concatenate(session["audio_chunks"])
            sample_rate = int(session["input_sample_rate"])
            duration = len(audio) / max(sample_rate, 1)
            await trace("audio", "complete", {"seconds":round(duration,2), "sample_rate":sample_rate, "samples":len(audio), "retained":bool(session["audio_retention_consent"])})
            await trace("speech", "running")
            await send({"type": "processing", "message": f"Transcribing and cleaning {duration:.1f}s audio..."})
            transcript_text = await call_provider(
                container.documentation_service.transcribe,
                audio,
                input_sample_rate=sample_rate,
                patient_id=patient_id,
            )
            if len(transcript_text.strip()) < 10:
                raise DocumentationError("NO_SPEECH", "No speech was detected in the recording.")

            await trace("speech", "complete", {"text":transcript_text, "language":"Urdu", "mode":"After-stop transcription and cleanup"})
            await trace("roles", "running")
            patient = session["patient"]
            transcript_id = new_id("TRN")
            await send({"type": "processing", "message": "Identifying speakers (doctor, patient, nurse, attendants)..."})
            diarized = await call_provider(
                container.documentation_service.diarize,
                transcript_text,
                patient=patient,
                transcript_id=transcript_id,
            )
            urdu_payload = [container.documentation_service.utterance_payload(item) for item in diarized]
            await trace("roles", "complete", {"utterances":urdu_payload, "method":"Text-based role attribution", "distinct_voices":None})
            await send(
                {
                    "type": "transcript_complete",
                    "transcript_id": transcript_id,
                    "urdu_conversation": urdu_payload,
                }
            )

            await trace("translation", "running")
            await send({"type": "processing", "message": "Translating transcript to English..."})
            translated = await call_provider(
                container.documentation_service.translate,
                diarized,
                patient=patient,
            )
            transcript = container.documentation_service.save_transcript(
                transcript_id=transcript_id,
                patient_id=patient_id,
                encounter_id=encounter_id,
                utterances=translated,
            )
            english_payload = [
                container.documentation_service.utterance_payload(item, translated=True)
                for item in translated
            ]
            await trace("translation", "complete", {"utterances":english_payload, "paired_ids":[item.utterance_id for item in translated]})
            await send({"type": "translation_complete", "english_conversation": english_payload})
            await trace("draft", "running")

            await send({"type": "processing", "message": "Generating an evidence-linked SOAP draft..."})
            draft = await call_provider(
                container.documentation_service.generate_draft,
                workflow_id=workflow_id,
                patient=patient,
                encounter_id=encounter_id,
                transcript=transcript,
                actor=actor,
                template_id=str(session.get("template_id") or "TPL-GP-01"),
            )
            await trace("draft", "complete", {"note_id":draft.note.note_id, "generation_mode":draft.legacy_soap.get("generation_mode", "MODEL_VALIDATED"), "soap":container.documentation_service.legacy_soap(draft.version.soap)})
            await trace("validation", "running")
            valid_ids = {item.utterance_id for item in translated}
            claims = [claim for key in ("subjective", "objective", "assessment", "plan") for claim in getattr(draft.version.soap, key)]
            if any(ref not in valid_ids for claim in claims for ref in claim.evidence_ids):
                raise DocumentationError("UNKNOWN_EVIDENCE", "Unknown evidence reference")
            from app.services.evidence_checks import note_evidence_report
            evidence_report = note_evidence_report(draft.version.soap, transcript, state=draft.version.status, version=draft.version.version_number, note_id=draft.note.note_id)
            draft.legacy_soap["evidence_report"] = evidence_report
            await trace("validation", "complete", {"evidence_report":evidence_report, "known_references":True, "claim_count":len(claims), "linked_claims":sum(bool(item.evidence_ids) for item in claims), "warnings":draft.version.soap.warnings, "missing_information":draft.version.soap.missing_information, "clinician_approval":"Required", "version":draft.version.version_number})
            audio_metadata = cleanup_audio_session(
                session,
                patient_ref=patient_id,
                note_ref=draft.note.note_id,
            )
            await send(
                {
                    "type": "soap_note",
                    "note_id": draft.note.note_id,
                    "note_state": draft.note.state.value,
                    "soap": {**draft.legacy_soap, "audio_retention": audio_metadata},
                    "urdu_transcript": urdu_payload,
                    "english_transcript": english_payload,
                }
            )
        except Exception as exc:
            await trace(stage, "failed", {"code":str(getattr(exc,"code","DOCUMENTATION_FAILED")), "message":"Processing interrupted. Retry from this encounter."})
            cleanup_audio_session(session, patient_ref=patient_id, allow_retention=False)
            print(f"[Documentation] failed safely ({type(exc).__name__})")
            try:
                workflow = container.workflow_repository.get(workflow_id)
                if workflow:
                    container.workflow_orchestrator.perform_action(
                        workflow_id,
                        WorkflowAction.MARK_FAILED,
                        actor=Actor.system("system_agent", patient_id),
                        expected_version=workflow.version,
                        error_code=str(getattr(exc, "code", "DOCUMENTATION_FAILED")),
                    )
            except Exception:
                pass
            container.audit_service.record(
                "documentation_failed",
                actor_ref=actor.ref,
                action="process_documentation",
                patient_ref=patient_id,
                resource_ref=encounter_id,
                result="deny",
                metadata={"reason_code": str(getattr(exc, "code", "DOCUMENTATION_FAILED"))},
            )
            await send(
                {
                    "type": "error",
                    "code": str(getattr(exc, "code", "DOCUMENTATION_FAILED")),
                    "message": "Clinical documentation processing failed safely.",
                }
            )

    try:
        while True:
            if not connection_open:
                break
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                if session["recording"]:
                    chunk = np.frombuffer(message["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                    session["audio_chunks"].append(chunk)
                continue
            raw_text = message.get("text")
            if raw_text is None:
                continue
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                await send({"type": "error", "code": "INVALID_MESSAGE", "message": "Invalid WebSocket message."})
                continue
            message_type = str(payload.get("type") or "")
            if message_type == "ping":
                await send({"type": "pong"})
            elif message_type == "start":
                await start_recording(payload)
            elif message_type == "stop":
                if session["recording"]:
                    session["recording"] = False
                    await process_recording()
            else:
                await send({"type": "error", "code": "UNSUPPORTED_MESSAGE", "message": "Unsupported WebSocket message."})
    except WebSocketDisconnect:
        pass
    finally:
        cleanup_audio_session(
            session,
            patient_ref=str(session.get("patient_id") or ""),
            allow_retention=False,
        )
