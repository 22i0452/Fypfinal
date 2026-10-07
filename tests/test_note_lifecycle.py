from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from medflow.domain.enums import ClaimSupportStatus, NoteStatus, Speaker
from medflow.domain.models import (
    ClinicalClaim,
    EvidenceReference,
    SOAPNote,
    SOAPNoteVersion,
    StructuredSOAP,
    TranscriptRecord,
    TranscriptUtterance,
)
from tests.support import build_container


class NoteLifecycleTests(unittest.TestCase):
    def _draft(self, root: Path):
        _, container, _, patient, doctor, receptionist = build_container(root)
        transcript = container.transcript_repository.save(
            TranscriptRecord(
                transcript_id="TRN-SYNTHETIC-001",
                patient_id=patient.patient_id,
                encounter_id="ENC-SYNTHETIC-001",
                utterances=[
                    TranscriptUtterance(
                        transcript_id="TRN-SYNTHETIC-001",
                        utterance_id="U1",
                        speaker=Speaker.PATIENT,
                        original_text="Synthetic symptom reported.",
                        clinical_english="Synthetic symptom reported.",
                    )
                ],
            )
        )
        structured = StructuredSOAP(
            subjective=[
                ClinicalClaim(
                    claim_id="NOTE-SYN-SUBJECTIVE-001",
                    text="Synthetic symptom reported.",
                    evidence_ids=["U1"],
                    status=ClaimSupportStatus.SUPPORTED,
                )
            ],
            objective=[ClinicalClaim(claim_id="NOTE-SYN-OBJECTIVE-001", text="Not documented.")],
            assessment=[ClinicalClaim(claim_id="NOTE-SYN-ASSESSMENT-001", text="Not documented.")],
            plan=[ClinicalClaim(claim_id="NOTE-SYN-PLAN-001", text="Not documented.")],
        )
        version = container.note_repository.save_version(
            SOAPNoteVersion(
                note_version_id="NV-SYNTHETIC-001",
                note_id="NOTE-SYNTHETIC-001",
                version_number=1,
                status=NoteStatus.AI_DRAFT,
                soap=structured,
                evidence=[
                    EvidenceReference(
                        evidence_id="U1",
                        source_type="TRANSCRIPT_UTTERANCE",
                        source_id="U1",
                    )
                ],
                transcript_id=transcript.transcript_id,
                created_by_actor_id="soap-generator-agent",
            )
        )
        note = container.note_repository.save(
            SOAPNote(
                note_id="NOTE-SYNTHETIC-001",
                patient_id=patient.patient_id,
                encounter_id="ENC-SYNTHETIC-001",
                current_version_id=version.note_version_id,
                state=NoteStatus.AI_DRAFT,
            )
        )
        return container, patient, doctor, receptionist, note

    def test_draft_requires_submit_then_authenticated_doctor_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container, _, doctor, _, note = self._draft(Path(directory))
            with self.assertRaisesRegex(Exception, "review-required"):
                container.note_lifecycle_service.approve(note.note_id, actor=doctor)

            submitted, _ = container.note_lifecycle_service.submit_for_review(note.note_id, actor=doctor)
            self.assertEqual(submitted.state, NoteStatus.REVIEW_REQUIRED)
            approved, approved_version = container.note_lifecycle_service.approve(note.note_id, actor=doctor)
            self.assertEqual(approved.state, NoteStatus.APPROVED_BY_DOCTOR)
            self.assertEqual(approved.approved_by_doctor_id, doctor.actor_id)
            self.assertEqual(approved_version.status, NoteStatus.APPROVED_BY_DOCTOR)

    def test_editing_approved_note_creates_amendment_and_preserves_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container, _, doctor, _, note = self._draft(Path(directory))
            container.note_lifecycle_service.submit_for_review(note.note_id, actor=doctor)
            container.note_lifecycle_service.approve(note.note_id, actor=doctor)

            amended, version = container.note_lifecycle_service.edit_legacy_sections(
                note.note_id,
                sections={
                    "subjective": "Doctor-authored synthetic amendment.",
                    "objective": "Not documented.",
                    "assessment": "Not documented.",
                    "plan": "Not documented.",
                },
                actor=doctor,
                change_reason="Synthetic correction",
            )

            self.assertEqual(amended.state, NoteStatus.AMENDED)
            self.assertIsNone(amended.approved_by_doctor_id)
            self.assertEqual(version.status, NoteStatus.AMENDED)
            self.assertEqual(len(container.note_lifecycle_service.versions(note.note_id, actor=doctor)), 4)

    def test_receptionist_cannot_read_or_approve_clinical_note(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            container, _, doctor, receptionist, note = self._draft(Path(directory))
            container.note_lifecycle_service.submit_for_review(note.note_id, actor=doctor)
            with self.assertRaisesRegex(Exception, "not authorized"):
                container.note_lifecycle_service.get(note.note_id, actor=receptionist)
            with self.assertRaisesRegex(Exception, "not authorized"):
                container.note_lifecycle_service.approve(note.note_id, actor=receptionist)


if __name__ == "__main__":
    unittest.main()
