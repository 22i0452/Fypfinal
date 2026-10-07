"""
diarizer.py - Speaker Diarization for Medical Consultations (Module 2)

Uses energy-based VAD + silence-gap heuristic to separate Doctor/Patient turns.
Falls back gracefully without any extra model downloads.

Primary  : pyannote.audio speaker-diarization-3.1 (if HF_TOKEN is set)
Fallback : Silence-gap heuristic (always works, no extra dependencies)
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import numpy as np
from dataclasses import dataclass
from pathlib import Path

# Allow importing config from parent directory
sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_RATE = 16_000

# Silence-based diarization parameters
FRAME_DURATION_MS   = 20        # ms per energy frame
SILENCE_THRESHOLD   = 0.006     # RMS amplitude threshold for speech detection
MIN_SPEECH_DURATION = 0.25      # seconds — shorter segments are noise
MIN_SILENCE_GAP     = 1.2       # seconds of silence to trigger speaker change
MERGE_GAP           = 0.30      # seconds — merge speech regions closer than this


@dataclass
class DiarizedSegment:
    start: float    # seconds
    end: float      # seconds
    speaker: str    # "Doctor" or "Patient"


# ─── Silence-Based Diarizer ───────────────────────────────────────────────────

def _compute_energy(audio: np.ndarray, frame_samples: int) -> np.ndarray:
    """Compute RMS energy per frame."""
    num_frames = len(audio) // frame_samples
    energies = np.zeros(num_frames, dtype=np.float32)
    for i in range(num_frames):
        frame = audio[i * frame_samples: (i + 1) * frame_samples]
        energies[i] = np.sqrt(np.mean(frame ** 2))
    return energies


def _smooth(arr: np.ndarray, window: int = 5) -> np.ndarray:
    """Apply a simple moving-average smoothing."""
    if len(arr) < window:
        return arr
    kernel = np.ones(window) / window
    return np.convolve(arr, kernel, mode="same")


def _find_speech_regions(
    energies: np.ndarray,
    frame_duration: float,
    silence_threshold: float,
) -> list[tuple[float, float]]:
    """Return list of (start, end) in seconds for speech regions."""
    is_speech = energies > silence_threshold
    regions: list[tuple[float, float]] = []
    in_speech = False
    start = 0.0

    for i, speech in enumerate(is_speech):
        t = i * frame_duration
        if speech and not in_speech:
            in_speech = True
            start = t
        elif not speech and in_speech:
            in_speech = False
            regions.append((start, t))

    if in_speech:
        regions.append((start, len(energies) * frame_duration))

    return regions


def _merge_regions(
    regions: list[tuple[float, float]], merge_gap: float
) -> list[tuple[float, float]]:
    """Merge speech regions that are too close together."""
    if not regions:
        return regions
    merged = [regions[0]]
    for start, end in regions[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= merge_gap:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def diarize_silence_based(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
) -> list[DiarizedSegment]:
    """
    Segment and assign speakers using silence-gap heuristics.
    Doctor is always assigned to the first detected speech segment.
    Speaker flips whenever silence >= MIN_SILENCE_GAP seconds occurs.
    """
    frame_samples = int(sample_rate * FRAME_DURATION_MS / 1000)
    frame_duration = FRAME_DURATION_MS / 1000

    energies = _compute_energy(audio, frame_samples)
    energies = _smooth(energies, window=7)

    regions = _find_speech_regions(energies, frame_duration, SILENCE_THRESHOLD)
    regions = _merge_regions(regions, MERGE_GAP)

    if not regions:
        return []

    # Remove very short regions (noise)
    regions = [(s, e) for s, e in regions if (e - s) >= MIN_SPEECH_DURATION]

    if not regions:
        return []

    # Assign speakers
    speaker_order = ["Doctor", "Patient"]
    speaker_idx = 0
    segments: list[DiarizedSegment] = []
    prev_end = None

    for start, end in regions:
        if prev_end is not None:
            gap = start - prev_end
            if gap >= MIN_SILENCE_GAP:
                speaker_idx = (speaker_idx + 1) % 2
        segments.append(
            DiarizedSegment(
                start=round(start, 3),
                end=round(end, 3),
                speaker=speaker_order[speaker_idx],
            )
        )
        prev_end = end

    return segments


# ─── Pyannote-Based Diarizer (optional, higher quality) ──────────────────────

def _try_pyannote_diarize(
    audio: np.ndarray, sample_rate: int
) -> list[DiarizedSegment] | None:
    """
    Attempt pyannote.audio speaker diarization.
    Returns None if pyannote is not installed or HF_TOKEN is absent.
    """
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError:
        return None

    hf_token = os.getenv("HF_TOKEN", "")
    if not hf_token:
        try:
            from config import _hf_token as hf_token  # type: ignore
        except ImportError:
            pass
    if not hf_token:
        return None

    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )
        # Save audio to temp WAV file (pyannote requires file path)
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        sf.write(tmp_path, audio.astype(np.float32), sample_rate)

        diarization = pipeline(tmp_path)
        os.unlink(tmp_path)

        raw_segments: list[tuple[float, float, str]] = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            raw_segments.append((turn.start, turn.end, speaker))

        if not raw_segments:
            return []

        # Map pyannote speaker labels → Doctor / Patient
        # First speaker to appear is Doctor; all others are Patient
        speaker_map: dict[str, str] = {}
        for _, _, spk in sorted(raw_segments, key=lambda x: x[0]):
            if spk not in speaker_map:
                label = "Doctor" if not speaker_map else "Patient"
                speaker_map[spk] = label

        return [
            DiarizedSegment(start=round(s, 3), end=round(e, 3), speaker=speaker_map[spk])
            for s, e, spk in raw_segments
        ]

    except Exception as exc:
        print(f"[Diarizer] pyannote failed ({exc}), using silence-based fallback.")
        return None


# ─── Public Interface ─────────────────────────────────────────────────────────

class SpeakerDiarizer:
    """
    Speaker diarizer for medical consultations.
    Automatically uses pyannote if available, otherwise falls back to silence-based.
    """

    def __init__(self) -> None:
        self._use_pyannote = bool(os.getenv("HF_TOKEN", ""))
        if self._use_pyannote:
            print("[Diarizer] HF_TOKEN found — will attempt pyannote diarization.")
        else:
            print("[Diarizer] No HF_TOKEN — using silence-based diarization.")

    def diarize(
        self,
        audio: np.ndarray,
        sample_rate: int = SAMPLE_RATE,
    ) -> list[DiarizedSegment]:
        """
        Diarize audio into Doctor / Patient segments.

        Args:
            audio: float32 numpy array, mono, normalised to [-1, 1]
            sample_rate: must match SAMPLE_RATE (16 kHz)

        Returns:
            List of DiarizedSegment ordered by start time.
        """
        if self._use_pyannote:
            result = _try_pyannote_diarize(audio, sample_rate)
            if result is not None:
                return result

        return diarize_silence_based(audio, sample_rate)
