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


class TranscriptIdentityTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    def test_flow_08_diarization_assigns_stable_ids_and_marks_unknown(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "diarization",
            {
                "conversation": [
                    {"speaker": "Doctor", "text": "How long has this lasted?"},
                    {"speaker": "Patient", "text": "It started yesterday."},
                    {"speaker": "Uncertain", "text": "Background speech."},
                ]
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        module = _load("flow_diarizer", "llm_diarizer.py")
        diarizer = module.LLMDiarizer()
        diarizer._provider = None

        result = diarizer.diarize_transcript(
            "How long has this lasted? It started yesterday. Background speech."
        )

        self.assertEqual([item["utterance_id"] for item in result], ["U1", "U2", "U3"])
        self.assertEqual(result[2]["speaker"], "Unknown")
        self.assertTrue(result[2]["needs_review"])
        self.assertIn("original_text", result[0])

    def test_flow_09_translation_preserves_id_speaker_and_source_text(self) -> None:
        adapter = MockProviderAdapter()
        adapter.set_response(
            "translation",
            {
                "conversation": [
                    {"utterance_id": "U1", "speaker": "Patient", "text": "How long?"},
                    {"utterance_id": "U2", "speaker": "Doctor", "text": "Since yesterday."},
                ]
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        module = _load("flow_translator", "translator.py")
        source = [
            {
                "utterance_id": "U1",
                "speaker": "Doctor",
                "original_text": "Synthetic source question",
                "text": "Synthetic source question",
                "start_ms": None,
                "end_ms": None,
            },
            {
                "utterance_id": "U2",
                "speaker": "Patient",
                "original_text": "Synthetic source answer",
                "text": "Synthetic source answer",
                "start_ms": None,
                "end_ms": None,
            },
        ]

        result = module.MedicalTranslator().translate_conversation(source)

        self.assertEqual([item["utterance_id"] for item in result], ["U1", "U2"])
        self.assertEqual([item["speaker"] for item in result], ["Doctor", "Patient"])
        self.assertEqual(result[0]["original_text"], "Synthetic source question")
        self.assertEqual(result[0]["clinical_english"], "How long?")


if __name__ == "__main__":
    unittest.main()
