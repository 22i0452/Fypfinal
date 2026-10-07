from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import ROOT_DIR, Settings
from app.main import create_app


def _settings(root: Path) -> Settings:
    return Settings(
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


def _create_legacy_doctor_database(path: Path) -> None:
    salt = bytes.fromhex("00" * 16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256", b"SyntheticPass123!", salt, 200_000
    ).hex()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO doctors (full_name, email, password_hash, salt, created_at)
            VALUES ('Dr. Synthetic Existing', 'existing@example.test', ?, ?, '2030-01-01T00:00:00')
            """,
            (password_hash, "00" * 16),
        )
        connection.commit()
    finally:
        connection.close()


class CentralAppAuthenticationTests(unittest.TestCase):
    def test_legacy_account_migrates_and_workspace_requires_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = _settings(root)
            _create_legacy_doctor_database(settings.database_path)
            app = create_app(settings)

            with TestClient(app, follow_redirects=False) as client:
                unauthenticated = client.get("/workspace")
                self.assertEqual(unauthenticated.status_code, 302)
                self.assertEqual(unauthenticated.headers["location"], "/consultation/login")

                login = client.post(
                    "/api/consultation/login",
                    json={"email": "existing@example.test", "password": "SyntheticPass123!"},
                )
                self.assertEqual(login.status_code, 200)
                user = login.json()["user"]
                self.assertEqual(user["full_name"], "Dr. Synthetic Existing")
                self.assertEqual(user["role"], "DOCTOR")
                self.assertTrue(user["practitioner_id"].startswith("DOC-USER-"))

                workspace = client.get("/workspace")
                self.assertEqual(workspace.status_code, 200)
                self.assertIn("Clinical Notes Workspace", workspace.text)
                self.assertEqual(client.get("/api/auth/me").status_code, 200)

            connection = sqlite3.connect(settings.database_path)
            try:
                provider_count = connection.execute(
                    "SELECT COUNT(*) FROM practitioner_profiles"
                ).fetchone()[0]
                login_count = connection.execute("SELECT COUNT(*) FROM doctors").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(provider_count, 4)
            self.assertEqual(login_count, 1)

    def test_signup_uses_backend_session_not_browser_password_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = _settings(Path(directory))
            app = create_app(settings)
            with TestClient(app) as client:
                signup = client.post(
                    "/api/auth/signup",
                    json={
                        "full_name": "Dr. Synthetic New",
                        "email": "new@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(signup.status_code, 200)
                self.assertEqual(client.get("/api/auth/me").status_code, 401)
                self.assertEqual(
                    client.post(
                        "/api/auth/login",
                        json={"email": "new@example.test", "password": "SyntheticPass123!"},
                    ).status_code,
                    200,
                )
                self.assertEqual(client.get("/api/auth/me").status_code, 200)

    def test_production_rejects_development_otp_exposure(self) -> None:
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "SHOW_DEV_OTP": "true"},
            clear=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "SHOW_DEV_OTP"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
