"""Durable, encounter-bound processing events. No audio or provider secrets are stored."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from medflow.domain.ids import new_id


class ProcessTraceStore:
    def __init__(self, database):
        self.database = database

    def initialize(self):
        with self.database.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS process_runs (run_id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, encounter_id TEXT NOT NULL, capture_id TEXT NOT NULL, created_at TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS process_events (run_id TEXT NOT NULL REFERENCES process_runs(run_id), sequence INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id, sequence))')
            db.execute('CREATE INDEX IF NOT EXISTS process_encounter ON process_runs(encounter_id, created_at)')

    def start(self, patient_id, encounter_id, capture_id):
        run_id = new_id('RUN')
        with self.database.connection() as db:
            db.execute('INSERT INTO process_runs VALUES (?, ?, ?, ?, ?)', (run_id, patient_id, encounter_id, capture_id, datetime.now(timezone.utc).isoformat()))
        return run_id

    def append(self, run_id, stage, status, *, artifact=None, duration_ms=None):
        with self.database.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM process_events WHERE run_id=?', (run_id,)).fetchone()[0]
            event = {'run_id':run_id, 'sequence':sequence, 'stage':stage, 'status':status, 'at':datetime.now(timezone.utc).isoformat(), 'artifact':artifact or {}}
            if duration_ms is not None:
                event['duration_ms'] = max(0, round(duration_ms))
            db.execute('INSERT INTO process_events VALUES (?, ?, ?)', (run_id, sequence, json.dumps(event, ensure_ascii=False)))
        return event

    def latest(self, encounter_id, patient_id):
        with self.database.connection() as db:
            run = db.execute('SELECT * FROM process_runs WHERE encounter_id=? AND patient_id=? ORDER BY created_at DESC LIMIT 1', (encounter_id, patient_id)).fetchone()
            if not run:
                return None
            events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM process_events WHERE run_id=? ORDER BY sequence', (run['run_id'],))]
        return {**dict(run), 'events':events}
