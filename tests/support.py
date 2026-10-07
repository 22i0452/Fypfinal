from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.config import ROOT_DIR, Settings
from app.container import ApplicationContainer
from security_guardrails import Actor


def test_settings(root: Path, **overrides) -> Settings:
    settings = Settings(
        app_env="test",
        database_path=root / "clinic.db",
        session_secret="synthetic-test-session-secret-at-least-32-characters",
        session_cookie_name="test_medflow_session",
        session_max_age_seconds=3600,
        mock_otp_enabled=True,
        show_dev_otp=False,
        otp_secret="synthetic-test-otp-secret-at-least-32-characters",
        test_otp_code="123456",
        otp_expiry_seconds=300,
        otp_lock_seconds=900,
        otp_resend_cooldown_seconds=60,
        otp_max_attempts=5,
        otp_max_resends=5,
        clinic_seed_path=ROOT_DIR / "app" / "data" / "clinic_seed.json",
        patient_records_dir=root / "patients",
        generated_notes_dir=root / "notes",
    )
    return replace(settings, **overrides)


def build_container(root: Path, **setting_overrides):
    settings = test_settings(root, **setting_overrides)
    settings.patient_records_dir.mkdir(parents=True, exist_ok=True)
    (settings.patient_records_dir / "patient_synthetic_en.json").write_text(
        json.dumps(
            {
                "name": "Synthetic Patient",
                "phone_number": "03000000000",
                "age": "40 years",
                "current_complaint": "Synthetic symptom",
            }
        ),
        encoding="utf-8",
    )
    container = ApplicationContainer(settings)
    container.initialize()
    user = container.auth_repository.create_doctor(
        "Dr. Synthetic Test", "doctor@example.test", "SyntheticPass123!"
    )
    patient = container.patient_repository.list()[0]
    assert user.practitioner_id
    container.auth_repository.assign_patient(user.practitioner_id, patient.patient_id)
    actor = Actor(str(user.user_id), "doctor", {patient.patient_id}, patient.patient_id)
    receptionist = Actor("reception-test", "receptionist", {patient.patient_id}, patient.patient_id)
    return settings, container, user, patient, actor, receptionist
