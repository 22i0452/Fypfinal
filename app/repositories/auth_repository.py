from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass

from app.infrastructure.database import SQLiteDatabase
from medflow.domain.models import utc_now


@dataclass(frozen=True)
class AuthUser:
    user_id: int
    full_name: str
    email: str
    role: str
    active: bool
    practitioner_id: str | None = None

    @property
    def actor_role(self) -> str:
        return self.role.strip().lower()


class SQLiteAuthRepository:
    def __init__(
        self,
        database: SQLiteDatabase,
        *,
        primary_doctor_email: str = "",
    ) -> None:
        self.database = database
        self.primary_doctor_email = str(primary_doctor_email or "").strip().lower()

    @staticmethod
    def _hash_password(password: str, salt_hex: str) -> str:
        salt = bytes.fromhex(salt_hex)
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()

    def create_doctor(self, full_name: str, email: str, password: str) -> AuthUser:
        clean_name = str(full_name or "").strip()
        clean_email = str(email or "").strip().lower()
        if not clean_name or not clean_email or not password:
            raise ValueError("full_name, email, and password are required")
        if len(password) < 8:
            raise ValueError("Password must contain at least 8 characters")
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password, salt)
        with self.database.connection() as connection:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO doctors (
                        full_name, email, password_hash, salt, created_at, role, active
                    ) VALUES (?, ?, ?, ?, ?, 'DOCTOR', 1)
                    """,
                    (clean_name, clean_email, password_hash, salt, utc_now().isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Doctor with this email already exists") from exc
            user_id = int(cursor.lastrowid)
        self.database.connect_existing_doctors_to_profiles()
        user = self.get_by_id(user_id)
        if user is None:
            raise RuntimeError("Created doctor could not be loaded")
        return user

    def verify_credentials(self, email: str, password: str) -> AuthUser | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.full_name, d.email, d.password_hash, d.salt, d.role, d.active,
                       p.practitioner_id
                FROM doctors d
                LEFT JOIN practitioner_profiles p ON p.doctor_user_id = d.id
                WHERE d.email = ?
                """,
                (str(email or "").strip().lower(),),
            ).fetchone()
        if row is None or not bool(row["active"]):
            return None
        actual = self._hash_password(password, row["salt"])
        if not hmac.compare_digest(str(row["password_hash"]), actual):
            return None
        return self._row_to_user(row)

    def get_by_id(self, user_id: int) -> AuthUser | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.full_name, d.email, d.role, d.active, p.practitioner_id
                FROM doctors d
                LEFT JOIN practitioner_profiles p ON p.doctor_user_id = d.id
                WHERE d.id = ?
                """,
                (int(user_id),),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_email(self, email: str) -> AuthUser | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT d.id, d.full_name, d.email, d.role, d.active, p.practitioner_id
                FROM doctors d
                LEFT JOIN practitioner_profiles p ON p.doctor_user_id = d.id
                WHERE lower(d.email) = ?
                """,
                (str(email or "").strip().lower(),),
            ).fetchone()
        return self._row_to_user(row) if row else None

    def authorized_patient_ids(self, user: AuthUser) -> set[str]:
        if not user.practitioner_id:
            return set()
        if self.is_primary_doctor(user):
            return {"*"}
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT patient_id FROM patient_assignments
                WHERE practitioner_id = ? AND active = 1
                UNION
                SELECT patient_id FROM appointments
                WHERE practitioner_id = ? AND status NOT IN ('CANCELLED', 'NO_SHOW')
                """,
                (user.practitioner_id, user.practitioner_id),
            ).fetchall()
        return {str(row["patient_id"]) for row in rows}

    def is_primary_doctor(self, user: AuthUser) -> bool:
        if not self.primary_doctor_email:
            return False
        return str(user.email or "").strip().lower() == self.primary_doctor_email

    def ensure_primary_doctor(self, *, email: str, display_name: str) -> AuthUser | None:
        clean_email = str(email or "").strip().lower()
        clean_name = str(display_name or "").strip() or "Dr. Shahzaib Ali Khan"
        if not clean_email:
            return None
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT id FROM doctors WHERE lower(email) = ? AND active = 1",
                (clean_email,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE doctors SET full_name = ? WHERE id = ?",
                (clean_name, int(row["id"])),
            )
        self.database.connect_existing_doctors_to_profiles()
        user = self.get_by_email(clean_email)
        if user is None or not user.practitioner_id:
            return user
        with self.database.connection() as connection:
            connection.execute(
                """
                UPDATE practitioner_profiles
                SET display_name = ?, department_id = 'DEP-GM',
                    location_id = 'LOC-ISB-001', active = 1
                WHERE practitioner_id = ?
                """,
                (clean_name, user.practitioner_id),
            )
        return self.get_by_email(clean_email)

    def assign_patient(self, practitioner_id: str, patient_id: str) -> None:
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO patient_assignments (practitioner_id, patient_id, active, assigned_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(practitioner_id, patient_id)
                DO UPDATE SET active=1, assigned_at=excluded.assigned_at
                """,
                (practitioner_id, patient_id, utc_now().isoformat()),
            )

    @staticmethod
    def _row_to_user(row) -> AuthUser:
        return AuthUser(
            user_id=int(row["id"]),
            full_name=str(row["full_name"]),
            email=str(row["email"]),
            role=str(row["role"] or "DOCTOR"),
            active=bool(row["active"]),
            practitioner_id=str(row["practitioner_id"]) if row["practitioner_id"] else None,
        )
