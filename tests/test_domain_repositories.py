from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from medflow.domain.enums import NoteStatus
from medflow.domain.ids import legacy_patient_id, new_id
from medflow.domain.models import Patient
from medflow.repositories import JsonNoteRepository, JsonPatientRepository


class DomainRepositoryTests(unittest.TestCase):
    def test_generated_patient_id_does_not_use_name(self) -> None:
        patient_id = new_id("PT")
        self.assertTrue(patient_id.startswith("PT-"))
        self.assertNotIn("SYNTHETIC", patient_id)

    def test_legacy_patient_is_normalized_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "patient_synthetic_en.json"
            original = {
                "name": "Synthetic Patient",
                "phone_number": "03000000000",
                "age": "40 years",
                "current_complaint": "Synthetic headache",
            }
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")
            before = path.read_bytes()

            repository = JsonPatientRepository(root)
            patient = repository.get(path.name)

            self.assertIsNotNone(patient)
            assert patient is not None
            self.assertEqual(patient.patient_id, legacy_patient_id(path.name))
            self.assertEqual(patient.legacy_ref, path.name)
            self.assertEqual(path.read_bytes(), before)

    def test_new_patient_uses_opaque_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonPatientRepository(directory)
            patient = Patient(patient_id=new_id("PT"), name="Synthetic Patient")
            repository.save(patient)

            files = list(Path(directory).glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].stem, patient.patient_id)
            self.assertNotIn("patient", files[0].stem.lower())

    def test_legacy_note_defaults_to_review_required_version_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "note_id": "NOTE-SYNTHETIC-001",
                "patient_id": "PT-SYNTHETIC-001",
                "soap": {
                    "subjective": "Synthetic fever reported.",
                    "objective": "Not documented.",
                    "assessment": "Clinical review required.",
                    "plan": "No treatment recorded.",
                },
            }
            (root / "legacy_note.json").write_text(json.dumps(payload), encoding="utf-8")

            repository = JsonNoteRepository(root)
            note = repository.get("NOTE-SYNTHETIC-001")

            self.assertIsNotNone(note)
            assert note is not None
            self.assertEqual(note.state, NoteStatus.REVIEW_REQUIRED)
            versions = repository.list_versions(note.note_id)
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].version_number, 1)
            self.assertIn("Legacy note normalized", versions[0].soap.warnings[0])


if __name__ == "__main__":
    unittest.main()
