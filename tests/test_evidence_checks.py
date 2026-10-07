"""Evidence receipts must follow real corrections and persisted note versions."""
import tempfile
import unittest
from pathlib import Path

from app.services.booking_flow import BookingFlow
from app.services.evidence_checks import note_evidence_report
from medflow.domain.enums import ClaimSupportStatus, Speaker
from medflow.domain.models import ClinicalClaim, StructuredSOAP, TranscriptRecord, TranscriptUtterance
from tests import test_note_lifecycle as lifecycle_fixture


def answer(**fields):
    return {"intent": "answer", "fields": {key: {"ur": value, "en": value} for key, value in fields.items()},
            "_process_metadata": {"method": "Synthetic contextual parser"}}


YES = {"intent": "yes", "fields": {}}


class BookingEvidenceTests(unittest.TestCase):
    def test_confirmation_keeps_original_and_records_separate_turn(self):
        flow = BookingFlow({"current": "age"})
        flow.handle("I am 22", answer(age="22"))
        self.assertEqual(flow.field_evidence["age"]["status"], "review")
        flow.handle("جی", YES)
        proof = flow.field_evidence["age"]
        self.assertEqual((proof["raw"], proof["source_turn_id"]), ("I am 22", "R0001"))
        self.assertEqual(proof["confirmation"], {"type": "readback", "raw": "جی", "source_turn_id": "R0002"})
        restored = BookingFlow.from_history([flow.state_message()])
        self.assertEqual(restored.field_evidence, flow.field_evidence)
        self.assertEqual(restored.evidence_turn, 2)

    def test_early_answer_keeps_origin_when_promoted(self):
        flow = BookingFlow()
        flow.handle("My name is Ali and I am 22", answer(name="Ali", age="22"))
        flow.handle("yes", YES)
        self.assertEqual(flow.pending["key"], "age")
        self.assertEqual(flow.field_evidence["age"]["source_turn_id"], "R0001")
        self.assertIsNone(flow.field_evidence["age"]["confirmation"])

    def test_correction_replaces_source_and_retains_revision(self):
        flow = BookingFlow({"current": "age"})
        flow.handle("22", answer(age="22"))
        flow.handle("No, 23", {**answer(age="23"), "intent": "no"})
        proof = flow.field_evidence["age"]
        self.assertEqual(proof["interpretation"]["en"], "23")
        self.assertEqual(proof["source_turn_id"], "R0002")
        self.assertIsNone(proof["confirmation"])
        self.assertEqual(proof["revisions"][0]["raw"], "22")
        flow.handle("no", {"intent": "no", "fields": {}})
        self.assertNotIn("age", flow.field_evidence)

    def test_invalid_rules_do_not_create_accepted_field_evidence(self):
        for field, value in [("age", "200"), ("phone", "03000000")]:
            flow = BookingFlow({"current": field})
            flow.handle(value, answer(**{field: value}))
            self.assertNotIn(field, flow.field_evidence)
            self.assertEqual(flow.last_answer["status"], "review")
            self.assertTrue(any(c["status"] == "failed" for c in flow.last_answer["checks"]))

    def test_legacy_state_does_not_invent_a_source(self):
        flow = BookingFlow({"current": "age", "values": {"name": {"ur": "Ali", "en": "Ali"}}})
        flow.handle("22", answer(age="22"))
        self.assertNotIn("name", flow.field_evidence)


class NoteEvidenceTests(unittest.TestCase):
    def test_link_and_exact_match_never_imply_clinical_support(self):
        transcript = TranscriptRecord(transcript_id="T", patient_id="P", encounter_id="E", utterances=[
            TranscriptUtterance(transcript_id="T", utterance_id="U1", speaker=Speaker.PATIENT,
                                original_text="مجھے درد ہے", clinical_english="I have knee pain.")])
        soap = StructuredSOAP(subjective=[
            ClinicalClaim(claim_id="exact", text="knee pain", evidence_ids=["U1"]),
            ClinicalClaim(claim_id="paraphrase", text="Pain in the knee", evidence_ids=["U1"]),
            ClinicalClaim(claim_id="unknown", text="Incorrect attribution", evidence_ids=["U9"]),
            ClinicalClaim(claim_id="empty", text="No attached source"),
            ClinicalClaim(claim_id="unsupported", text="Unsupported assertion", status=ClaimSupportStatus.UNSUPPORTED)],
            objective=[ClinicalClaim(claim_id="missing", text="Not documented.")])
        report = note_evidence_report(soap, transcript)
        rows = {row["claim_id"]: row for row in report["claims"]}
        self.assertEqual(report["counts"], {"statements": 6, "linked": 2, "exact_matches": 1, "review": 3, "missing": 1, "failed": 2})
        self.assertEqual(rows["exact"]["status"], "review")
        self.assertEqual(rows["exact"]["checks"][2]["status"], "review")
        self.assertEqual(rows["paraphrase"]["checks"][1]["status"], "unassessed")
        self.assertEqual(rows["unknown"]["label"], "Unknown source ID")
        self.assertEqual(rows["empty"]["checks"][0]["status"], "unassessed")
        self.assertEqual(rows["exact"]["sources"][0]["original"], "مجھے درد ہے")
        self.assertIsNone(report["confidence"])

    def test_safe_objective_placeholder_remains_missing_after_approval(self):
        soap = StructuredSOAP(objective=[ClinicalClaim(claim_id="placeholder", text="No vital signs, examination findings, or completed diagnostic results were documented in the supplied encounter.")])
        report = note_evidence_report(soap, None, state="APPROVED_BY_DOCTOR")
        self.assertEqual(report["claims"][0]["status"], "missing")
        self.assertEqual(report["counts"]["missing"], 1)
        self.assertEqual(report["claims"][0]["checks"][-1]["status"], "passed")

    def test_approval_and_amendment_use_actual_saved_version(self):
        with tempfile.TemporaryDirectory() as directory:
            c, _, doctor, _, note = lifecycle_fixture.NoteLifecycleTests()._draft(Path(directory))
            initial_note, initial_version = c.note_lifecycle_service.get(note.note_id, actor=doctor)
            c.note_lifecycle_service.submit_for_review(note.note_id, actor=doctor)
            approved, approved_version = c.note_lifecycle_service.approve(note.note_id, actor=doctor)
            report = c.note_lifecycle_service.payload(approved, approved_version)["soap"]["evidence_report"]
            self.assertEqual(report["version"], 3)
            self.assertEqual(report["claims"][0]["status"], "checked")
            self.assertEqual(report["counts"]["missing"], 3)
            self.assertEqual(report["approval"]["doctor_id"], doctor.actor_id)
            historical = c.note_lifecycle_service.payload(initial_note, initial_version)["soap"]["evidence_report"]
            self.assertEqual(historical["state"], "AI_DRAFT")
            self.assertIsNone(historical["approval"])
            amended, version = c.note_lifecycle_service.edit_legacy_sections(note.note_id, actor=doctor, sections={
                "subjective": "Doctor amendment", "objective": "Not documented.", "assessment": "Not documented.", "plan": "Not documented."})
            report = c.note_lifecycle_service.payload(amended, version)["soap"]["evidence_report"]
            self.assertEqual(report["version"], 4)
            self.assertEqual(report["claims"][0]["source_ids"], [])
            self.assertFalse(report["claims"][0]["exact_text_match"])
            self.assertIsNone(report["approval"])
            self.assertEqual(report["claims"][0]["status"], "review")
