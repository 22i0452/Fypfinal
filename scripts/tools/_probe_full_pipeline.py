"""Probe diarization -> translation -> SOAP with current env (no secret printing)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from security_guardrails import SecureLLMGateway, set_gateway
from scribe.llm_diarizer import LLMDiarizer
from scribe.soap_generator import SOAPGenerator
from scribe.translator import MedicalTranslator

SAMPLE = (
    "اسلام علیکم ڈاکٹر صاحب کیسے ہیں؟ کیسی صحبت؟ و علیکم اسلام میں ٹھیک آپ کیسے ہیں؟ "
    "ڈاکٹر صاحب میری کمر میں شدید قسم کا درد ہے۔ میں جب بھی چلنے کی کوشش کرتا ہوں تو مجھے کافی شدید درد ہوتا ہے۔ "
    "آپ وجہ بتا سکتے ہیں؟ آپ بس اپنے خیال رکھیں۔ میں آپ کو دوا لکھ دیتا ہوں۔"
)


def main() -> None:
    set_gateway(None)
    set_gateway(SecureLLMGateway())
    print("provider", SecureLLMGateway().provider)

    diarizer = LLMDiarizer()
    turns = diarizer.diarize_transcript(SAMPLE, patient_ref="PT-TEST")
    speakers = [item.get("speaker") for item in turns]
    print("diar_speakers", speakers)
    print("diar_turns", len(turns))

    translated = MedicalTranslator().translate_conversation(turns, patient_ref="PT-TEST")
    english_nonempty = sum(1 for item in translated if str(item.get("clinical_english") or item.get("text") or "").strip())
    print("translated_entries", english_nonempty)

    note = SOAPGenerator().generate({"_id": "PT-TEST", "age": "35", "current_complaint": "back pain"}, translated)
    summary = {
        "mode": note.get("generation_mode"),
        "subjective_len": len(str(note.get("subjective") or "")),
        "objective_len": len(str(note.get("objective") or "")),
        "assessment_len": len(str(note.get("assessment") or "")),
        "plan_len": len(str(note.get("plan") or "")),
        "issues": note.get("validation_issues"),
    }
    print("soap", json.dumps(summary))


if __name__ == "__main__":
    main()
