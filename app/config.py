from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_path: Path
    session_secret: str
    session_cookie_name: str
    session_max_age_seconds: int
    mock_otp_enabled: bool
    show_dev_otp: bool
    otp_secret: str
    test_otp_code: str
    otp_expiry_seconds: int
    otp_lock_seconds: int
    otp_resend_cooldown_seconds: int
    otp_max_attempts: int
    otp_max_resends: int
    clinic_seed_path: Path
    patient_records_dir: Path
    generated_notes_dir: Path
    storage_backend: str = "json"
    previsit_summary_enabled: bool = True
    fhir_enabled: bool = False
    icd_coding_enabled: bool = False
    development_quick_start_enabled: bool = False
    receptionist_service_token: str = ""
    primary_doctor_email: str = ""
    primary_doctor_display_name: str = "Dr. Shahzaib Ali Khan"
    telnyx_api_key: str = ""
    telnyx_number: str = ""
    telnyx_connection_id: str = ""
    telnyx_webhook_base_url: str = ""
    openrouter_api_key: str = ""
    openrouter_llm_model: str = "openai/gpt-4o-mini"
    openrouter_tts_model: str = "x-ai/grok-voice-tts-1.0"
    openrouter_tts_voice: str = "eve"
    openrouter_stt_model: str = "openai/whisper-large-v3"
    groq_api_key: str = ""
    groq_llm_model: str = "qwen/qwen3.8-27b"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def may_expose_dev_otp(self) -> bool:
        return self.app_env == "development" and self.mock_otp_enabled and self.show_dev_otp

    @property
    def development_quick_start_available(self) -> bool:
        return self.app_env == "development" and self.development_quick_start_enabled

    @classmethod
    def from_env(cls) -> "Settings":
        app_env = os.getenv("APP_ENV", os.getenv("MEDFLOW_ENV", "development")).strip().lower()
        show_dev_otp = _bool_env("SHOW_DEV_OTP", False)
        if app_env == "production" and show_dev_otp:
            raise RuntimeError("SHOW_DEV_OTP must be false in production")
        development_quick_start_enabled = _bool_env(
            "DEVELOPMENT_QUICK_START_ENABLED",
            app_env == "development",
        )
        if app_env != "development" and development_quick_start_enabled:
            raise RuntimeError("DEVELOPMENT_QUICK_START_ENABLED may only be true in development")

        default_database = ROOT_DIR / "consultation" / "consultation.db"
        database_path = Path(os.getenv("MEDFLOW_DATABASE_PATH", str(default_database))).expanduser()
        if not database_path.is_absolute():
            database_path = ROOT_DIR / database_path

        session_secret = os.getenv("SESSION_SECRET", "medflow-ai-development-session-secret")
        otp_secret = os.getenv("OTP_SECRET", session_secret)
        if app_env == "production":
            if len(session_secret) < 32 or session_secret == "medflow-ai-development-session-secret":
                raise RuntimeError("A strong SESSION_SECRET is required in production")
            if len(otp_secret) < 32:
                raise RuntimeError("A strong OTP_SECRET is required in production")

        receptionist_service_token = os.getenv("MEDFLOW_RECEPTIONIST_SERVICE_TOKEN", "").strip()
        development_receptionist_token = "medflow-development-receptionist-token"
        if not receptionist_service_token and app_env == "development":
            receptionist_service_token = development_receptionist_token
        if app_env == "production" and (
            len(receptionist_service_token) < 32
            or receptionist_service_token == development_receptionist_token
        ):
            raise RuntimeError("A strong MEDFLOW_RECEPTIONIST_SERVICE_TOKEN is required in production")

        test_otp_code = os.getenv("TEST_OTP_CODE", "123456")
        if app_env == "test" and (len(test_otp_code) != 6 or not test_otp_code.isdecimal()):
            raise RuntimeError("TEST_OTP_CODE must contain exactly six decimal digits")

        storage_backend = os.getenv("STORAGE_BACKEND", "json").strip().lower()
        if storage_backend != "json":
            raise RuntimeError("Only the JSON development storage adapter is implemented")

        return cls(
            app_env=app_env,
            database_path=database_path.resolve(),
            session_secret=session_secret,
            session_cookie_name=os.getenv("SESSION_COOKIE_NAME", "medflow_session"),
            session_max_age_seconds=int(os.getenv("SESSION_MAX_AGE_SECONDS", "28800")),
            mock_otp_enabled=_bool_env("MOCK_OTP_ENABLED", app_env in {"development", "test"}),
            show_dev_otp=show_dev_otp,
            otp_secret=otp_secret,
            test_otp_code=test_otp_code,
            otp_expiry_seconds=int(os.getenv("OTP_EXPIRY_SECONDS", "300")),
            otp_lock_seconds=int(os.getenv("OTP_LOCK_SECONDS", "900")),
            otp_resend_cooldown_seconds=int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", "60")),
            otp_max_attempts=int(os.getenv("OTP_MAX_ATTEMPTS", "5")),
            otp_max_resends=int(os.getenv("OTP_MAX_RESENDS", "5")),
            clinic_seed_path=ROOT_DIR / "app" / "data" / "clinic_seed.json",
            patient_records_dir=Path(
                os.getenv("MEDFLOW_PATIENT_RECORDS_DIR", str(ROOT_DIR / "patient_records"))
            ).resolve(),
            generated_notes_dir=Path(
                os.getenv("MEDFLOW_GENERATED_NOTES_DIR", str(ROOT_DIR / "scribe" / "generated_notes"))
            ).resolve(),
            storage_backend=storage_backend,
            previsit_summary_enabled=_bool_env("PREVISIT_SUMMARY_ENABLED", True),
            fhir_enabled=_bool_env("FHIR_ENABLED", False),
            icd_coding_enabled=_bool_env("ICD_CODING_ENABLED", False),
            development_quick_start_enabled=development_quick_start_enabled,
            receptionist_service_token=receptionist_service_token,
            primary_doctor_email=os.getenv(
                "PRIMARY_DOCTOR_EMAIL",
                "sa7979798@gmail.com" if app_env == "development" else "",
            ).strip().lower(),
            primary_doctor_display_name=os.getenv(
                "PRIMARY_DOCTOR_DISPLAY_NAME",
                "Dr. Shahzaib Ali Khan",
            ).strip()
            or "Dr. Shahzaib Ali Khan",
            telnyx_api_key=os.getenv("TELNYX_API_KEY", "").strip(),
            telnyx_number=os.getenv("TELNYX_NUMBER", os.getenv("TELNYX_PHONE_NUMBER", "")).strip(),
            telnyx_connection_id=os.getenv("TELNYX_CONNECTION_ID", "").strip(),
            telnyx_webhook_base_url=os.getenv(
                "TELNYX_WEBHOOK_BASE_URL",
                os.getenv("PUBLIC_BASE_URL", ""),
            ).strip().rstrip("/"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
            openrouter_llm_model=os.getenv("OPENROUTER_LLM_MODEL", "openai/gpt-4o-mini").strip()
            or "openai/gpt-4o-mini",
            openrouter_tts_model=os.getenv(
                "OPENROUTER_TTS_MODEL",
                "x-ai/grok-voice-tts-1.0",
            ).strip()
            or "x-ai/grok-voice-tts-1.0",
            openrouter_tts_voice=os.getenv("OPENROUTER_TTS_VOICE", "eve").strip() or "eve",
            # Voice agent STT: same Whisper used by medical transcription (Module 2).
            openrouter_stt_model=os.getenv(
                "OPENROUTER_STT_MODEL",
                os.getenv("MODULE2_OPENROUTER_WHISPER_MODEL", "openai/whisper-large-v3"),
            ).strip()
            or "openai/whisper-large-v3",
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip().strip('"'),
            groq_llm_model=os.getenv("GROQ_LLM_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b",
        )
