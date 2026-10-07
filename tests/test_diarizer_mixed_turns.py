"""Deterministic mixed-turn split tests for Urdu clinic diarization."""
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


class MixedTurnDiarizerTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    def test_split_patient_blob_containing_doctor_plan(self) -> None:
        module = _load("mixed_diarizer", "llm_diarizer.py")
        diarizer = module.LLMDiarizer()
        mixed = (
            "ڈاکٹر صاحب میں کل بائیک چلا رہا تھا میرے گھٹنا لگا مجھے شدید درد ہوتا ہے "
            "پہلی چیز تو یہ ہے کہ میں آپ کو کچھ دوائیاں کچھ پین کلرز بتا دوں یہ آپ نے لینے "
            "ایک صبح لینے اور ایک شام لینے دوسری چیز یہ ہے کہ آپ نے بہت زیادہ احتیاط کرنا ہے"
        )
        split = diarizer._split_mixed_speaker_turns([{"speaker": "Patient", "text": mixed}])
        speakers = [item["speaker"] for item in split]
        self.assertIn("Patient", speakers)
        self.assertIn("Doctor", speakers)
        doctor_text = " ".join(item["text"] for item in split if item["speaker"] == "Doctor")
        self.assertIn("پہلی چیز", doctor_text)
        self.assertIn("پین کلرز", doctor_text)
        patient_text = " ".join(item["text"] for item in split if item["speaker"] == "Patient")
        self.assertIn("گھٹنا", patient_text)
        self.assertNotIn("پہلی چیز", patient_text)

    def test_lexicon_cleanup_fixes_common_asr_errors(self) -> None:
        module = _load("cleaner", "transcript_cleaner.py")
        cleaned = module.TranscriptCleaner._lexicon_clean(
            "میرے کھٹنا لگا شدیر درد بزرگ نہیں ڈال سا پین کلیس سوچن پتر لگ"
        )
        self.assertIn("گھٹنا", cleaned)
        self.assertIn("شدید", cleaned)
        self.assertIn("وزن نہیں ڈال", cleaned)
        self.assertIn("پین کلرز", cleaned)
        self.assertIn("سوجن", cleaned)
        self.assertIn("پتہ لگ", cleaned)

    def test_lexicon_cleanup_fixes_metal_pipe_to_motorbike(self) -> None:
        module = _load("cleaner_bike", "transcript_cleaner.py")
        noisy = (
            "ڈاکٹر صاحب، اصل میں میٹل پائپ شلال تھا۔ تو، ایک دم وہ سامنے پتھر آیا "
            "اور میں کل گیا۔ ایک ٹانگ پتھر کی پر آئی، پائپ کا گارڈ میری ٹانگ کی پر آئی۔"
        )
        cleaned = module.TranscriptCleaner._lexicon_clean(noisy)
        self.assertIn("موٹر بائیک", cleaned)
        self.assertIn("گر گیا", cleaned)
        self.assertIn("بائیک کا گارڈ", cleaned)
        self.assertNotIn("میٹل پائپ", cleaned)
        self.assertNotIn("پائپ کا گارڈ", cleaned)

    def test_diarize_uses_freeform_then_keeps_identity(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "diarization",
            {
                "conversation": [
                    {"speaker": "Patient", "text": "اسلام علیکم"},
                    {
                        "speaker": "Doctor",
                        "text": "و علیکم اسلام اچھا کیسے آنا ہوا آپ کا",
                    },
                    {
                        "speaker": "Patient",
                        "text": "ڈاکٹر صاحب میرے گھٹنا میں درد ہے",
                    },
                    {
                        "speaker": "Doctor",
                        "text": "پہلی چیز یہ ہے کہ پین کلرز لیں",
                    },
                ]
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        module = _load("flow_mixed_diarizer", "llm_diarizer.py")
        diarizer = module.LLMDiarizer()
        # Keep the mock gateway isolated from live DIARIZATION_PROVIDER in .env.
        diarizer._provider = None
        result = diarizer.diarize_transcript(
            "اسلام علیکم و علیکم اسلام اچھا کیسے آنا ہوا آپ کا "
            "ڈاکٹر صاحب میرے گھٹنا میں درد ہے پہلی چیز یہ ہے کہ پین کلرز لیں"
        )
        self.assertGreaterEqual(len(result), 3)
        self.assertEqual(result[0]["utterance_id"], "U1")
        speakers = {item["speaker"] for item in result}
        self.assertIn("Doctor", speakers)
        self.assertIn("Patient", speakers)


if __name__ == "__main__":
    unittest.main()
