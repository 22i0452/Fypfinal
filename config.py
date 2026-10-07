"""
config.py — Central configuration for the Urdu Medical Receptionist Agent.
All tunable parameters live here; secrets are loaded from .env.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ─── API Keys ─────────────────────────────────────────────────────────────────
GROQ_API_KEY:      str = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY:    str = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY:    str = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
HF_TTS_API_KEY: str = os.getenv("HF_TTS_API_KEY", "")
HF_TTS_VOICE_ID: str = os.getenv("HF_TTS_VOICE_ID", "")  # leave blank for auto-select

# Set HF_TOKEN so huggingface_hub uses authenticated (higher rate-limit) access
_hf_token = os.getenv("HF_TOKEN", "")
if _hf_token:
    os.environ["HF_TOKEN"] = _hf_token  # picked up automatically by huggingface_hub

# ─── Audio Recording ──────────────────────────────────────────────────────────
SAMPLE_RATE: int        = 16_000   # Hz  — required by most ASR models
CHUNK_DURATION: float   = 0.1      # seconds per VAD chunk (100 ms)

# Energy-based Voice Activity Detection
# Raise ENERGY_THRESHOLD if the mic picks up too much background noise.
# Lower it if the agent misses soft speech.
ENERGY_THRESHOLD: float = 0.008    # RMS amplitude (0.0 – 1.0)

# How long silence must last before recording stops (seconds)
SILENCE_DURATION: float = 1.8

# Hard cap on a single recording (seconds)
MAX_RECORDING_DURATION: int = 30

# ─── STT — OpenRouter / Groq Whisper (no local model download) ───────────────
GROQ_STT_MODEL: str = os.getenv("GROQ_STT_MODEL", "whisper-large-v3")
OPENAI_STT_MODEL: str = os.getenv("OPENAI_STT_MODEL", "whisper-1")
MODULE2_STT_PROVIDER: str = os.getenv("MODULE2_STT_PROVIDER", "openrouter")
MODULE2_GROQ_STT_MODEL: str = os.getenv("MODULE2_GROQ_STT_MODEL", "whisper-large-v3")
MODULE2_OPENAI_STT_MODEL: str = os.getenv("MODULE2_OPENAI_STT_MODEL", OPENAI_STT_MODEL)
MODULE2_OPENROUTER_STT_MODEL: str = os.getenv(
    "MODULE2_OPENROUTER_STT_MODEL", "openai/gpt-4o-transcribe"
)
MODULE2_OPENROUTER_WHISPER_MODEL: str = os.getenv(
    "MODULE2_OPENROUTER_WHISPER_MODEL", "openai/whisper-large-v3"
)
OPENROUTER_LLM_MODEL: str = os.getenv("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini")

# ─── LLM Brain — Groq LLaMA ──────────────────────────────────────────────────
GROQ_LLM_MODEL: str = os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
DIARIZATION_PROVIDER: str = os.getenv("DIARIZATION_PROVIDER", "auto")
GROQ_DIARIZATION_MODEL: str = os.getenv("GROQ_DIARIZATION_MODEL", GROQ_LLM_MODEL)
OPENAI_LLM_MODEL: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
OPENAI_DIARIZATION_MODEL: str = os.getenv("OPENAI_DIARIZATION_MODEL", OPENAI_LLM_MODEL)
MEDFLOW_ENV: str = os.getenv("MEDFLOW_ENV", "development")
MEDFLOW_LLM_PROVIDER: str = os.getenv("MEDFLOW_LLM_PROVIDER", "openai")
MEDFLOW_AUDIO_RETENTION_ENABLED: str = os.getenv("MEDFLOW_AUDIO_RETENTION_ENABLED", "false")
MEDFLOW_AUDIO_RETENTION_DIR: str = os.getenv("MEDFLOW_AUDIO_RETENTION_DIR", "scribe/retained_audio")

# ─── TTS — Microsoft Edge TTS (free, no API key) ──────────────────────────────
# ur-PK-UzmaNeural  →  Female Pakistani Urdu (default)
# ur-PK-AsadNeural  →  Male  Pakistani Urdu
