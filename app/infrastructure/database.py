from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteDatabase:
    """Single configured SQLite connection factory with explicit close semantics."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(_SCHEMA)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS receptionist_intake_sessions ("
                "token_hash TEXT PRIMARY KEY, patient_id TEXT NOT NULL, "
                "workflow_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL CHECK (revision > 0))"
            )
            self._ensure_column(connection, "doctors", "role", "TEXT NOT NULL DEFAULT 'DOCTOR'")
            self._ensure_column(connection, "doctors", "active", "INTEGER NOT NULL DEFAULT 1")

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def seed_clinic_configuration(self, seed_path: str | Path) -> None:
        seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
        clinic = seed["clinic"]
        location = seed["location"]
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO clinics (
                    clinic_id, name, timezone, slot_duration_minutes,
                    booking_horizon_days, minimum_advance_booking_minutes, active
                ) VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(clinic_id) DO UPDATE SET
                    name=excluded.name,
                    timezone=excluded.timezone,
                    slot_duration_minutes=excluded.slot_duration_minutes,
                    booking_horizon_days=excluded.booking_horizon_days,
                    minimum_advance_booking_minutes=excluded.minimum_advance_booking_minutes
                """,
                (
                    clinic["clinic_id"],
                    clinic["name"],
                    clinic["timezone"],
                    clinic["slot_duration_minutes"],
                    clinic["booking_horizon_days"],
                    clinic["minimum_advance_booking_minutes"],
                ),
            )
            connection.execute(
                """
                INSERT INTO clinic_locations (location_id, clinic_id, name, address, active)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(location_id) DO UPDATE SET
                    clinic_id=excluded.clinic_id, name=excluded.name,
                    address=excluded.address, active=1
                """,
                (location["location_id"], location["clinic_id"], location["name"], location["address"]),
            )
            for department in seed["departments"]:
                connection.execute(
                    """
                    INSERT INTO departments (department_id, name, active)
                    VALUES (?, ?, 1)
                    ON CONFLICT(department_id) DO UPDATE SET name=excluded.name, active=1
                    """,
                    (department["department_id"], department["name"]),
                )
            for visit_type in seed["visit_types"]:
                connection.execute(
                    """
                    INSERT INTO visit_types (visit_type_id, name, mode, duration_minutes, active)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(visit_type_id) DO UPDATE SET
                        name=excluded.name, mode=excluded.mode,
                        duration_minutes=excluded.duration_minutes, active=1
                    """,
                    (
                        visit_type["visit_type_id"],
                        visit_type["name"],
                        visit_type["mode"],
                        visit_type["duration_minutes"],
                    ),
                )
            connection.execute("DELETE FROM clinic_working_hours WHERE clinic_id = ?", (clinic["clinic_id"],))
            for day, intervals in seed["working_hours"].items():
                for index, (start_time, end_time) in enumerate(intervals):
                    connection.execute(
                        """
                        INSERT INTO clinic_working_hours
                            (clinic_id, weekday, interval_index, start_time, end_time)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (clinic["clinic_id"], day, index, start_time, end_time),
                    )
            for provider in seed["development_providers"]:
                connection.execute(
                    """
                    INSERT INTO practitioner_profiles (
                        practitioner_id, doctor_user_id, display_name,
                        department_id, location_id, active, inherits_clinic_hours
                    ) VALUES (?, NULL, ?, ?, ?, 1, 1)
                    ON CONFLICT(practitioner_id) DO UPDATE SET
                        display_name=excluded.display_name,
                        department_id=excluded.department_id,
                        location_id=excluded.location_id,
                        active=1
                    """,
                    (
                        provider["practitioner_id"],
                        provider["display_name"],
                        provider["department_id"],
                        provider["location_id"],
                    ),
                )

    def connect_existing_doctors_to_profiles(self) -> None:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT id, full_name FROM doctors WHERE active = 1 ORDER BY id"
            ).fetchall()
            for row in rows:
                existing = connection.execute(
                    "SELECT practitioner_id FROM practitioner_profiles WHERE doctor_user_id = ?",
                    (row["id"],),
                ).fetchone()
                if existing:
                    continue
                practitioner_id = f"DOC-USER-{int(row['id']):03d}"
                connection.execute(
                    """
                    INSERT INTO practitioner_profiles (
                        practitioner_id, doctor_user_id, display_name,
                        department_id, location_id, active, inherits_clinic_hours
                    ) VALUES (?, ?, ?, 'DEP-GM', 'LOC-ISB-001', 1, 1)
                    """,
                    (practitioner_id, int(row["id"]), row["full_name"]),
                )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'DOCTOR',
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clinics (
    clinic_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    slot_duration_minutes INTEGER NOT NULL,
    booking_horizon_days INTEGER NOT NULL,
    minimum_advance_booking_minutes INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clinic_locations (
    location_id TEXT PRIMARY KEY,
    clinic_id TEXT NOT NULL REFERENCES clinics(clinic_id),
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS departments (
    department_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS visit_types (
    visit_type_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS clinic_working_hours (
    clinic_id TEXT NOT NULL REFERENCES clinics(clinic_id),
    weekday TEXT NOT NULL,
    interval_index INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    PRIMARY KEY (clinic_id, weekday, interval_index)
);

CREATE TABLE IF NOT EXISTS practitioner_profiles (
    practitioner_id TEXT PRIMARY KEY,
    doctor_user_id INTEGER UNIQUE REFERENCES doctors(id),
    display_name TEXT NOT NULL,
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    location_id TEXT NOT NULL REFERENCES clinic_locations(location_id),
    active INTEGER NOT NULL DEFAULT 1,
    inherits_clinic_hours INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS practitioner_blocked_periods (
    blocked_period_id TEXT PRIMARY KEY,
    practitioner_id TEXT NOT NULL REFERENCES practitioner_profiles(practitioner_id),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT 'UNAVAILABLE'
);

CREATE TABLE IF NOT EXISTS patient_assignments (
    practitioner_id TEXT NOT NULL REFERENCES practitioner_profiles(practitioner_id),
    patient_id TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    assigned_at TEXT NOT NULL,
    PRIMARY KEY (practitioner_id, patient_id)
);

CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    practitioner_id TEXT NOT NULL REFERENCES practitioner_profiles(practitioner_id),
    department_id TEXT NOT NULL REFERENCES departments(department_id),
    location_id TEXT NOT NULL REFERENCES clinic_locations(location_id),
    visit_type_id TEXT NOT NULL REFERENCES visit_types(visit_type_id),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    cancellation_reason TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appointments_practitioner_time
    ON appointments(practitioner_id, start_at, end_at);
CREATE INDEX IF NOT EXISTS idx_appointments_patient_time
    ON appointments(patient_id, start_at, end_at);

CREATE TABLE IF NOT EXISTS appointment_operations (
    idempotency_key TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    appointment_id TEXT NOT NULL REFERENCES appointments(appointment_id),
    request_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_sessions (
    workflow_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    appointment_id TEXT,
    encounter_id TEXT,
    note_id TEXT,
    assigned_practitioner_id TEXT,
    state TEXT NOT NULL,
    resume_state TEXT,
    version INTEGER NOT NULL,
    last_error_code TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    practitioner_id TEXT NOT NULL REFERENCES practitioner_profiles(practitioner_id),
    appointment_id TEXT NOT NULL REFERENCES appointments(appointment_id),
    workflow_id TEXT NOT NULL REFERENCES workflow_sessions(workflow_id),
    status TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS verification_challenges (
    challenge_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL REFERENCES workflow_sessions(workflow_id),
    method TEXT NOT NULL,
    normalized_phone_reference TEXT NOT NULL,
    phone_last_four TEXT NOT NULL,
    otp_digest TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    resend_count INTEGER NOT NULL DEFAULT 0,
    last_sent_at TEXT NOT NULL,
    locked_until TEXT,
    verified_at TEXT,
    used_at TEXT,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verification_patient_workflow
    ON verification_challenges(patient_id, workflow_id, created_at);

CREATE TABLE IF NOT EXISTS consent_records (
    consent_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    encounter_id TEXT NOT NULL REFERENCES encounters(encounter_id),
    consent_type TEXT NOT NULL,
    decision INTEGER NOT NULL,
    consent_text_version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    captured_by TEXT NOT NULL,
    capture_method TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_consents_encounter_type
    ON consent_records(encounter_id, consent_type, captured_at);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    action TEXT NOT NULL,
    patient_ref TEXT NOT NULL DEFAULT '',
    resource_ref TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL,
    request_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""
