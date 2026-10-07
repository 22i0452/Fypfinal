"""
audio_recorder.py — Microphone capture with energy-based Voice Activity Detection.

Algorithm
---------
1. Stream audio in 100 ms chunks.
2. Compute RMS energy of each chunk.
3. Wait for energy > ENERGY_THRESHOLD (speech start).
4. Keep recording until SILENCE_DURATION seconds of silence passes (speech end).
5. Return a concatenated float32 numpy array normalised to [-1, 1].
"""

from __future__ import annotations

from collections import deque

import numpy as np
import sounddevice as sd

from config import (
    CHUNK_DURATION,
    ENERGY_THRESHOLD,
    MAX_RECORDING_DURATION,
    SAMPLE_RATE,
    SILENCE_DURATION,
)


class AudioRecorder:
    """Records from the default microphone using energy-based VAD."""

    def __init__(self) -> None:
        self.sample_rate: int   = SAMPLE_RATE
        self.chunk_size: int    = int(SAMPLE_RATE * CHUNK_DURATION)
        self.energy_threshold: float = ENERGY_THRESHOLD
        self._silence_limit: int = max(1, int(SILENCE_DURATION / CHUNK_DURATION))
        self._max_chunks: int    = int(MAX_RECORDING_DURATION / CHUNK_DURATION)

    @staticmethod
    def _rms(chunk: np.ndarray) -> float:
        return float(np.sqrt(np.mean(chunk ** 2)))

    def calibrate(self, duration: float = 2.0) -> None:
        """
        Sample ambient noise and set the energy threshold automatically.
        """
        print(f"🔧  Calibrating microphone ({duration:.0f}s) — please stay quiet…")
        chunks: list[np.ndarray] = []
        n_chunks = int(duration / CHUNK_DURATION)

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
        ) as stream:
            for _ in range(n_chunks):
                data, _ = stream.read(self.chunk_size)
                chunks.append(data.flatten())

        ambient_rms = self._rms(np.concatenate(chunks))
        self.energy_threshold = max(0.003, ambient_rms * 3.0)
        print(f"✅  Threshold set to {self.energy_threshold:.4f}  (ambient RMS: {ambient_rms:.4f})")

    def record(
        self,
        interrupt_event=None,
        *,
        short_response: bool = False,
    ) -> np.ndarray | None:
        """
        Block until the user finishes speaking, then return audio as a
        float32 numpy array at SAMPLE_RATE.  Returns None if no speech
        was detected within the recording window. A trusted UI action
        may interrupt the wait between 100 ms audio chunks. Short numeric and
        confirmation turns use a slightly lower speech-start threshold.
        """
        frames: list[np.ndarray] = []
        pre_roll: deque[np.ndarray] = deque(maxlen=3)
        silence_count: int = 0
        speech_started: bool = False
        waiting_chunks = 0
        speech_threshold = self.energy_threshold * (0.55 if short_response else 1.0)

        if interrupt_event is not None and interrupt_event.is_set():
            return None

        print("\nListening for speech (Urdu or English).")

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
        ) as stream:
            while len(frames) < self._max_chunks:
                if interrupt_event is not None and interrupt_event.is_set():
                    return None
                chunk, overflowed = stream.read(self.chunk_size)
                if overflowed:
                    print("Warning  Microphone input overflowed; discarding incomplete audio")
                    return None
                chunk = chunk.flatten()
                energy = self._rms(chunk)

                if energy > speech_threshold:
                    if not speech_started:
                        frames.extend(pre_roll)
                    speech_started = True
                    silence_count = 0
                    frames.append(chunk)
                elif speech_started:
                    frames.append(chunk)
                    silence_count += 1
                    if silence_count >= self._silence_limit:
                        print("End of speech detected; processing audio.")
                        break
                else:
                    pre_roll.append(chunk)
                    waiting_chunks += 1
                    if waiting_chunks >= self._max_chunks:
                        return None

        if not speech_started or not frames:
            return None

        return np.concatenate(frames)
