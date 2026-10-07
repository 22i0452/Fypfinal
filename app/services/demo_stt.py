"""Demo voice-call STT helpers (WAV prep + medical-style Whisper)."""
from __future__ import annotations

import io
import logging
import re
import wave

import numpy as np

from receptionist.urdu_stt_utils import normalize_text, resample_audio


logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000

# Same Whisper family as medical Module 2; Urdu Nastaliq + clinic vocabulary.
DEMO_STT_PROMPT = "پاکستانی اردو، English، میڈفلو کلینک، جنرل میڈیسن، کارڈیالوجی، پیڈیاٹرکس۔"


def contextual_stt_prompt(field: str = "") -> str:
    # Vocabulary bias only: instructions and sample answers can be hallucinated.
    hints = {"name": "نام", "age": "عمر", "phone": "فون نمبر",
             "department": "شعبہ", "doctor": "ڈاکٹر", "time": "دن، وقت"}
    return DEMO_STT_PROMPT + (" " + hints[field] if field in hints else "")


def transcript_issue(text: str) -> str:
    clean = normalize_text(text)
    echo = ("اردو رسم خط میں لکھیں", "اردو رسم الخط میں لکھیں",
            "صرف بولی گئی بات", "رومن اردو مت لکھیں", "transcribe only the exact spoken words")
    if any(marker in clean.lower() for marker in echo):
        return "prompt_echo"
    return "uncertain_transcript" if looks_garbled_urdu(clean) else ""


def audio_metrics(audio_bytes: bytes) -> dict:
    """Measure original PCM, before normalization; never call this a speech score."""
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as handle:
            rate, channels, width = handle.getframerate(), handle.getnchannels(), handle.getsampwidth()
            if width != 2:
                return {}
            samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if not samples.size:
            return {"duration_ms": 0, "rms": 0.0, "peak": 0.0}
        return {"duration_ms": round(samples.size / channels / rate * 1000),
                "rms": float(np.sqrt(np.mean(samples * samples))),
                "peak": float(np.max(np.abs(samples)))}
    except (wave.Error, EOFError, ValueError):
        return {}


def sniff_audio_format(audio_bytes: bytes) -> str:
    head = audio_bytes[:16] if audio_bytes else b""
    if head.startswith(b"RIFF") and b"WAVE" in audio_bytes[:12]:
        return "wav"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"\x1aE\xdf\xa3") or head.startswith(b"\x1aE\xdf\xa3"):
        return "webm"
    if len(head) >= 4 and head[0:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head.startswith(b"fLaC"):
        return "flac"
    # EBML / webm often
    if b"webm" in audio_bytes[:64].lower() or b"opus" in audio_bytes[:64].lower():
        return "webm"
    return "bin"


def wav_bytes_from_upload(audio_bytes: bytes) -> bytes:
    """Normalize uploaded mic audio to 16 kHz mono PCM WAV when possible."""
    if not audio_bytes:
        return b""
    fmt = sniff_audio_format(audio_bytes)
    if fmt == "wav":
        try:
            return _normalize_wav(audio_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WAV normalize failed: %s", exc)
            return audio_bytes
    # Browser should send WAV now; keep original with correct type for provider fallback.
    return audio_bytes


def _normalize_wav(audio_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(audio_bytes), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frame_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if sample_width != 2:
        raise ValueError(f"Unsupported sample width: {sample_width}")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if frame_rate != SAMPLE_RATE:
        samples = resample_audio(samples, frame_rate, SAMPLE_RATE)
    # Preserve quiet input. Peak normalization previously amplified tiny noise
    # to full scale. Bound gain to 4x and never amplify near-silence.
    samples = samples - float(np.mean(samples)) if samples.size else samples
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 0.002:
        samples = samples * min(4.0, 0.95 / peak)
    return _float_to_wav_bytes(samples, SAMPLE_RATE)


def _float_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def looks_garbled_urdu(text: str) -> bool:
    """Heuristic for clearly broken STT (e.g. nonsense syllable salad)."""
    clean = normalize_text(text)
    if not clean:
        return True
    urdu_words = re.findall(r"[\u0600-\u06FF]{2,}", clean)
    # Names, yes/no confirmations and ages are legitimately one short token.
    # Grammar/meaning belongs to BookingFlow, which can ask for clarification.
    if not re.search(r"[A-Za-z؀-ۿݐ-ݿ\d]", clean):
        return True
    # High ratio of rare/unlikely token patterns from bad Whisper hallucinations
    nonsense_hits = 0
    for token in urdu_words:
        if len(token) >= 6 and re.search(r"(.)\1{2,}", token):
            nonsense_hits += 1
    if nonsense_hits >= 2:
        return True
    return False


def stt_filename_and_mime(audio_bytes: bytes) -> tuple[str, str]:
    fmt = sniff_audio_format(audio_bytes)
    mapping = {
        "wav": ("audio.wav", "audio/wav"),
        "webm": ("audio.webm", "audio/webm"),
        "ogg": ("audio.ogg", "audio/ogg"),
        "mp3": ("audio.mp3", "audio/mpeg"),
        "flac": ("audio.flac", "audio/flac"),
    }
    return mapping.get(fmt, ("audio.bin", "application/octet-stream"))
