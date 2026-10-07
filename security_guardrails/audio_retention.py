from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audit import audit_event


@dataclass(frozen=True)
class AudioRetentionDecision:
    consent_recorded: bool = False
    retention_requested: bool = False
    retention_days: int = 30

    @property
    def may_retain(self) -> bool:
        return self.consent_recorded and self.retention_requested and audio_retention_enabled()


def audio_retention_enabled() -> bool:
    return os.getenv("MEDFLOW_AUDIO_RETENTION_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def make_audio_retention_metadata(
    *,
    decision: AudioRetentionDecision,
    audio_ref: str = "",
) -> dict[str, Any]:
    now = time.time()
    state = "AUDIO_RETENTION_CONSENTED" if decision.may_retain else "AUDIO_DELETED"
    delete_after = ""
    if decision.may_retain:
        delete_after = time.strftime(
            "%Y-%m-%dT%H:%M:%S",
            time.localtime(now + decision.retention_days * 24 * 60 * 60),
        )
    return {
        "state": state,
        "consent_recorded": decision.consent_recorded,
        "retention_enabled": decision.may_retain,
        "retention_days": decision.retention_days if decision.may_retain else 0,
        "audio_ref": audio_ref if decision.may_retain else "",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
        "delete_after": delete_after,
    }


def cleanup_audio_session(
    session: dict[str, Any],
    *,
    patient_ref: str = "",
    note_ref: str = "",
    allow_retention: bool = True,
) -> dict[str, Any]:
    decision = AudioRetentionDecision(
        consent_recorded=bool(session.get("audio_retention_consent")),
        retention_requested=bool(session.get("audio_retention_requested")),
        retention_days=int(session.get("audio_retention_days") or 30),
    )
    effective_decision = decision if allow_retention else AudioRetentionDecision()
    audio_ref = ""
    if effective_decision.may_retain:
        audio_ref = f"audio_{int(time.time() * 1000)}{int.from_bytes(os.urandom(2), 'big') % 1000:03d}"
        retention_dir = Path(os.getenv("MEDFLOW_AUDIO_RETENTION_DIR", "scribe/retained_audio"))
        retention_dir.mkdir(parents=True, exist_ok=True)
        chunks = session.get("audio_chunks") if isinstance(session.get("audio_chunks"), list) else []
        stored_audio = False
        if chunks:
            import numpy as np
            import soundfile as sf

            audio = np.concatenate(chunks).astype(np.float32)
            sample_rate = int(session.get("input_sample_rate") or 16_000)
            temporary_path = retention_dir / f".{audio_ref}.{uuid.uuid4().hex}.tmp.wav"
            audio_path = retention_dir / f"{audio_ref}.wav"
            try:
                sf.write(temporary_path, audio, sample_rate, format="WAV")
                os.replace(temporary_path, audio_path)
                stored_audio = True
            finally:
                temporary_path.unlink(missing_ok=True)
        metadata_path = retention_dir / f"{audio_ref}.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "audio_ref": audio_ref,
                    "patient_ref": patient_ref,
                    "note_ref": note_ref,
                    "stored_audio": stored_audio,
                    "audio_file": f"{audio_ref}.wav" if stored_audio else "",
                    "warning": "Development metadata only; production audio storage requires encryption and access control.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    session["audio_chunks"] = []
    metadata = make_audio_retention_metadata(decision=effective_decision, audio_ref=audio_ref)
    audit_event(
        "audio_cleanup",
        actor_ref="system",
        action="audio_cleanup",
        patient_ref=patient_ref,
        result="allow",
        metadata={"note_ref": note_ref, "state": metadata["state"], "retained": metadata["retention_enabled"]},
    )
    return metadata
