"""SQL document storage using the same validated domain models and interfaces.

Patients, transcripts, immutable note versions and summaries live in the same
database as appointments/auth, rather than the deployed container filesystem.
"""
import json
from pathlib import Path
from medflow.repositories import json_repositories as existing


class SQLDocumentStore:
    def __init__(self, database, collection):
        self.database = database
        self.collection = collection
        self.root = Path('/__medflow_documents') / collection  # identifiers only, no disk writes

    def path_for(self, key):
        return self.root / (existing._safe_key(key) + '.json')

    def read(self, key):
        existing._safe_key(key)
        with self.database.connection() as db:
            row = db.execute('SELECT payload FROM clinical_documents WHERE collection=? AND document_id=?',
                             (self.collection, key)).fetchone()
        return json.loads(row['payload']) if row else None

    def list_documents(self):
        with self.database.connection() as db:
            rows = db.execute('SELECT document_id,payload FROM clinical_documents WHERE collection=? ORDER BY document_id',
                              (self.collection,)).fetchall()
        return [(self.path_for(row['document_id']), json.loads(row['payload'])) for row in rows]

    def write(self, key, payload):
        existing._safe_key(key)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.database.connection() as db:
            if self.collection == 'note_versions':
                db.execute('INSERT INTO clinical_documents VALUES (?,?,?) ON CONFLICT(collection,document_id) DO NOTHING',
                           (self.collection, key, encoded))
                saved = db.execute('SELECT payload FROM clinical_documents WHERE collection=? AND document_id=?',
                                   (self.collection, key)).fetchone()
                if json.loads(saved['payload']) != payload:
                    raise existing.RepositoryConflictError('Note versions are immutable')
            else:
                db.execute('INSERT INTO clinical_documents VALUES (?,?,?) ON CONFLICT(collection,document_id) DO UPDATE SET payload=excluded.payload',
                           (self.collection, key, encoded))

    def delete(self, key):
        existing._safe_key(key)
        with self.database.connection() as db:
            db.execute('DELETE FROM clinical_documents WHERE collection=? AND document_id=?', (self.collection, key))


class SQLPatientRepository(existing.JsonPatientRepository):
    def __init__(self, database):
        self.store = SQLDocumentStore(database, 'patients')

    def get(self, identifier):
        if not identifier:
            return None
        payload = self.store.read(identifier)
        if payload is not None:
            return self._from_document(self.store.path_for(identifier), payload)
        return next((item for item in self.list() if item.legacy_ref == identifier), None)


def repositories(database):
    """Reuse model validation/query semantics; replace only the persistence stores."""
    result = {'patient_repository': SQLPatientRepository(database)}
    specs = [
        ('transcript_repository', existing.JsonTranscriptRepository, existing.TranscriptRecord, 'transcript_id', 'transcripts'),
        ('previsit_summary_repository', existing.JsonPreVisitSummaryRepository, existing.PreVisitSummary, 'summary_id', 'previsit'),
        ('after_visit_summary_repository', existing.JsonAfterVisitSummaryRepository, existing.AfterVisitSummary, 'after_visit_summary_id', 'after_visit'),
        ('template_repository', existing.JsonTemplateRepository, existing.ClinicalTemplate, 'template_id', 'templates'),
        ('code_suggestion_repository', existing.JsonCodeSuggestionRepository, existing.CodeSuggestion, 'code_suggestion_id', 'codes'),
    ]
    for name, cls, model, id_field, collection in specs:
        repo = cls.__new__(cls)
        repo.store = SQLDocumentStore(database, collection)
        repo.model_type, repo.id_field = model, id_field
        result[name] = repo
    note = existing.JsonNoteRepository.__new__(existing.JsonNoteRepository)
    note.notes = SQLDocumentStore(database, 'notes')
    note.versions = SQLDocumentStore(database, 'note_versions')
    result['note_repository'] = note
    return result


def initialize(database):
    with database.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS clinical_documents ('
                   'collection TEXT NOT NULL, document_id TEXT NOT NULL, payload TEXT NOT NULL, '
                   'PRIMARY KEY(collection,document_id))')
