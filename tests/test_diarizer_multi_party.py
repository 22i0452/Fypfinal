"""Multi-party clinic diarization: Doctor, Patient, Nurse and Attendant roles."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from security_guardrails import SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter


ROOT = Path(__file__).resolve().parents[1]
MODULE2 = ROOT / "scribe"


def _load(name: str, file_name: str):
    if str(MODULE2) not in sys.path:
        sys.path.insert(0, str(MODULE2))
    spec = importlib.util.spec_from_file_location(name, MODULE2 / file_name)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {file_name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Mother brings a child with a sore throat; the doctor asks the nurse for vitals.
_CHILD_VISIT = [
    {"speaker": "Attendant", "relation": "Mother", "text": "اسلام علیکم ڈاکٹر صاحب میرے بچے کی طبیعت شدید قسم کی خراب ہے"},
    {"speaker": "Doctor", "text": "و علیکم اسلام تشریف رکھئے بیٹا آپ کا نام کیا ہے"},
    {"speaker": "Patient", "text": "میرا نام احمد علی ہے"},
    {"speaker": "Attendant", "relation": "Mother", "text": "اس کو تین چار دنوں سے گلے میں شدید درد ہے"},
    {"speaker": "Doctor", "addressed_to": "Nurse", "text": "سسٹر ذرا اس کا ٹمپریچر چیک کریں"},
    {"speaker": "Nurse", "text": "ڈاکٹر صاحب ٹمپریچر ایک سو ایک ہے"},
    {"speaker": "Doctor", "addressed_to": "Attendant", "text": "میں دوائیاں لکھ رہا ہوں یہ گولیاں اس کو صبح اور شام دینی ہیں"},
]


class MultiPartyDiarizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load("multi_party_diarizer", "llm_diarizer.py")
        self.diarizer = self.module.LLMDiarizer()
        self.diarizer._provider = None

    def tearDown(self) -> None:
        set_gateway(None)

    def test_canonical_speaker_maps_roles_and_relations(self) -> None:
        canonical = self.diarizer._canonical_speaker
        self.assertEqual(canonical("Nurse"), "Nurse")
        self.assertEqual(canonical("Mother"), "Attendant")
        self.assertEqual(canonical("Patient's mother"), "Attendant")
        self.assertEqual(canonical("guardian"), "Attendant")
        self.assertEqual(canonical("Receptionist"), "Unknown")
        self.assertEqual(canonical("Doctor"), "Doctor")

        entry = self.diarizer._normalize_entry({"speaker": "Mother", "text": "x"})
        self.assertEqual(entry, {"speaker": "Attendant", "relation": "Mother", "text": "x"})
        doctor = self.diarizer._normalize_entry({"speaker": "Doctor", "addressed_to": "nurse", "text": "x"})
        self.assertEqual(doctor["addressed_to"], "Nurse")
        self.assertNotIn("relation", doctor)

    def test_diarize_keeps_attendant_nurse_and_addressee(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response("diarization", {"conversation": _CHILD_VISIT})
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        result = self.diarizer.diarize_transcript(" ".join(item["text"] for item in _CHILD_VISIT))

        self.assertEqual(
            [(item["speaker"], item["speaker_relation"], item["addressed_to"]) for item in result],
            [
                ("Attendant", "Mother", None),
                ("Doctor", None, None),
                ("Patient", None, None),
                ("Attendant", "Mother", None),
                ("Doctor", None, "Nurse"),
                ("Nurse", None, None),
                ("Doctor", None, "Attendant"),
            ],
        )
        self.assertEqual([item["utterance_id"] for item in result], [f"U{i}" for i in range(1, 8)])
        self.assertFalse(any(item["needs_review"] for item in result))

    def test_relabel_detects_parent_reporting_child_illness(self) -> None:
        relabeled = self.diarizer._relabel_turns(
            [
                {"speaker": "Patient", "text": "ڈاکٹر صاحب میرے بچے کی طبعیت شدید قسم کی خراب ہے"},
                {"speaker": "Doctor", "text": "سسٹر ان کا BP چیک کریں"},
            ]
        )
        self.assertEqual(relabeled[0]["speaker"], "Attendant")
        self.assertEqual(relabeled[1]["addressed_to"], "Nurse")

    def test_relabel_keeps_doctor_instruction_to_nurse_despite_patient_cues(self) -> None:
        relabeled = self.diarizer._relabel_turns(
            [{"speaker": "Doctor", "addressed_to": "Nurse", "text": "ڈاکٹر صاحب سسٹر ذرا ان کا بی پی اور ٹمپریچر چیک کریں"}]
        )
        self.assertEqual(relabeled[0]["speaker"], "Doctor")
        self.assertEqual(relabeled[0]["addressed_to"], "Nurse")

    def test_relabel_does_not_override_llm_nurse_or_attendant(self) -> None:
        relabeled = self.diarizer._relabel_turns(
            [
                {"speaker": "Nurse", "text": "ڈاکٹر صاحب مجھے لگتا ہے بخار ہے دوا دے دی ہے"},
                {"speaker": "Attendant", "relation": "Father", "text": "ڈاکٹر صاحب اس کو بخار اور درد ہے"},
            ]
        )
        self.assertEqual([item["speaker"] for item in relabeled], ["Nurse", "Attendant"])
        self.assertEqual(relabeled[1]["relation"], "Father")

    def test_attendant_blob_splits_only_at_doctor_speech(self) -> None:
        split = self.diarizer._split_mixed_speaker_turns(
            [
                {
                    "speaker": "Attendant",
                    "relation": "Mother",
                    "text": "ڈاکٹر صاحب اس کو گلے میں بہت درد ہے پہلی چیز تو یہ ہے کہ پین کلرز دیں",
                }
            ]
        )
        self.assertEqual([item["speaker"] for item in split], ["Attendant", "Doctor"])
        self.assertEqual(split[0]["relation"], "Mother")

    def test_unknown_not_filled_by_alternation_in_multi_party_visit(self) -> None:
        entries = [
            {"speaker": "Doctor", "text": "a"},
            {"speaker": "Unknown", "text": "b"},
            {"speaker": "Doctor", "text": "c"},
            {"speaker": "Attendant", "text": "d"},
        ]
        self.assertEqual(self.diarizer._fill_unknowns(entries)[1]["speaker"], "Unknown")
        two_party = entries[:3]
        self.assertEqual(self.diarizer._fill_unknowns(two_party)[1]["speaker"], "Patient")

    def test_diarize_infers_mother_when_llm_omits_relation(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "diarization",
            {
                "conversation": [
                    {"speaker": "Attendant", "text": "اسلام علیکم ڈاکٹر صاحب"},
                    {"speaker": "Doctor", "text": "وعلیکم السلام کیسے آنا ہوا آپ کا؟"},
                    {"speaker": "Attendant", "text": "ڈاکٹر صاحب یہ میرا بیٹا ہے جس کو پیٹ میں درد ہوتا ہے"},
                    {"speaker": "Doctor", "addressed_to": "Attendant", "text": "میں کچھ میڈیسنز لکھ کے دے رہا ہوں وہ آپ نے دینی ہے"},
                    {"speaker": "Attendant", "text": "ٹھیک ہو گیا ڈاکٹر صاحب میں اس تجویز پر عمل کروں گی"},
                ]
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        result = self.diarizer.diarize_transcript("اسلام علیکم ڈاکٹر صاحب یہ میرا بیٹا ہے عمل کروں گی دوائی")

        attendants = [item for item in result if item["speaker"] == "Attendant"]
        self.assertEqual(len(attendants), 3)
        self.assertEqual({item["speaker_relation"] for item in attendants}, {"Mother"})

    def _relation(self, turns: list[tuple[str, str]], context: dict | None = None) -> set:
        entries = [{"speaker": speaker, "text": text} for speaker, text in turns]
        inferred = self.diarizer._infer_relations(entries, context)
        return {item.get("relation") for item in inferred if item["speaker"] == "Attendant"}

    def test_infer_relation_from_kinship_and_gender(self) -> None:
        # Feminine first-person verb.
        self.assertEqual(
            self._relation([("Attendant", "یہ میرا بیٹا ہے"), ("Attendant", "میں خیال رکھوں گی")]),
            {"Mother"},
        )
        # Doctor addresses her in the feminine.
        self.assertEqual(
            self._relation([("Attendant", "یہ میری بیٹی ہے اس کو بخار ہے"), ("Doctor", "آپ بتا سکتی ہیں کب سے ہے؟")]),
            {"Mother"},
        )
        # Masculine first-person verb.
        self.assertEqual(
            self._relation([("Attendant", "میرا بچہ بیمار ہے میں اس کو لے کر آیا ہوں میں دوائی دوں گا")]),
            {"Father"},
        )
        self.assertEqual(self._relation([("Attendant", "میرے شوہر کو سینے میں درد ہے")]), {"Wife"})
        self.assertEqual(self._relation([("Attendant", "میری امی کو شوگر ہے میں دیکھتی ہوں")]), {"Daughter"})

    def test_infer_relation_uses_child_age_and_refines_generic(self) -> None:
        self.assertEqual(self._relation([("Attendant", "اس کو بخار ہے")], {"age": "6 years"}), {"Parent"})
        self.assertEqual(self._relation([("Attendant", "اس کو بخار ہے")], {"age": "8 months"}), {"Parent"})
        self.assertEqual(self._relation([("Attendant", "اس کو بخار ہے")], {"age": "45"}), {None})
        entries = [{"speaker": "Attendant", "relation": "Parent", "text": "میرا بیٹا ہے میں عمل کروں گی"}]
        self.assertEqual(self.diarizer._infer_relations(entries)[0]["relation"], "Mother")

    def test_infer_relation_leaves_distinct_attendants_alone(self) -> None:
        entries = [
            {"speaker": "Attendant", "relation": "Mother", "text": "a"},
            {"speaker": "Doctor", "text": "b"},
            {"speaker": "Attendant", "relation": "Father", "text": "c"},
        ]
        self.assertEqual(self.diarizer._infer_relations(entries), entries)

    def test_greeting_to_child_starts_doctor_turn(self) -> None:
        split = self.diarizer._split_mixed_speaker_turns(
            [{"speaker": "Attendant", "relation": "Mother", "text": "اس کو الٹی آ جاتی ہے تو اس کا آپ بتائیں بچے کیسے ہو؟"}]
        )
        self.assertEqual([item["speaker"] for item in split], ["Attendant", "Doctor"])
        self.assertTrue(split[1]["text"].startswith("بچے کیسے ہو"))

    def test_turn_calling_the_child_is_not_the_patient(self) -> None:
        relabeled = self.diarizer._relabel_turns(
            [
                {"speaker": "Patient", "text": "بچے بچے یہ ٹوپی لے لو"},
                {"speaker": "Attendant", "relation": "Mother", "text": "بہت شکریہ"},
                # Elderly patient addressing a young doctor as "بیٹا" stays Patient.
                {"speaker": "Patient", "text": "بیٹا مجھے کمر میں درد ہے"},
            ]
        )
        self.assertEqual(relabeled[0]["speaker"], "Doctor")
        self.assertEqual(relabeled[0]["addressed_to"], "Patient")
        self.assertEqual(relabeled[2]["speaker"], "Patient")

    def test_merge_keeps_different_attendants_apart(self) -> None:
        merged = self.diarizer._merge_adjacent_turns(
            [
                {"speaker": "Attendant", "relation": "Mother", "text": "a"},
                {"speaker": "Attendant", "relation": "Father", "text": "b"},
                {"speaker": "Attendant", "relation": "Father", "text": "c"},
            ]
        )
        self.assertEqual([item["text"] for item in merged], ["a", "b c"])


class MultiPartyDownstreamTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    def test_translation_preserves_attendant_relation_and_addressee(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "translation",
            {
                "conversation": [
                    {"utterance_id": "U1", "speaker": "Attendant", "text": "My child is very unwell."},
                    {"utterance_id": "U2", "speaker": "Doctor", "text": "Sister, check his temperature."},
                ]
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        module = _load("multi_party_translator", "translator.py")
        source = [
            {"utterance_id": "U1", "speaker": "Attendant", "speaker_relation": "Mother", "text": "x"},
            {"utterance_id": "U2", "speaker": "Doctor", "addressed_to": "Nurse", "text": "y"},
        ]

        result = module.MedicalTranslator().translate_conversation(source)

        self.assertEqual([item["speaker"] for item in result], ["Attendant", "Doctor"])
        self.assertEqual(result[0]["speaker_relation"], "Mother")
        self.assertEqual(result[1]["addressed_to"], "Nurse")
        self.assertFalse(result[0]["needs_review"])

    def test_documentation_service_round_trips_new_fields(self) -> None:
        from app.services.documentation_service import DocumentationService
        from medflow.domain.enums import Speaker

        utterance = DocumentationService._utterance(
            "TRN-1",
            {"speaker": "Attendant", "speaker_relation": "Mother", "addressed_to": "Doctor", "text": "x"},
            1,
        )
        self.assertEqual(utterance.speaker, Speaker.ATTENDANT)
        self.assertEqual(utterance.speaker_relation, "Mother")
        self.assertEqual(utterance.addressed_to, Speaker.DOCTOR)
        self.assertFalse(utterance.needs_review)

        payload = DocumentationService.utterance_payload(utterance)
        self.assertEqual(payload["speaker"], "Attendant")
        self.assertEqual(payload["speaker_relation"], "Mother")
        self.assertEqual(payload["addressed_to"], "Doctor")

        nurse = DocumentationService._utterance("TRN-1", {"speaker": "Nurse", "speaker_relation": "Mother", "text": "x"}, 2)
        self.assertEqual(nurse.speaker, Speaker.NURSE)
        self.assertIsNone(nurse.speaker_relation)

    def test_soap_transcript_labels_and_fallback_sources(self) -> None:
        module = _load("multi_party_soap", "soap_generator.py")
        conversation, normalized = module._format_transcript(
            [
                {"utterance_id": "U1", "speaker": "Attendant", "speaker_relation": "Mother", "text": "My son has a sore throat."},
                {"utterance_id": "U2", "speaker": "Doctor", "addressed_to": "Nurse", "text": "Please check his temperature."},
                {"utterance_id": "U3", "speaker": "Nurse", "text": "Temperature is 101 F."},
            ]
        )
        self.assertIn("U1 [Attendant (Mother)]:", conversation)
        self.assertIn("U2 [Doctor -> Nurse]:", conversation)

        subjective, objective, _, plan = module._fallback_sources(normalized)
        self.assertEqual([uid for uid, _ in subjective], ["U1"])
        self.assertEqual([uid for uid, _ in objective], ["U3"])
        self.assertEqual([uid for uid, _ in plan], ["U2"])


if __name__ == "__main__":
    unittest.main()
