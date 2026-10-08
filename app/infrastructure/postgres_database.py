"""PostgreSQL persistence for the existing parameterized clinic repositories.

The small demo serializes DB transactions with an advisory lock, preserving the
SQLite adapter's atomic booking/checkpoint behavior across concurrent requests.
No provider call is made while a database transaction is held.
"""
from contextlib import contextmanager
import re
import sqlite3

from app.infrastructure.database import SQLiteDatabase, _SCHEMA


class Record(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def record_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Record(zip(names, values))


class Cursor:
    def __init__(self, cursor, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)


class Connection:
    def __init__(self, raw):
        self.raw = raw

    @property
    def in_transaction(self):
        return True  # connection() already opened and serialized the transaction.

    def execute(self, sql, params=()):
        import psycopg
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            # The outer transaction already owns the advisory lock.
            return Cursor(self.raw.execute('SELECT 1'))
        # Repository SQL is fixed in source. Values remain bound parameters;
        # no user input is interpolated into SQL.
        statement = sql.replace('?', '%s')
        creates_doctor = bool(re.match(r'\s*INSERT\s+INTO\s+doctors\s*\(', sql, re.I))
        if creates_doctor:
            statement += ' RETURNING id'
        try:
            cursor = self.raw.execute(statement, params)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError('Database constraint violation') from exc
        return Cursor(cursor, cursor.fetchone()['id'] if creates_doctor else None)

    def executescript(self, sql):
        for statement in sql.split(';'):
            if statement.strip():
                self.execute(statement)


class PostgresDatabase(SQLiteDatabase):
    def __init__(self, dsn):
        from contextvars import ContextVar
        self.dsn = dsn
        self._transaction = ContextVar('postgres_clinic_transaction', default=None)

    @contextmanager
    def connection(self):
        import psycopg
        existing = self._transaction.get()
        if existing is not None:
            yield existing
            return
        with psycopg.connect(self.dsn, row_factory=record_factory, connect_timeout=10) as raw:
            raw.execute("SET LOCAL lock_timeout = '10s'")
            raw.execute("SET LOCAL statement_timeout = '30s'")
            raw.execute('SELECT pg_advisory_xact_lock(7046202608)')
            connection = Connection(raw)
            token = self._transaction.set(connection)
            try:
                yield connection
            finally:
                self._transaction.reset(token)

    @contextmanager
    def transaction(self):
        with self.connection() as connection:
            yield connection

    def initialize(self):
        schema = _SCHEMA.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
        with self.connection() as db:
            db.executescript(schema)
            db.execute("CREATE TABLE IF NOT EXISTS receptionist_intake_sessions ("
                       "token_hash TEXT PRIMARY KEY, patient_id TEXT NOT NULL, "
                       "workflow_id TEXT NOT NULL UNIQUE, revision INTEGER NOT NULL CHECK (revision > 0))")
            db.execute("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'DOCTOR'")
            db.execute('ALTER TABLE doctors ADD COLUMN IF NOT EXISTS active INTEGER NOT NULL DEFAULT 1')

