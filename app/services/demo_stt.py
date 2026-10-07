"""Demo voice-call STT helpers (WAV prep + medical-style Whisper)."""
from __future__ import annotations

import io
import logging
import re
import wave

import numpy as np

from receptionist.urdu_stt_utils import normalize_text, prepare_audio_for_stt, resample_audio


logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000

# Same Whisper family as medical Module 2; Urdu Nastaliq + clinic vocabulary.
DEMO_STT_PROMPT = (
    "پاکستانی اردو فون کال میڈفلو کلینک رسیپشن سے۔ "
    "مریض اپنا نام، عمر، فون نمبر، شکایت، ڈاکٹر اور وقت بتاتا ہے۔ "
    "نام درست اردو رسم الخط میں لکھیں جیسے شہزیب علی خان۔ "
    "فون نمبر صرف ہندسوں میں لکھیں جیسے 03031234567۔ "
    "وقت ہندسوں میں لکھیں جیسے 3 بجے۔ "
    "صرف بولی گئی بات کی درست نقل اردو رسم الخط میں کریں۔ رومن اردو مت لکھیں۔"
)


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
    samples = prepare_audio_for_stt(samples)
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
