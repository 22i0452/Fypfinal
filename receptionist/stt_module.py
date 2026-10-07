"""
Receptionist speech transcription through the approved secure STT route.
"""
from __future__ import annotations
import io
import re
from typing import Callable

import numpy as np
import soundfile as sf

from config import GROQ_STT_MODEL, SAMPLE_RATE
from security_guardrails import Actor, get_gateway
from .urdu_stt_utils import evaluate_urdu_transcript, prepare_audio_for_stt


_INTAKE_STT_VOCABULARY = {
    "name": ("نام", "Name"),
    "age": ("عمر، سال", "Age, years"),
    "phone_number": ("موبائل، فون نمبر", "Phone number"),
    "first_visit": ("پہلی ملاقات", "First visit"),
    "past_medical_history": ("طبی تاریخ", "Medical history"),
    "current_complaint": ("علامات", "Symptoms"),
    "department": ("شعبہ", "Department"),
    "practitioner_preference": ("ڈاکٹر، ترجیح", "Doctor, preference"),
    "visit_type": ("ملاقات، مشاورت", "Consultation, follow-up"),
    "booking_slot_time": ("تاریخ، وقت", "Date, time"),
    "confirmation": ("تصدیق، تبدیلی", "Confirmation, correction"),
}

SHORT_INTAKE_FIELDS = frozenset({"age", "phone_number", "first_visit", "confirmation"})


class STTEngine:
    """Transcribes Urdu audio through the approved secure STT gateway."""
    def __init__(self) -> None:
        self._actor = Actor(actor_id="receptionist-agent", role="receptionist")
        print(f"OK  STT Engine ready  (approved gateway route, default model {GROQ_STT_MODEL})")
    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        return prepare_audio_for_stt(audio)
    @staticmethod
    def _to_wav_bytes(audio: np.ndarray) -> bytes:
        buf = io.BytesIO()
        sf.write(buf, audio.astype(np.float32), SAMPLE_RATE, format="WAV")
        return buf.getvalue()
    def transcribe(
        self,
        audio: np.ndarray,
        *,
        expected_field: str = "",
        validator: Callable[[str], bool] | None = None,
        language_hint: str | None = None,
    ) -> str:
        raw = np.asarray(audio, dtype=np.float32)
        if raw.size == 0 or not np.all(np.isfinite(raw)):
            return ""
        # Do not amplify digital silence or a DC-only signal into an STT request.
        if float(np.max(np.abs(raw - float(np.mean(raw))))) < 1e-6:
            return ""
        audio = self._normalize(audio)
        wav_bytes = self._to_wav_bytes(audio)
        best_text = ""
        best_quality: dict[str, object] | None = None

        # Whisper prompts provide vocabulary, not instructions or sample answers.
        preferred = language_hint if language_hint in {"ur", "en"} else None
        vocabulary = _INTAKE_STT_VOCABULARY.get(expected_field, ("", ""))
        if preferred == "ur":
            contextual_prompt = vocabulary[0] + "۔ تصحیح، غلطی۔"
        elif preferred == "en":
            contextual_prompt = vocabulary[1] + ". Correction, mistake."
        else:
            contextual_prompt = ". ".join(vocabulary) + ". تصحیح، Correction."
        first_language = preferred if expected_field in SHORT_INTAKE_FIELDS else None
        retry_language = None if first_language else preferred
        for prompt, language in ((contextual_prompt, first_language), (None, retry_language)):
            result = self._transcribe_approved(
                wav_bytes,
                prompt=prompt,
                language=language,
            )
            if not result:
                continue
            quality = evaluate_urdu_transcript(result)
            normalized = str(quality["normalized"])
            if normalized.strip(" .۔") in {contextual_prompt.strip(" .۔"), *vocabulary}:
                continue
            if any(reason in quality["reasons"] for reason in ("prompt_echo", "bad_phrase_marker", "duplicate_sentences")):
                continue
            if re.search(r"مریض .*بتا رہا|the (?:speaker|patient) (?:is|may)|transcribe only spoken", normalized, re.I):
                continue
            if validator is not None and not validator(normalized):
                print(
                    "Warning  Rejected an implausible STT candidate "
                    f"for intake field {expected_field or 'unknown'}"
                )
                continue
            if best_quality is None or float(quality["score"]) > float(best_quality["score"]):
                best_text = normalized
                best_quality = quality
            if not quality["suspicious"]:
                return normalized
        if best_text:
            print(f"Warning  Returning best available Urdu STT transcript with quality warnings: {best_quality['reasons']}")
            return best_text
        print("Warning  No valid STT result was available")
        return ""

    def _transcribe_approved(
        self,
        wav_bytes: bytes,
        prompt: str | None,
        language: str | None = "ur",
    ) -> str:
        try:
            return get_gateway().transcribe_audio(
                task_type="stt_intake",
                audio_bytes=wav_bytes,
                actor=self._actor,
                model=GROQ_STT_MODEL,
                language=language,
                prompt=prompt,
                response_format="text",
            )
        except Exception:
            print("Warning  Approved STT route failed; no transcript was accepted")
            return ""
