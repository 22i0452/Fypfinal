from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "scribe").exists():
    ROOT = Path(r"C:\Users\blossom\OneDrive\Documents\New project 2\FYP_Repo")
MODULE2 = ROOT / "scribe"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from security_guardrails import (
    AI_DIFFERENTIAL_LABEL,
    AI_MANAGEMENT_LABEL,
    SecureLLMGateway,
    set_gateway,
)
from security_guardrails.provider_adapters import MockProviderAdapter


def load_soap_module():
    spec = importlib.util.spec_from_file_location("quality_soap_generator", MODULE2 / "soap_generator.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SequenceAdapter(MockProviderAdapter):
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__()
        self.sequence = list(responses)

    def chat(
        self,
        *,
        task_type: str,
        model: str,
        messages: list[dict[str, str]],
        **_: Any,
    ) -> str:
        self.calls.append(
            {
                "kind": "chat",
                "task_type": task_type,
                "model": model,
                "messages": messages,
            }
        )
        response = self.sequence.pop(0)
        return json.dumps(response)


class FailingAdapter(MockProviderAdapter):
    def chat(
        self,
        *,
        task_type: str,
        model: str,
        messages: list[dict[str, str]],
        **_: Any,
    ) -> str:
        self.calls.append(
            {
                "kind": "chat",
                "task_type": task_type,
                "model": model,
                "messages": messages,
            }
        )
        raise RuntimeError("synthetic provider failure")


class SOAPQualityTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    @staticmethod
    def _rich_response() -> dict[str, Any]:
        return {
            "subjective": (
                "The patient reports a two-day history of sore throat and fever with reduced "
                "oral intake. Symptoms began gradually and have persisted without improvement. "
                "The patient denies shortness of breath, chest pain, or vomiting."
            ),
            "objective": (
                "Temperature measured during the encounter was 38.2 C. Throat examination "
                "showed tonsillar erythema without exudate. No respiratory distress was "
                "observed by the clinician."
            ),
            "assessment": (
                "The clinician documented a working assessment of acute viral pharyngitis. "
                "The impression was based on the short symptom duration, fever, and throat "
                "erythema without exudate."
            ),
            "plan": (
                "The clinician advised oral hydration and paracetamol 500 mg every six hours "
                "as needed for fever. The patient was told to return for persistent fever, "
                "worsening swallowing difficulty, or shortness of breath."
            ),
            "visit_date": "2030-02-01",
            "generated_by": "AI Medical Scribe",
            "evidence": [
                {"utterance_id": "U1", "quote": "two-day history"},
                {"utterance_id": "U2", "quote": "Temperature measured"},
                {"utterance_id": "U3", "quote": "working assessment"},
            ],
        }

    @staticmethod
    def _rich_transcript() -> list[dict[str, str]]:
        return [
            {
                "utterance_id": "U1",
                "speaker": "Patient",
                "text": (
                    "I have had a sore throat and fever for two days with reduced oral intake. "
                    "I do not have shortness of breath, chest pain, or vomiting."
                ),
            },
            {
                "utterance_id": "U2",
                "speaker": "Doctor",
                "text": (
                    "Temperature measured today is 38.2 C. Throat examination shows tonsillar "
                    "erythema without exudate, and I observe no respiratory distress."
                ),
            },
            {
                "utterance_id": "U3",
                "speaker": "Doctor",
                "text": (
                    "My working assessment is acute viral pharyngitis. Maintain oral hydration "
                    "and take paracetamol 500 mg every six hours as needed for fever. Return for "
                    "persistent fever, worsening swallowing difficulty, or shortness of breath."
                ),
            },
        ]

    def test_rich_grounded_sections_and_objective_are_preserved(self) -> None:
        adapter = SequenceAdapter([self._rich_response()])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        soap = load_soap_module().SOAPGenerator().generate(
            {
                "_id": "PT-SYNTHETIC-QUALITY",
                "name": "Synthetic Person",
                "age": "31 years",
                "current_complaint": "Synthetic sore throat",
            },
            self._rich_transcript(),
            visit_date="2030-02-01",
            template={
                "template_id": "TPL-DETAIL-01",
                "name": "Detailed Consultation",
                "sections": ["subjective", "objective", "assessment", "plan"],
            },
        )

        self.assertGreater(len(soap["subjective"]), 160)
        self.assertIn("38.2 C", soap["objective"])
        self.assertGreater(len(soap["objective"]), 120)
        self.assertGreater(len(soap["assessment"]), 120)
        self.assertGreater(len(soap["plan"]), 150)
        self.assertEqual(soap["state"], "REVIEW_REQUIRED")
        self.assertEqual([item["utterance_id"] for item in soap["evidence"]], ["U1", "U2", "U3"])
        outbound = adapter.calls[0]["messages"]
        self.assertIn("SOAP SECTION REQUIREMENTS", outbound[0]["content"])
        self.assertIn("POTENTIAL_OBJECTIVE_SOURCE_UTTERANCES", outbound[1]["content"])
        self.assertNotIn("Synthetic Person", str(outbound))

    def test_empty_sections_receive_one_constrained_repair_attempt(self) -> None:
        malformed = {
            "subjective": "The patient reports a synthetic sore throat.",
            "objective": "",
            "assessment": "",
            "plan": "",
            "visit_date": "2030-02-01",
            "generated_by": "AI Medical Scribe",
            "evidence": [{"utterance_id": "U1", "quote": "sore throat"}],
        }
        adapter = SequenceAdapter([malformed, self._rich_response()])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        soap = load_soap_module().SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-REPAIR"},
            self._rich_transcript(),
            visit_date="2030-02-01",
        )

        self.assertEqual(len(adapter.calls), 2)
        self.assertIn("38.2 C", soap["objective"])
        self.assertIn("schema_validation_failed", adapter.calls[1]["messages"][-1]["content"])

    def test_missing_objective_becomes_an_explicit_limitation(self) -> None:
        response = {
            "subjective": "The patient reports a synthetic fever.",
            "objective": "Not documented.",
            "assessment": "Fever was reported by the patient.",
            "plan": "The clinician discussed hydration.",
            "visit_date": "2030-02-01",
            "generated_by": "AI Medical Scribe",
            "evidence": [
                {"utterance_id": "U1", "quote": "synthetic fever"},
                {"utterance_id": "U2", "quote": "hydration"},
            ],
        }
        adapter = SequenceAdapter([response])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        soap = load_soap_module().SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-NO-OBJECTIVE"},
            [
                {"utterance_id": "U1", "speaker": "Patient", "text": "I have a synthetic fever."},
                {"utterance_id": "U2", "speaker": "Doctor", "text": "Maintain hydration."},
            ],
            visit_date="2030-02-01",
        )

        self.assertIn("No vital signs", soap["objective"])
        self.assertNotEqual(soap["objective"], "Not documented.")

    def test_unsupported_objective_does_not_erase_supported_sections(self) -> None:
        response = {
            "subjective": "The patient reports a synthetic fever.",
            "objective": "Vital signs were within normal limits.",
            "assessment": "Fever was reported by the patient.",
            "plan": "The clinician advised hydration.",
            "visit_date": "2030-02-01",
            "generated_by": "AI Medical Scribe",
            "evidence": [
                {"utterance_id": "U1", "quote": "synthetic fever"},
                {"utterance_id": "U2", "quote": "hydration"},
            ],
        }
        adapter = SequenceAdapter([response, response])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        soap = load_soap_module().SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-SALVAGE"},
            [
                {"utterance_id": "U1", "speaker": "Patient", "text": "I have a synthetic fever."},
                {"utterance_id": "U2", "speaker": "Doctor", "text": "I advise hydration."},
            ],
            visit_date="2030-02-01",
        )

        self.assertEqual(soap["subjective"], response["subjective"])
        self.assertNotIn("normal limits", soap["objective"].lower())
        self.assertIn("removed", soap["objective"].lower())
        self.assertIn("unsupported_clinical_fact:objective", soap["validation_issues"])

    @staticmethod
    def _abdominal_transcript() -> list[dict[str, str]]:
        return [
            {
                "utterance_id": "U1",
                "speaker": "Patient",
                "text": (
                    "I developed central abdominal pain last night after eating food "
                    "from outside."
                ),
            },
            {
                "utterance_id": "U2",
                "speaker": "Patient",
                "text": (
                    "I have nausea but no vomiting, diarrhea, fever, or blood in my stool."
                ),
            },
        ]

    @staticmethod
    def _suggested_abdominal_response() -> dict[str, Any]:
        return {
            "subjective": (
                "The patient reports central abdominal pain beginning last night after "
                "eating food from outside, with nausea. The patient denies vomiting, "
                "diarrhea, fever, and blood in the stool."
            ),
            "objective": (
                "No vital signs, examination findings, or completed diagnostic results "
                "were documented in the supplied encounter."
            ),
            "assessment": (
                "The reported problem is acute central abdominal pain with nausea after "
                f"outside food. {AI_DIFFERENTIAL_LABEL} Foodborne gastroenteritis or "
                "gastritis may be considered because the abdominal pain and nausea began "
                "after outside food; these possibilities are not confirmed."
            ),
            "plan": (
                f"{AI_MANAGEMENT_LABEL} For the reported abdominal pain, consider a "
                "focused abdominal examination, hydration assessment, and safety-net "
                "instructions for worsening pain, fever, persistent vomiting, or blood "
                "in stool. These are considerations, not orders."
            ),
            "visit_date": "2030-02-01",
            "generated_by": "AI Medical Scribe",
            "evidence": [
                {"utterance_id": "U1", "quote": "central abdominal pain"},
                {"utterance_id": "U2", "quote": "nausea but no vomiting"},
            ],
        }

    def test_grounded_ai_differential_and_management_are_explicitly_flagged(self) -> None:
        response = self._suggested_abdominal_response()
        adapter = SequenceAdapter([response])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        soap = load_soap_module().SOAPGenerator().generate(
            {
                "_id": "PT-SYNTHETIC-ABDOMINAL",
                "name": "Synthetic Person",
                "current_complaint": "Synthetic abdominal discomfort",
            },
            self._abdominal_transcript(),
            visit_date="2030-02-01",
        )

        self.assertEqual(soap["generation_mode"], "MODEL_VALIDATED")
        self.assertIn(AI_DIFFERENTIAL_LABEL, soap["assessment"])
        self.assertIn(AI_MANAGEMENT_LABEL, soap["plan"])
        self.assertCountEqual(
            soap["review_flags"],
            [
                "ai_differential_requires_doctor_confirmation",
                "ai_management_requires_doctor_confirmation",
            ],
        )

    def test_unmarked_unsupported_diagnosis_is_removed(self) -> None:
        response = self._suggested_abdominal_response()
        response["assessment"] = (
            "The reported abdominal pain is acute appendicitis."
        )
        response["plan"] = "A clinician-stated treatment or follow-up plan was not documented."
        adapter = SequenceAdapter([response, response])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        soap = load_soap_module().SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-UNMARKED-DIAGNOSIS"},
            self._abdominal_transcript(),
            visit_date="2030-02-01",
        )

        self.assertEqual(soap["generation_mode"], "MODEL_SALVAGED")
        self.assertNotIn("appendicitis", soap["assessment"].lower())
        self.assertIn(
            "unsupported_clinical_fact:assessment",
            soap["validation_issues"],
        )

    def test_ai_suggestion_cannot_introduce_unsupported_medication_or_dose(self) -> None:
        response = self._suggested_abdominal_response()
        response["plan"] = (
            f"{AI_MANAGEMENT_LABEL} For the reported abdominal pain, start "
            "amoxicillin 500 mg twice daily."
        )
        adapter = SequenceAdapter([response, response])
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))

        soap = load_soap_module().SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-UNSUPPORTED-MEDICINE"},
            self._abdominal_transcript(),
            visit_date="2030-02-01",
        )

        self.assertEqual(soap["generation_mode"], "MODEL_SALVAGED")
        self.assertNotIn("amoxicillin", soap["plan"].lower())
        self.assertNotIn("500 mg", soap["plan"].lower())
        self.assertIn(
            "unsupported_clinical_fact:medication_or_dosage",
            soap["validation_issues"],
        )

    def test_provider_failure_fallback_preserves_clinical_transcript(self) -> None:
        adapter = FailingAdapter()
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": adapter}))
        transcript = [
            {
                "utterance_id": "U1",
                "speaker": "Patient",
                "text": "My name is Synthetic Person.",
            },
            {
                "utterance_id": "U2",
                "speaker": "Patient",
                "text": "I have had stomach pain since last night after outside food.",
            },
            {
                "utterance_id": "U3",
                "speaker": "Doctor",
                "text": "What did you eat last night?",
            },
            {
                "utterance_id": "U4",
                "speaker": "Doctor",
                "text": "Please return if the stomach pain becomes worse.",
            },
        ]

        soap = load_soap_module().SOAPGenerator().generate(
            {
                "_id": "PT-SYNTHETIC-FALLBACK",
                "current_complaint": "Synthetic follow-up",
            },
            transcript,
            visit_date="2030-02-01",
        )

        self.assertEqual(soap["generation_mode"], "TRANSCRIPT_FALLBACK")
        self.assertIn("stomach pain since last night", soap["subjective"])
        self.assertNotIn("My name is", soap["subjective"])
        self.assertIn("return if the stomach pain", soap["plan"])
        self.assertEqual(
            [item["utterance_id"] for item in soap["evidence"]],
            ["U2", "U4"],
        )
        self.assertIn("fallback_draft_requires_clinician_review", soap["review_flags"])

    def test_structured_note_marks_ai_suggestions_for_doctor_review(self) -> None:
        from app.services.documentation_service import DocumentationService
        from medflow.domain.enums import ClaimSupportStatus, Speaker
        from medflow.domain.models import TranscriptRecord, TranscriptUtterance

        soap = self._suggested_abdominal_response()
        soap["generation_mode"] = "MODEL_VALIDATED"
        soap["review_flags"] = [
            "ai_differential_requires_doctor_confirmation",
            "ai_management_requires_doctor_confirmation",
        ]
        transcript = TranscriptRecord(
            transcript_id="TRN-SYNTHETIC-SUGGESTIONS",
            patient_id="PT-SYNTHETIC-ABDOMINAL",
            encounter_id="ENC-SYNTHETIC-ABDOMINAL",
            utterances=[
                TranscriptUtterance(
                    transcript_id="TRN-SYNTHETIC-SUGGESTIONS",
                    utterance_id=item["utterance_id"],
                    speaker=Speaker.PATIENT,
                    original_text=item["text"],
                )
                for item in self._abdominal_transcript()
            ],
        )
        service = object.__new__(DocumentationService)

        structured = service.build_structured_soap(
            "NOTE-SYNTHETIC-SUGGESTIONS",
            soap,
            transcript,
        )

        self.assertEqual(
            structured.assessment[0].status,
            ClaimSupportStatus.REVIEW_REQUIRED,
        )
        self.assertEqual(
            structured.plan[0].status,
            ClaimSupportStatus.REVIEW_REQUIRED,
        )
        self.assertIn(
            "AI-suggested differential requires doctor confirmation.",
            structured.warnings,
        )
        self.assertIn(
            "AI-suggested management considerations require doctor confirmation.",
            structured.warnings,
        )


if __name__ == "__main__":
    unittest.main()
