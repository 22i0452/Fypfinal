"""Copy existing local clinic records to an EMPTY PostgreSQL demo database.

Run once in the Replit Shell before starting the new PostgreSQL app if existing
local profiles/visits should be retained. Refuses to merge IDs into a used target,
never deletes source files, and commits all copied records as one transaction.
"""
import os
import re
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def migrate(source_settings, target):
    from medflow.repositories import json_repositories as legacy
    from medflow.repositories.sql_documents import repositories, initialize
    if not source_settings.database_path.is_file():
        raise RuntimeError('No source SQLite database found. Nothing was imported.')
    source=sqlite3.connect(source_settings.database_path.as_uri()+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    target.initialize();initialize(target)
    from app.services.process_trace import ProcessTraceStore
    from app.services.demo_report_service import DemoReportService
    from app.services.consultation_review import ConsultationReviewStore
    from app.services.attendance_service import AttendanceService
    from types import SimpleNamespace
    AttendanceService(SimpleNamespace(database=target)).initialize()
    ProcessTraceStore(target).initialize()
    DemoReportService(target,source_settings).initialize()
    ConsultationReviewStore(target).initialize()
    tables=['doctors','clinics','clinic_locations','departments','visit_types','clinic_working_hours',
        'practitioner_profiles','practitioner_blocked_periods','patient_assignments','appointments',
        'appointment_operations','workflow_sessions','encounters','verification_challenges','consent_records',
        'audit_events','receptionist_intake_sessions','attendance_requests','process_runs','process_events',
        'demo_test_reports','consultation_reviews']
    documents=repositories(target);counts={}
    try:
        with target.transaction() as db:
            for table in tables+['clinical_documents']:
                if db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:
                    raise RuntimeError('Target database already contains records. Import into a fresh database; no records were overwritten.')
            available={row['name'] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table not in available:continue
                rows=source.execute(f'SELECT * FROM {table}').fetchall()
                for row in rows:
                    columns=row.keys()
                    if not all(re.fullmatch('[a-z_]+',name) for name in columns):raise ValueError('Unexpected source schema')
                    db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",tuple(row))
                counts[table]=len(rows)
            # PostgreSQL SERIAL must advance past imported doctor IDs.
            if target.__class__.__name__=='PostgresDatabase':
                db.execute("SELECT setval(pg_get_serial_sequence('doctors','id'),COALESCE((SELECT MAX(id) FROM doctors),1),EXISTS(SELECT 1 FROM doctors))")
            old_patients=legacy.JsonPatientRepository(source_settings.patient_records_dir)
            for patient in old_patients.list():documents['patient_repository'].save(patient)
            counts['patients']=len(old_patients.list())
            old_notes=legacy.JsonNoteRepository(source_settings.generated_notes_dir)
            for note in old_notes.list():
                for version in old_notes.list_versions(note.note_id):documents['note_repository'].save_version(version)
                documents['note_repository'].save(note)
            counts['notes']=len(old_notes.list())
            for name,cls,folder in [
                ('transcript_repository',legacy.JsonTranscriptRepository,'_transcripts'),
                ('previsit_summary_repository',legacy.JsonPreVisitSummaryRepository,'_previsit_summaries'),
                ('after_visit_summary_repository',legacy.JsonAfterVisitSummaryRepository,'_after_visit_summaries'),
                ('template_repository',legacy.JsonTemplateRepository,'_templates'),
                ('code_suggestion_repository',legacy.JsonCodeSuggestionRepository,'_code_suggestions')]:
                old=cls(source_settings.generated_notes_dir/folder)
                models=old.list_models()
                for model in models:documents[name].save(model)
                counts[name]=len(models)
    finally:
        source.close()
    return counts


def main():
    from app.config import Settings
    from app.infrastructure.postgres_database import PostgresDatabase
    configured=Settings.from_env()
    if not configured.database_url:raise RuntimeError('Set DATABASE_URL before importing')
    source=replace(configured,storage_backend='json',demo_profiles_enabled=False)
    result=migrate(source,PostgresDatabase(configured.database_url))
    print('Import complete. Existing local files were retained.')
    print(result)


if __name__=='__main__':
    main()
