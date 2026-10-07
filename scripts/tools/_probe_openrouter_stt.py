"""Smoke-test OpenRouter Module 2 STT routing + metal-pipe cleanup."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from security_guardrails import Actor, SecureLLMGateway, set_gateway
from scribe.transcript_cleaner import TranscriptCleaner


def _tiny_wav_bytes(seconds: float = 0.4, sample_rate: int = 16_000) -> bytes:
    import soundfile as sf

    t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
    audio = (0.05 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    return buffer.getvalue()


def main() -> None:
    set_gateway(None)
    gateway = SecureLLMGateway()
    set_gateway(gateway)
    provider, model = gateway._select_provider_model("module2_stt", None, None)
    print(f"selected={provider}/{model}")

    # Live STT call on a tiny tone (just verifies routing/auth; text may be empty/noise).
    try:
        text = gateway.transcribe_audio(
            task_type="module2_stt",
            audio_bytes=_tiny_wav_bytes(),
            actor=Actor.system("system_agent", "PT-STT"),
            patient_ref="PT-STT",
            language="ur",
            prompt="Pakistani Urdu medical consultation. موٹر بائیک بائیک گھٹنا درد",
            response_format="text",
        )
        print(f"stt_ok text_len={len(text)} preview={text[:80]!r}")
    except Exception as exc:
        print(f"stt_failed: {type(exc).__name__}: {exc}")

    noisy = (
        "ڈاکٹر صاحب، اصل میں میٹل پائپ شلال تھا۔ تو، ایک دم وہ سامنے پتھر آیا "
        "اور میں کل گیا۔ ایک ٹانگ پتھر کی پر آئی، پائپ کا گارڈ میری ٹانگ کی پر آئی۔ "
        "مجھے شدید قسم کا درد ہوا۔"
    )
    cleaned = TranscriptCleaner().clean(noisy, patient_ref="PT-STT")
    print(json.dumps({"cleaned": cleaned}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
