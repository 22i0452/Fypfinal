from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent / "consultation.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200000)
    return digest.hex()


def create_doctor(full_name: str, email: str, password: str) -> dict:
    email = email.strip().lower()
    full_name = full_name.strip()
    if not full_name or not email or not password:
        raise ValueError("full_name, email, and password are required")

    salt_hex = os.urandom(16).hex()
    password_hash = _hash_password(password, salt_hex)

    with _connect() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO doctors (full_name, email, password_hash, salt, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (full_name, email, password_hash, salt_hex, datetime.now().isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Doctor with this email already exists") from exc

        doctor_id = int(cur.lastrowid)

    return {"id": doctor_id, "full_name": full_name, "email": email}


def verify_doctor(email: str, password: str) -> dict | None:
    email = email.strip().lower()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, full_name, email, password_hash, salt FROM doctors WHERE email = ?",
            (email,),
        ).fetchone()

    if not row:
        return None

    expected = row["password_hash"]
    actual = _hash_password(password, row["salt"])
    if expected != actual:
        return None

    return {"id": int(row["id"]), "full_name": row["full_name"], "email": row["email"]}


def get_doctor_by_id(doctor_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, full_name, email, created_at FROM doctors WHERE id = ?",
            (doctor_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": int(row["id"]),
        "full_name": row["full_name"],
        "email": row["email"],
        "created_at": row["created_at"],
    }
