"""Inbound Telnyx voice receptionist — low-latency Urdu appointment booking."""
from __future__ import annotations

import array
import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from security_guardrails import Actor, get_gateway


logger = logging.getLogger(__name__)

_GREETING = (
    "السلام علیکم، میں ثمرہ ہوں، میڈفلو کلینک۔ "
    "اپائنٹمنٹ بک کرانے کے لیے اپنا پورا نام بتائیں۔"
)

_BOOKING_SYSTEM_PROMPT = """\
آپ میڈفلو کلینک کی فون رسیپشنسٹ "ثمرہ" ہیں۔ صرف مختصر اردو میں بات کریں۔
مقصد: مریض کی اپائنٹمنٹ بکنگ کی معلومات اکٹھی کرنا۔
ایک وقت میں صرف ایک سوال پوچھیں (۱ جملہ، زیادہ سے زیادہ ۲)۔
قوسین، انگریزی نوٹ، یا لمبی سوچ مت لکھیں۔

ترتیب:
1) پورا نام
2) عمر
3) فون نمبر (اگر کالَر آئی ڈی پہلے سے معلوم ہو تو تصدیق کریں)
4) پہلی بار؟ ہاں/نہیں
5) پچھلی بیماریاں (نہ ہوں تو "کوئی نہیں")
6) آج کی شکایت
7) شعبہ: جنرل میڈیسن، کارڈیالوجی، پیڈیاٹرکس
8) ڈاکٹر ترجیح (اختیاری) یا خود بخود
9) ملاقات: نیا مریض / فالو اپ / ٹیلی
10) ترجیحی دن/وقت

اگر جواب ادھورا یا غیر واضح ہو تو ایک مختصر وضاحتی سوال پوچھیں۔
شادی، غیر طبی بات، یا بے تعلق موضوع پر اپائنٹمنٹ کا راستہ واپس لائیں۔
جب کافی معلومات ہوں تو خلاصہ سنائیں اور کہیں کہ درخواست ڈاکٹر کو بھیج دی جائے گی۔
"""


class InboundCallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class TranscriptLine:
    role: str
    text: str
    at: str
    interim: bool = False


@dataclass
class LiveCallSession:
    call_control_id: str
    from_number: str
    to_number: str
    direction: str = "incoming"
    status: str = "ringing"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ended_at: str = ""
    transcript: list[TranscriptLine] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    speaking: bool = False
    processing: bool = False
    last_patient_text: str = ""
    last_patient_at: float = 0.0
    # Media stream / VAD
    sample_rate: int = 16000
    pcm_buffer: bytearray = field(default_factory=bytearray)
    speech_started: bool = False
    last_voice_at: float = 0.0
    speech_ms: float = 0.0


class CallMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        # cache_key -> (media_id, extension)
        self._cache: dict[str, tuple[str, str]] = {}

    def save_audio(self, audio: bytes, *, ext: str = "mp3") -> str:
        media_id = uuid.uuid4().hex
        clean_ext = (ext or "mp3").lower().lstrip(".")
        if clean_ext not in {"mp3", "wav"}:
            clean_ext = "mp3"
        path = self.root / f"{media_id}.{clean_ext}"
        path.write_bytes(audio)
        return media_id

    def save_mp3(self, audio: bytes) -> str:
        return self.save_audio(audio, ext="mp3")

    def cached_media(
        self, cache_key: str, audio: bytes, *, ext: str = "mp3"
    ) -> tuple[str, str]:
        existing = self._cache.get(cache_key)
        if existing:
            media_id, cached_ext = existing
            if self.path_for(media_id, ext=cached_ext):
                return media_id, cached_ext
        media_id = self.save_audio(audio, ext=ext)
        self._cache[cache_key] = (media_id, ext)
        return media_id, ext

    def cached_media_id(self, cache_key: str, audio: bytes) -> str:
        media_id, _ext = self.cached_media(cache_key, audio, ext="mp3")
        return media_id

    def path_for(self, media_id: str, *, ext: str | None = None) -> Path | None:
        clean = re.sub(r"[^a-f0-9]", "", (media_id or "").lower())
        if not clean:
            return None
        if ext:
            path = self.root / f"{clean}.{ext.lstrip('.')}"
            return path if path.exists() else None
        for candidate in ("mp3", "wav"):
            path = self.root / f"{clean}.{candidate}"
            if path.exists():
                return path
        return None


class FastUrduTTS:
    """OpenRouter multilingual TTS (Gemini/Grok) with Edge ur-PK fallback."""

    def __init__(
        self,
        media_store: CallMediaStore,
        *,
        openrouter_api_key: str = "",
        openrouter_tts_model: str = "x-ai/grok-voice-tts-1.0",
        openrouter_tts_voice: str = "eve",
    ) -> None:
        self.media_store = media_store
        self.openrouter_api_key = (openrouter_api_key or "").strip()
        self.openrouter_tts_model = (openrouter_tts_model or "").strip() or "x-ai/grok-voice-tts-1.0"
        self.openrouter_tts_voice = (openrouter_tts_voice or "").strip() or "eve"
        self._lock = threading.Lock()

    def media_id_for(self, text: str) -> tuple[str, str]:
        media_id, backend, _ext = self.synthesize(text)
        return media_id, backend

    def synthesize(self, text: str) -> tuple[str, str, str]:
        """Return (media_id, backend, file_extension)."""
        clean = " ".join((text or "").split())
        if not clean:
            raise InboundCallError("EMPTY_TTS", "Nothing to speak")
        key = hashlib.sha1(
            f"{self.openrouter_tts_model}|{self.openrouter_tts_voice}|{clean}".encode("utf-8")
        ).hexdigest()
        with self._lock:
            cached = self.media_store._cache.get(key)
            if cached:
                media_id, ext = cached
                if self.media_store.path_for(media_id, ext=ext):
                    return media_id, f"cache:{self.openrouter_tts_model}", ext
            audio, ext, backend = self._render(clean)
            media_id, saved_ext = self.media_store.cached_media(key, audio, ext=ext)
            return media_id, backend, saved_ext

    def warmup(self, phrases: list[str]) -> None:
        for phrase in phrases:
            try:
                self.synthesize(phrase)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS warmup failed: %s", exc)

    def _render(self, text: str) -> tuple[bytes, str, str]:
        if self.openrouter_api_key:
            attempts = [
                (self.openrouter_tts_model, self.openrouter_tts_voice),
            ]
            # Quality fallbacks if the configured model/voice fails.
            if not self.openrouter_tts_model.startswith("x-ai/grok"):
                attempts.append(("x-ai/grok-voice-tts-1.0", "eve"))
            for model, voice in attempts:
                try:
                    audio, ext = self._openrouter(text, model=model, voice=voice)
                    return audio, ext, f"openrouter:{model}"
                except Exception as exc:  # noqa: BLE001
                    logger.warning("OpenRouter TTS failed (%s / %s): %s", model, voice, exc)
        audio = self._edge(text)
        return audio, "mp3", "edge-ur-PK"

    def _openrouter(self, text: str, *, model: str, voice: str) -> tuple[bytes, str]:
        use_pcm = "gemini" in model.lower()
        response_format = "pcm" if use_pcm else "mp3"
        payload = {
            "model": model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/audio/speech",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://medflow.local",
                "X-Title": "MedFlowAI Urdu Voice Agent",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            raise RuntimeError(f"OpenRouter TTS HTTP {exc.code}: {detail}") from exc
        if not audio:
            raise RuntimeError("OpenRouter TTS returned empty audio")
        if use_pcm:
            return _pcm16_to_wav(audio, sample_rate=24000), "wav"
        return audio, "mp3"

    @staticmethod
    def _edge(text: str) -> bytes:
        import edge_tts

        voice = "ur-PK-UzmaNeural" if re.search(r"[\u0600-\u06ff]", text) else "en-US-JennyNeural"

        async def _run() -> bytes:
            communicate = edge_tts.Communicate(text, voice, rate="+10%", pitch="+0Hz")
            chunks: list[bytes] = []
            async for item in communicate.stream():
                if item["type"] == "audio":
                    chunks.append(item["data"])
            return b"".join(chunks)

        audio = asyncio.run(asyncio.wait_for(_run(), timeout=12))
        if not audio:
            raise RuntimeError("Edge TTS returned empty audio")
        return audio


def _pcm16_rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if not samples:
        return 0.0
    acc = 0
    for sample in samples:
        acc += sample * sample
    return (acc / len(samples)) ** 0.5


def _pcm16_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()


class InboundCallService:
    # VAD tuned for phone barge-in after agent finishes
    SPEECH_RMS = 650.0
    MIN_SPEECH_MS = 350.0
    SILENCE_MS = 700.0
    MAX_UTTERANCE_MS = 9000.0

    def __init__(
        self,
        *,
        api_key: str,
        clinic_number: str,
        webhook_base_url: str,
        openrouter_api_key: str,
        openrouter_stt_model: str,
        openrouter_tts_model: str,
        openrouter_tts_voice: str,
        groq_api_key: str,
        groq_llm_model: str,
        media_store: CallMediaStore,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.clinic_number = (clinic_number or "").strip()
        self.webhook_base_url = (webhook_base_url or "").rstrip("/")
        self.openrouter_api_key = (openrouter_api_key or "").strip()
        self.openrouter_stt_model = openrouter_stt_model or "openai/whisper-large-v3"
        self.openrouter_tts_model = openrouter_tts_model or "x-ai/grok-voice-tts-1.0"
        self.openrouter_tts_voice = openrouter_tts_voice or "eve"
        self.groq_api_key = (groq_api_key or "").strip()
        self.groq_llm_model = groq_llm_model or "qwen/qwen3.8-27b"
        self.media_store = media_store
        self.tts = FastUrduTTS(
            media_store,
            openrouter_api_key=self.openrouter_api_key,
            openrouter_tts_model=self.openrouter_tts_model,
            openrouter_tts_voice=self.openrouter_tts_voice,
        )
        self._sessions: dict[str, LiveCallSession] = {}
        self._stream_to_call: dict[str, str] = {}
        self._lock = threading.RLock()
        threading.Thread(
            target=self.tts.warmup,
            args=(
                [
                    _GREETING,
                    "معذرت، دوبارہ مختصر بتائیے۔",
                    "شکریہ، آپ کی اپائنٹمنٹ کی درخواست نوٹ کر لی گئی ہے۔",
                ],
            ),
            daemon=True,
        ).start()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.webhook_base_url)

    @property
    def stream_url(self) -> str:
        base = self.webhook_base_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :] + "/api/desk/media-stream"
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :] + "/api/desk/media-stream"
        return base.rstrip("/") + "/api/desk/media-stream"

    def status(self) -> dict[str, Any]:
        with self._lock:
            live = sum(1 for s in self._sessions.values() if s.status in {"ringing", "active"})
        return {
            "configured": self.configured,
            "clinic_number": self.clinic_number or None,
            "webhook_base_url": self.webhook_base_url or None,
            "stream_url": self.stream_url,
            "stt": f"openrouter:{self.openrouter_stt_model}",
            "llm": f"groq:{self.groq_llm_model}",
            "tts": f"openrouter:{self.openrouter_tts_model}/{self.openrouter_tts_voice}",
            "live_calls": live,
        }

    def list_live_calls(self) -> list[dict[str, Any]]:
        with self._lock:
            sessions = sorted(self._sessions.values(), key=lambda item: item.started_at, reverse=True)
            return [self._public_session(item) for item in sessions[:30]]

    def get_live_call(self, call_control_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(call_control_id)
            return None if session is None else self._public_session(session)

    def has_session(self, call_control_id: str) -> bool:
        with self._lock:
            return call_control_id in self._sessions

    def handle_webhook(self, body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        event_type = str(data.get("event_type") or body.get("event_type") or "")
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
        call_control_id = str(payload.get("call_control_id") or "")
        direction = str(payload.get("direction") or "").lower()

        if event_type == "call.initiated" and direction in {"incoming", "inbound"}:
            return self._on_initiated(call_control_id, payload)

        if call_control_id and self.has_session(call_control_id):
            if event_type == "call.answered":
                return self._on_answered(call_control_id, payload)
            if event_type in {"call.playback.ended", "call.speak.ended"}:
                return self._on_playback_ended(call_control_id)
            if event_type in {"streaming.started", "call.streaming.started"}:
                return {"ok": True, "action": "streaming_started"}
            if event_type == "call.hangup":
                return self._on_hangup(call_control_id)
            # Ignore legacy Telnyx STT events — OpenRouter STT owns transcription now.
            if event_type == "call.transcription":
                return {"ok": True, "action": "ignored_telnyx_stt"}
            return {"ok": True, "action": "ignored", "event_type": event_type}

        return {"ok": True, "action": "not_inbound", "event_type": event_type}

    def handle_stream_message(self, message: dict[str, Any]) -> None:
        event = str(message.get("event") or "")
        if event == "start":
            start = message.get("start") if isinstance(message.get("start"), dict) else {}
            call_control_id = str(
                start.get("call_control_id")
                or message.get("call_control_id")
                or ""
            )
            stream_id = str(start.get("stream_id") or message.get("stream_id") or "")
            media_format = start.get("media_format") if isinstance(start.get("media_format"), dict) else {}
            sample_rate = int(media_format.get("sample_rate") or media_format.get("sampleRate") or 16000)
            with self._lock:
                if call_control_id and stream_id:
                    self._stream_to_call[stream_id] = call_control_id
                session = self._sessions.get(call_control_id)
                if session is not None:
                    session.sample_rate = sample_rate
            return

        if event != "media":
            return

        media = message.get("media") if isinstance(message.get("media"), dict) else {}
        track = str(media.get("track") or "inbound")
        if track not in {"inbound", "inbound_track"}:
            return
        payload_b64 = media.get("payload")
        if not payload_b64:
            return
        try:
            pcm = base64.b64decode(payload_b64)
        except Exception:  # noqa: BLE001
            return

        stream_id = str(message.get("stream_id") or "")
        call_control_id = ""
        with self._lock:
            call_control_id = self._stream_to_call.get(stream_id, "")
            if not call_control_id:
                # Some payloads include call_control_id on the envelope.
                call_control_id = str(message.get("call_control_id") or "")
            session = self._sessions.get(call_control_id) if call_control_id else None
            if session is None or session.status != "active":
                return
            if session.speaking or session.processing:
                session.pcm_buffer.clear()
                session.speech_started = False
                session.speech_ms = 0.0
                return

            rms = _pcm16_rms(pcm)
            now = time.monotonic()
            frame_ms = (len(pcm) / 2) / max(session.sample_rate, 1) * 1000.0
            if rms >= self.SPEECH_RMS:
                session.speech_started = True
                session.last_voice_at = now
                session.speech_ms += frame_ms
                session.pcm_buffer.extend(pcm)
            elif session.speech_started:
                session.pcm_buffer.extend(pcm)
                silent_for = (now - session.last_voice_at) * 1000.0
                too_long = session.speech_ms >= self.MAX_UTTERANCE_MS
                if (silent_for >= self.SILENCE_MS and session.speech_ms >= self.MIN_SPEECH_MS) or too_long:
                    utterance = bytes(session.pcm_buffer)
                    sample_rate = session.sample_rate
                    session.pcm_buffer.clear()
                    session.speech_started = False
                    session.speech_ms = 0.0
                    session.processing = True
                    threading.Thread(
                        target=self._process_utterance_audio,
                        args=(call_control_id, utterance, sample_rate),
                        daemon=True,
                    ).start()

    def _on_initiated(self, call_control_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        from_number = str(payload.get("from") or payload.get("caller_id_number") or "")
        to_number = str(payload.get("to") or self.clinic_number or "")
        with self._lock:
            self._sessions[call_control_id] = LiveCallSession(
                call_control_id=call_control_id,
                from_number=from_number,
                to_number=to_number,
                status="ringing",
            )
        self._telnyx("POST", f"/calls/{call_control_id}/actions/answer", {})
        return {"ok": True, "action": "answered"}

    def _on_answered(self, call_control_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(call_control_id)
            if session is None:
                session = LiveCallSession(
                    call_control_id=call_control_id,
                    from_number=str(payload.get("from") or ""),
                    to_number=str(payload.get("to") or self.clinic_number or ""),
                )
                self._sessions[call_control_id] = session
            session.status = "active"
            caller = session.from_number

        # Start inbound media stream for OpenRouter STT (same family as Module 2 scribe).
        try:
            self._telnyx(
                "POST",
                f"/calls/{call_control_id}/actions/streaming_start",
                {
                    "stream_url": self.stream_url,
                    "stream_track": "inbound_track",
                    "stream_codec": "L16",
                },
            )
        except InboundCallError as exc:
            logger.error("streaming_start failed: %s", exc)

        # Seed caller-id hint for booking flow.
        if caller:
            with self._lock:
                session = self._sessions.get(call_control_id)
                if session is not None and not session.history:
                    session.history.append(
                        {
                            "role": "system",
                            "content": f"کالر آئی ڈی فون نمبر: {caller}",
                        }
                    )

        self._speak(call_control_id, _GREETING, role="agent")
        return {"ok": True, "action": "greeted_streaming"}

    def _process_utterance_audio(self, call_control_id: str, pcm: bytes, sample_rate: int) -> None:
        try:
            if len(pcm) < sample_rate:  # < ~0.5s
                with self._lock:
                    session = self._sessions.get(call_control_id)
                    if session is not None:
                        session.processing = False
                return

            wav_bytes = _pcm16_to_wav(pcm, sample_rate=sample_rate)
            text = self._stt_openrouter(wav_bytes)
            text = " ".join((text or "").split())
            if not text or len(text) < 2:
                with self._lock:
                    session = self._sessions.get(call_control_id)
                    if session is not None:
                        session.processing = False
                return

            with self._lock:
                session = self._sessions.get(call_control_id)
                if session is None:
                    return
                if text == session.last_patient_text and (time.monotonic() - session.last_patient_at) < 1.8:
                    session.processing = False
                    return
                session.last_patient_text = text
                session.last_patient_at = time.monotonic()
                session.transcript.append(
                    TranscriptLine(
                        role="patient",
                        text=text,
                        at=datetime.now(timezone.utc).isoformat(),
                        interim=False,
                    )
                )
                session.history.append({"role": "user", "content": text})

            reply = self._llm_reply(call_control_id)
            if not reply:
                reply = "براہ کرم مختصر بتائیں — آپ کا نام کیا ہے؟"
            self._speak(call_control_id, reply, role="agent")
        except Exception:  # noqa: BLE001
            logger.exception("Utterance pipeline failed")
            try:
                self._speak(call_control_id, "معذرت، دوبارہ مختصر بتائیے۔", role="agent")
            except Exception:  # noqa: BLE001
                logger.exception("Fallback speak failed")
            with self._lock:
                session = self._sessions.get(call_control_id)
                if session is not None:
                    session.processing = False
                    session.speaking = False

    def _stt_openrouter(self, wav_bytes: bytes) -> str:
        from app.services.demo_stt import DEMO_STT_PROMPT

        gateway = get_gateway()
        actor = Actor(
            actor_id="inbound-phone-agent",
            role="receptionist",
            authorized_patient_ids={"*"},
            current_patient_id="",
        )
        attempts: list[tuple[str, str]] = []
        if self.groq_api_key:
            attempts.append(("groq", "whisper-large-v3"))
        attempts.append(("openrouter", self.openrouter_stt_model))
        last_error: Exception | None = None
        for provider, model in attempts:
            try:
                text = gateway.transcribe_audio(
                    task_type="stt_intake",
                    audio_bytes=wav_bytes,
                    actor=actor,
                    provider=provider,
                    model=model,
                    language="ur",
                    prompt=DEMO_STT_PROMPT,
                    response_format="text",
                )
                if (text or "").strip():
                    return text.strip()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("Inbound STT failed (%s/%s): %s", provider, model, exc)
        if last_error is not None:
            raise last_error
        return ""

    def _llm_reply(self, call_control_id: str) -> str:
        with self._lock:
            session = self._sessions.get(call_control_id)
            history = list(session.history) if session else []
        messages = [{"role": "system", "content": _BOOKING_SYSTEM_PROMPT}, *history[-10:]]

        # Prefer Groq for low latency; fall back to OpenRouter mini.
        if self.groq_api_key:
            try:
                return self._chat_completion(
                    url="https://api.groq.com/openai/v1/chat/completions",
                    api_key=self.groq_api_key,
                    model=self.groq_llm_model,
                    messages=messages,
                    timeout=8,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Groq LLM failed: %s", exc)
        if self.openrouter_api_key:
            return self._chat_completion(
                url="https://openrouter.ai/api/v1/chat/completions",
                api_key=self.openrouter_api_key,
                model="openai/gpt-4o-mini",
                messages=messages,
                timeout=10,
            )
        return "براہ کرم اپنا نام بتائیں۔"

    @staticmethod
    def _chat_completion(
        *,
        url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        timeout: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 70,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://medflow.local",
                "X-Title": "MedFlowAI Inbound Receptionist",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        content = re.sub(r"\([^)]*\)", "", content)
        content = re.sub(r"\s+", " ", content).strip()
        # Keep TTS short
        if len(content) > 180:
            content = content[:180].rsplit(" ", 1)[0]
        return content

    def _on_playback_ended(self, call_control_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(call_control_id)
            if session is not None:
                session.speaking = False
                session.processing = False
                session.pcm_buffer.clear()
                session.speech_started = False
                session.speech_ms = 0.0
        return {"ok": True, "action": "ready_for_patient"}

    def _on_hangup(self, call_control_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(call_control_id)
            if session is not None:
                session.status = "ended"
                session.ended_at = datetime.now(timezone.utc).isoformat()
                session.speaking = False
                session.processing = False
            stale = [sid for sid, cid in self._stream_to_call.items() if cid == call_control_id]
            for sid in stale:
                self._stream_to_call.pop(sid, None)
        return {"ok": True, "action": "ended"}

    def _speak(self, call_control_id: str, text: str, *, role: str) -> None:
        media_id, backend, ext = self.tts.synthesize(text)
        media_url = f"{self.webhook_base_url}/api/desk/media/{media_id}.{ext}"
        with self._lock:
            session = self._sessions.get(call_control_id)
            if session is not None:
                session.speaking = True
                session.processing = True
                session.pcm_buffer.clear()
                session.speech_started = False
                session.transcript.append(
                    TranscriptLine(
                        role=role,
                        text=text,
                        at=datetime.now(timezone.utc).isoformat(),
                        interim=False,
                    )
                )
                if role == "agent":
                    # Avoid duplicating the seeded greeting if already last assistant turn.
                    if not session.history or session.history[-1].get("content") != text:
                        session.history.append({"role": "assistant", "content": text})
        try:
            self._telnyx(
                "POST",
                f"/calls/{call_control_id}/actions/playback_start",
                {
                    "audio_url": media_url,
                    "overlay": False,
                    "target_legs": "self",
                },
            )
            logger.info("Played %s (%s)", backend, text[:48])
        except InboundCallError as exc:
            logger.warning("playback_start failed (%s); Telnyx speak fallback", exc)
            self._telnyx(
                "POST",
                f"/calls/{call_control_id}/actions/speak",
                {
                    "payload": text,
                    "payload_type": "text",
                    "service_level": "premium",
                    "voice": "female",
                    "language": "hi-IN",
                },
            )

    def _telnyx(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telnyx.com/v2{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise InboundCallError("TELNYX_API_ERROR", f"Telnyx request failed ({exc.code}): {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise InboundCallError("TELNYX_NETWORK_ERROR", f"Telnyx network error: {exc.reason}") from exc

    @staticmethod
    def _public_session(session: LiveCallSession) -> dict[str, Any]:
        return {
            "call_control_id": session.call_control_id,
            "from_number": session.from_number,
            "to_number": session.to_number,
            "direction": session.direction,
            "status": session.status,
            "started_at": session.started_at,
            "ended_at": session.ended_at or None,
            "speaking": session.speaking,
            "transcript": [
                {
                    "role": line.role,
                    "text": line.text,
                    "at": line.at,
                    "interim": line.interim,
                }
                for line in session.transcript
            ],
        }
