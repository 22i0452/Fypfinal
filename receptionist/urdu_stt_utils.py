from __future__ import annotations

import re
from collections import Counter

import numpy as np


URDU_STT_BIAS_HINT = "پاکستانی اردو طبی مشاورت"

_PROMPT_ECHO_MARKERS = (
    "pakistani urdu medical consultation",
    "medical consultation between doctor and patient",
    "transcribe only the exact spoken words",
    "speaker labels",
)

_BAD_TRANSCRIPT_MARKERS = (
    "i am a doctor",
    "hello doctor, how are you",
    "comment section",
    "exact message",
    "excel reports",
)


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def prepare_audio_for_stt(audio: np.ndarray) -> np.ndarray:
    prepared = np.asarray(audio, dtype=np.float32)
    if prepared.size == 0:
        return prepared

    prepared = prepared - float(np.mean(prepared))
    peak = float(np.max(np.abs(prepared)))
    if peak > 1e-6:
        prepared = prepared / peak * 0.95
    return prepared.astype(np.float32, copy=False)


def resample_audio(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate <= 0 or target_rate <= 0 or source_rate == target_rate:
        return np.asarray(audio, dtype=np.float32)

    prepared = np.asarray(audio, dtype=np.float32)
    if prepared.size < 2:
        return prepared

    target_length = max(1, int(round(prepared.size * target_rate / source_rate)))
    source_positions = np.linspace(0.0, 1.0, num=prepared.size, endpoint=True)
    target_positions = np.linspace(0.0, 1.0, num=target_length, endpoint=True)
    return np.interp(target_positions, source_positions, prepared).astype(np.float32)


def evaluate_urdu_transcript(text: str, duration_seconds: float | None = None) -> dict[str, object]:
    normalized = normalize_text(text)
    lowered = normalized.lower()
    urdu_char_count = len(re.findall(r"[\u0600-\u06FF]", normalized))
    urdu_words = re.findall(r"[\u0600-\u06FF]+", normalized)
    english_words = re.findall(r"[A-Za-z]{2,}", normalized)
    english_word_count = len(english_words)
    numeric_tokens = re.findall(r"\b\d+(?:[./:-]\d+)*\b", normalized)
    token_count = len(urdu_words) + english_word_count + len(numeric_tokens)

    sentence_parts = [
        part.strip().lower()
        for part in re.split(r"[\n.!?؟]+", normalized)
        if len(part.strip()) >= 12
    ]
    sentence_count = len(sentence_parts)
    duplicate_sentence_count = sum(
        count - 1 for count in Counter(sentence_parts).values() if count > 1
    )

    reasons: list[str] = []
    matched_markers = [marker for marker in _BAD_TRANSCRIPT_MARKERS if marker in lowered]
    prompt_echo_markers = [marker for marker in _PROMPT_ECHO_MARKERS if marker in lowered]

    if matched_markers:
        reasons.append("bad_phrase_marker")
    if prompt_echo_markers:
        reasons.append("prompt_echo")
    if 0 < urdu_char_count < 16 and english_word_count >= 12:
        reasons.append("almost_no_urdu")
    if english_word_count >= 28 and 0 < urdu_char_count < max(60, english_word_count * 2):
        reasons.append("english_heavy")
    if duplicate_sentence_count >= 2:
        reasons.append("duplicate_sentences")

    char_density = 0.0
    token_density = 0.0
    if duration_seconds and duration_seconds > 0:
        char_density = len(normalized) / duration_seconds
        token_density = token_count / duration_seconds
        if (
            duration_seconds >= 20
            and len(normalized) < max(120, duration_seconds * 5.0)
            and token_count < max(24, duration_seconds * 0.85)
            and sentence_count <= 4
        ):
            reasons.append("too_short_for_duration")

    score = (
        len(normalized) * 0.10
        + token_count * 1.50
        + urdu_char_count * 0.05
        - duplicate_sentence_count * 12.0
        - len(matched_markers) * 15.0
        - len(prompt_echo_markers) * 20.0
    )
    if "too_short_for_duration" in reasons:
        score -= 25.0

    return {
        "normalized": normalized,
        "score": score,
        "suspicious": bool(reasons),
        "reasons": reasons,
        "urdu_char_count": urdu_char_count,
        "english_word_count": english_word_count,
        "token_count": token_count,
        "sentence_count": sentence_count,
        "char_density": char_density,
        "token_density": token_density,
    }