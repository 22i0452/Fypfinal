from __future__ import annotations

import hashlib


class ReceptionistSessionRepository:
    """Bind a receptionist capability and intake revision to one workflow."""

    def __init__(self, database) -> None:
        self.database = database

    @staticmethod
    def digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def get(self, token: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM receptionist_intake_sessions WHERE token_hash = ?",
                (self.digest(token),),
            ).fetchone()
        return dict(row) if row else None

    def save(self, *, token: str, patient_id: str, workflow_id: str, revision: int) -> None:
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO receptionist_intake_sessions (token_hash, patient_id, workflow_id, revision) VALUES (?, ?, ?, ?)",
                (self.digest(token), patient_id, workflow_id, revision),
            )

    def advance(self, *, token: str, revision: int, expected_revision: int) -> bool:
        with self.database.connection() as connection:
            updated = connection.execute(
                "UPDATE receptionist_intake_sessions SET revision = ? WHERE token_hash = ? AND revision = ?",
                (revision, self.digest(token), expected_revision),
            )
            return updated.rowcount == 1
