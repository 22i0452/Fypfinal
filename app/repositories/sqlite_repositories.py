from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.infrastructure.database import SQLiteDatabase
from medflow.domain.enums import AppointmentStatus, ConsentType
from medflow.domain.models import (
    Appointment,
    AuditEvent,
    ConsentRecord,
    Encounter,
    VerificationRecord,
    WorkflowSession,
)
from medflow.repositories.json_repositories import RepositoryConflictError


class SQLiteClinicRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get_clinic(self, clinic_id: str = "CLINIC-DEMO-001") -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM clinics WHERE clinic_id = ?", (clinic_id,)).fetchone()
        return dict(row) if row else None

    def list_departments(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT department_id, name FROM departments WHERE active = 1 ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_locations(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT location_id, clinic_id, name, address FROM clinic_locations WHERE active = 1 ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_visit_types(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT visit_type_id, name, mode, duration_minutes
                FROM visit_types WHERE active = 1 ORDER BY name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_practitioners(
        self,
        *,
        department_id: str | None = None,
        location_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT practitioner_id, display_name, department_id, location_id,
                   active, inherits_clinic_hours, doctor_user_id
            FROM practitioner_profiles WHERE active = 1
        """
        parameters: list[Any] = []
        if department_id:
            query += " AND department_id = ?"
            parameters.append(department_id)
        if location_id:
            query += " AND location_id = ?"
            parameters.append(location_id)
        query += " ORDER BY display_name"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def get_practitioner(self, practitioner_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM practitioner_profiles WHERE practitioner_id = ?",
                (practitioner_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_visit_type(self, visit_type_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM visit_types WHERE visit_type_id = ? AND active = 1",
                (visit_type_id,),
            ).fetchone()
        return dict(row) if row else None

    def working_intervals(self, clinic_id: str, weekday: str) -> list[tuple[str, str]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT start_time, end_time FROM clinic_working_hours
                WHERE clinic_id = ? AND weekday = ? ORDER BY interval_index
                """,
                (clinic_id, weekday.upper()),
            ).fetchall()
        return [(str(row["start_time"]), str(row["end_time"])) for row in rows]

    def practitioner_is_blocked(self, practitioner_id: str, start_at: datetime, end_at: datetime) -> bool:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM practitioner_blocked_periods
                WHERE practitioner_id = ? AND start_at < ? AND end_at > ? LIMIT 1
                """,
                (practitioner_id, end_at.isoformat(), start_at.isoformat()),
            ).fetchone()
        return row is not None


class SQLiteAppointmentRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _from_row(row) -> Appointment:
        return Appointment(
            appointment_id=row["appointment_id"],
            patient_id=row["patient_id"],
            practitioner_id=row["practitioner_id"],
            department_id=row["department_id"],
            location_id=row["location_id"],
            visit_type_id=row["visit_type_id"],
            start_at=row["start_at"],
            end_at=row["end_at"],
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            cancellation_reason=row["cancellation_reason"],
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get(self, appointment_id: str) -> Appointment | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM appointments WHERE appointment_id = ?", (appointment_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, patient_id: str | None = None, practitioner_id: str | None = None) -> list[Appointment]:
        query = "SELECT * FROM appointments WHERE 1=1"
        parameters: list[Any] = []
        if patient_id:
            query += " AND patient_id = ?"
            parameters.append(patient_id)
        if practitioner_id:
            query += " AND practitioner_id = ?"
            parameters.append(practitioner_id)
        query += " ORDER BY start_at"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def get_by_idempotency_key(self, idempotency_key: str) -> Appointment | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM appointments WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return self._from_row(row) if row else None

    def find_overlaps(
        self,
        *,
        patient_id: str,
        practitioner_id: str,
        start_at: datetime,
        end_at: datetime,
        exclude_appointment_id: str | None = None,
    ) -> list[Appointment]:
        query = """
            SELECT * FROM appointments
            WHERE status NOT IN ('CANCELLED', 'NO_SHOW')
              AND start_at < ? AND end_at > ?
              AND (patient_id = ? OR practitioner_id = ?)
        """
        parameters: list[Any] = [end_at.isoformat(), start_at.isoformat(), patient_id, practitioner_id]
        if exclude_appointment_id:
            query += " AND appointment_id <> ?"
            parameters.append(exclude_appointment_id)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, appointment: Appointment) -> Appointment:
        payload = appointment.model_dump(mode="json")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO appointments (
                    appointment_id, patient_id, practitioner_id, department_id,
                    location_id, visit_type_id, start_at, end_at, status,
                    idempotency_key, cancellation_reason, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(appointment_id) DO UPDATE SET
                    practitioner_id=excluded.practitioner_id,
                    department_id=excluded.department_id,
                    location_id=excluded.location_id,
                    visit_type_id=excluded.visit_type_id,
                    start_at=excluded.start_at,
                    end_at=excluded.end_at,
                    status=excluded.status,
                    cancellation_reason=excluded.cancellation_reason,
                    version=excluded.version,
                    updated_at=excluded.updated_at
                """,
                (
                    payload["appointment_id"], payload["patient_id"], payload["practitioner_id"],
                    payload["department_id"], payload["location_id"], payload["visit_type_id"],
                    payload["start_at"], payload["end_at"], payload["status"],
                    payload["idempotency_key"], payload["cancellation_reason"], payload["version"],
                    payload["created_at"], payload["updated_at"],
                ),
            )
        return appointment.model_copy(deep=True)

    def get_operation(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM appointment_operations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return dict(row) if row else None

    def create_atomic(self, appointment: Appointment, *, request_hash: str) -> Appointment:
        payload = appointment.model_dump(mode="json")
        with self.database.connection() as connection:
            if not connection.in_transaction: connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT * FROM appointment_operations WHERE idempotency_key = ?",
                (appointment.idempotency_key,),
            ).fetchone()
            if existing_operation:
                if existing_operation["operation"] != "CREATE" or existing_operation["request_hash"] != request_hash:
                    raise RepositoryConflictError("Idempotency key was used for a different request")
                existing = connection.execute(
                    "SELECT * FROM appointments WHERE appointment_id = ?",
                    (existing_operation["appointment_id"],),
                ).fetchone()
                if existing is None:
                    raise RepositoryConflictError("Idempotent appointment result is unavailable")
                return self._from_row(existing)
            conflict = connection.execute(
                """
                SELECT appointment_id FROM appointments
                WHERE status NOT IN ('CANCELLED', 'NO_SHOW')
                  AND start_at < ? AND end_at > ?
                  AND (patient_id = ? OR practitioner_id = ?)
                LIMIT 1
                """,
                (
                    payload["end_at"], payload["start_at"],
                    payload["patient_id"], payload["practitioner_id"],
                ),
            ).fetchone()
            if conflict:
                raise RepositoryConflictError("Requested slot conflicts with an existing appointment")
            connection.execute(
                """
                INSERT INTO appointments (
                    appointment_id, patient_id, practitioner_id, department_id,
                    location_id, visit_type_id, start_at, end_at, status,
                    idempotency_key, cancellation_reason, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["appointment_id"], payload["patient_id"], payload["practitioner_id"],
                    payload["department_id"], payload["location_id"], payload["visit_type_id"],
                    payload["start_at"], payload["end_at"], payload["status"],
                    payload["idempotency_key"], payload["cancellation_reason"], payload["version"],
                    payload["created_at"], payload["updated_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO appointment_operations
                    (idempotency_key, operation, appointment_id, request_hash, created_at)
                VALUES (?, 'CREATE', ?, ?, ?)
                """,
                (
                    appointment.idempotency_key,
                    appointment.appointment_id,
                    request_hash,
                    payload["created_at"],
                ),
            )
        return appointment.model_copy(deep=True)

    def update_atomic(
        self,
        appointment: Appointment,
        *,
        operation: str,
        operation_idempotency_key: str,
        request_hash: str,
        previous_version: int,
        check_overlap: bool,
    ) -> Appointment:
        payload = appointment.model_dump(mode="json")
        with self.database.connection() as connection:
            if not connection.in_transaction: connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT * FROM appointment_operations WHERE idempotency_key = ?",
                (operation_idempotency_key,),
            ).fetchone()
            if existing_operation:
                if existing_operation["operation"] != operation or existing_operation["request_hash"] != request_hash:
                    raise RepositoryConflictError("Idempotency key was used for a different request")
                existing = connection.execute(
                    "SELECT * FROM appointments WHERE appointment_id = ?",
                    (existing_operation["appointment_id"],),
                ).fetchone()
                if existing is None:
                    raise RepositoryConflictError("Idempotent appointment result is unavailable")
                return self._from_row(existing)
            current = connection.execute(
                "SELECT version FROM appointments WHERE appointment_id = ?",
                (appointment.appointment_id,),
            ).fetchone()
            if current is None:
                raise RepositoryConflictError("Appointment was not found")
            if int(current["version"]) != previous_version:
                raise RepositoryConflictError("Appointment version conflict")
            if check_overlap:
                conflict = connection.execute(
                    """
                    SELECT appointment_id FROM appointments
                    WHERE appointment_id <> ?
                      AND status NOT IN ('CANCELLED', 'NO_SHOW')
                      AND start_at < ? AND end_at > ?
                      AND (patient_id = ? OR practitioner_id = ?)
                    LIMIT 1
                    """,
                    (
                        appointment.appointment_id, payload["end_at"], payload["start_at"],
                        payload["patient_id"], payload["practitioner_id"],
                    ),
                ).fetchone()
                if conflict:
                    raise RepositoryConflictError("Requested slot conflicts with an existing appointment")
            connection.execute(
                """
                UPDATE appointments SET
                    practitioner_id=?, department_id=?, location_id=?, visit_type_id=?,
                    start_at=?, end_at=?, status=?, cancellation_reason=?, version=?, updated_at=?
                WHERE appointment_id=? AND version=?
                """,
                (
                    payload["practitioner_id"], payload["department_id"], payload["location_id"],
                    payload["visit_type_id"], payload["start_at"], payload["end_at"], payload["status"],
                    payload["cancellation_reason"], payload["version"], payload["updated_at"],
                    payload["appointment_id"], previous_version,
                ),
            )
            connection.execute(
                """
                INSERT INTO appointment_operations
                    (idempotency_key, operation, appointment_id, request_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    operation_idempotency_key, operation, appointment.appointment_id,
                    request_hash, payload["updated_at"],
                ),
            )
        return appointment.model_copy(deep=True)


class SQLiteWorkflowRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _from_row(row) -> WorkflowSession:
        return WorkflowSession.model_validate(dict(row))

    def get(self, workflow_id: str) -> WorkflowSession | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_sessions WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, patient_id: str | None = None) -> list[WorkflowSession]:
        query = "SELECT * FROM workflow_sessions"
        parameters: tuple[Any, ...] = ()
        if patient_id:
            query += " WHERE patient_id = ?"
            parameters = (patient_id,)
        query += " ORDER BY updated_at DESC"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._from_row(row) for row in rows]

    def save(self, workflow: WorkflowSession, *, expected_version: int | None = None) -> WorkflowSession:
        payload = workflow.model_dump(mode="json")
        with self.database.connection() as connection:
            existing = connection.execute(
                "SELECT version FROM workflow_sessions WHERE workflow_id = ?", (workflow.workflow_id,)
            ).fetchone()
            current_version = int(existing["version"]) if existing else 0
            if expected_version is not None and current_version != expected_version:
                raise RepositoryConflictError("Workflow version conflict")
            connection.execute(
                """
                INSERT INTO workflow_sessions (
                    workflow_id, patient_id, appointment_id, encounter_id, note_id,
                    assigned_practitioner_id, state, resume_state, version,
                    last_error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    appointment_id=excluded.appointment_id,
                    encounter_id=excluded.encounter_id,
                    note_id=excluded.note_id,
                    assigned_practitioner_id=excluded.assigned_practitioner_id,
                    state=excluded.state,
                    resume_state=excluded.resume_state,
                    version=excluded.version,
                    last_error_code=excluded.last_error_code,
                    updated_at=excluded.updated_at
                """,
                (
                    payload["workflow_id"], payload["patient_id"], payload["appointment_id"],
                    payload["encounter_id"], payload["note_id"], payload["assigned_practitioner_id"],
                    payload["state"], payload["resume_state"], payload["version"],
                    payload["last_error_code"], payload["created_at"], payload["updated_at"],
                ),
            )
        return workflow.model_copy(deep=True)


class SQLiteEncounterRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, encounter_id: str) -> Encounter | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM encounters WHERE encounter_id = ?", (encounter_id,)).fetchone()
        return Encounter.model_validate(dict(row)) if row else None

    def list(self, *, patient_id: str | None = None) -> list[Encounter]:
        query = "SELECT * FROM encounters"
        parameters: tuple[Any, ...] = ()
        if patient_id:
            query += " WHERE patient_id = ?"
            parameters = (patient_id,)
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Encounter.model_validate(dict(row)) for row in rows]

    def save(self, encounter: Encounter) -> Encounter:
        payload = encounter.model_dump(mode="json")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO encounters (
                    encounter_id, patient_id, practitioner_id, appointment_id,
                    workflow_id, status, started_at, ended_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(encounter_id) DO UPDATE SET
                    status=excluded.status,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    updated_at=excluded.updated_at
                """,
                (
                    payload["encounter_id"], payload["patient_id"], payload["practitioner_id"],
                    payload["appointment_id"], payload["workflow_id"], payload["status"],
                    payload["started_at"], payload["ended_at"], payload["created_at"], payload["updated_at"],
                ),
            )
        return encounter.model_copy(deep=True)


class SQLiteVerificationRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _from_row(row) -> VerificationRecord:
        return VerificationRecord.model_validate(dict(row))

    def get(self, challenge_id: str) -> VerificationRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM verification_challenges WHERE challenge_id = ?", (challenge_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def latest_for_patient(self, patient_id: str) -> VerificationRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM verification_challenges
                WHERE patient_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (patient_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def latest_for_workflow(self, workflow_id: str) -> VerificationRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM verification_challenges
                WHERE workflow_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (workflow_id,),
            ).fetchone()
        return self._from_row(row) if row else None

    def save(self, verification: VerificationRecord) -> VerificationRecord:
        payload = verification.model_dump(mode="json")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO verification_challenges (
                    challenge_id, patient_id, workflow_id, method,
                    normalized_phone_reference, phone_last_four, otp_digest,
                    created_at, expires_at, failed_attempts, resend_count,
                    last_sent_at, locked_until, verified_at, used_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(challenge_id) DO UPDATE SET
                    otp_digest=excluded.otp_digest,
                    expires_at=excluded.expires_at,
                    failed_attempts=excluded.failed_attempts,
                    resend_count=excluded.resend_count,
                    last_sent_at=excluded.last_sent_at,
                    locked_until=excluded.locked_until,
                    verified_at=excluded.verified_at,
                    used_at=excluded.used_at,
                    status=excluded.status
                """,
                (
                    payload["challenge_id"], payload["patient_id"], payload["workflow_id"], payload["method"],
                    payload["normalized_phone_reference"], payload["phone_last_four"], payload["otp_digest"],
                    payload["created_at"], payload["expires_at"], payload["failed_attempts"], payload["resend_count"],
                    payload["last_sent_at"], payload["locked_until"], payload["verified_at"], payload["used_at"],
                    payload["status"],
                ),
            )
        return verification.model_copy(deep=True)


class SQLiteConsentRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _from_row(row) -> ConsentRecord:
        payload = dict(row)
        payload["decision"] = bool(payload["decision"])
        return ConsentRecord.model_validate(payload)

    def get(self, consent_id: str) -> ConsentRecord | None:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM consent_records WHERE consent_id = ?", (consent_id,)).fetchone()
        return self._from_row(row) if row else None

    def list_for_encounter(self, encounter_id: str) -> list[ConsentRecord]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM consent_records WHERE encounter_id = ? ORDER BY captured_at",
                (encounter_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def latest(self, encounter_id: str, consent_type: ConsentType) -> ConsentRecord | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM consent_records
                WHERE encounter_id = ? AND consent_type = ?
                ORDER BY captured_at DESC LIMIT 1
                """,
                (encounter_id, consent_type.value),
            ).fetchone()
        return self._from_row(row) if row else None

    def save(self, consent: ConsentRecord) -> ConsentRecord:
        payload = consent.model_dump(mode="json")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO consent_records (
                    consent_id, patient_id, encounter_id, consent_type, decision,
                    consent_text_version, captured_at, captured_by, capture_method, revoked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(consent_id) DO UPDATE SET revoked_at=excluded.revoked_at
                """,
                (
                    payload["consent_id"], payload["patient_id"], payload["encounter_id"],
                    payload["consent_type"], int(payload["decision"]), payload["consent_text_version"],
                    payload["captured_at"], payload["captured_by"], payload["capture_method"],
                    payload["revoked_at"],
                ),
            )
        return consent.model_copy(deep=True)


class SQLiteAuditRepository:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def append(self, event: AuditEvent) -> AuditEvent:
        payload = event.model_dump(mode="json")
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    audit_event_id, event_type, actor_ref, action, patient_ref,
                    resource_ref, result, request_id, timestamp, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["audit_event_id"], payload["event_type"], payload["actor_ref"], payload["action"],
                    payload["patient_ref"], payload["resource_ref"], payload["result"], payload["request_id"],
                    payload["timestamp"], json.dumps(payload["metadata"], sort_keys=True),
                ),
            )
        return event.model_copy(deep=True)

    def list(self, *, patient_ref: str | None = None, event_type: str | None = None) -> list[AuditEvent]:
        query = "SELECT * FROM audit_events WHERE 1=1"
        parameters: list[Any] = []
        if patient_ref:
            query += " AND patient_ref = ?"
            parameters.append(patient_ref)
        if event_type:
            query += " AND event_type = ?"
            parameters.append(event_type)
        query += " ORDER BY timestamp"
        with self.database.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        events: list[AuditEvent] = []
        for row in rows:
            payload = dict(row)
            payload["metadata"] = json.loads(payload.pop("metadata_json"))
            events.append(AuditEvent.model_validate(payload))
        return events
