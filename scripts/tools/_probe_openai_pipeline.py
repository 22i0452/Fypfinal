"""Local probe for OpenAI diarization / translation / SOAP (dev only)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from security_guardrails import Actor, SecureLLMGateway, set_gateway
from scribe.llm_diarizer import LLMDiarizer
from scribe.soap_generator import SOAPGenerator
from scribe.translator import MedicalTranslator


SAMPLE = (
    "اسلام علیکم ڈاکٹر صاحب کیسے ہیں؟ و علیکم اسلام میں ٹھیک ہوں۔ "
    "ڈاکٹر صاحب میری کمر میں شدید درد ہے۔ آپ آرام کریں میں دوا لکھ دیتا ہوں۔"
)


def main() -> None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    print("openai_key_set:", bool(key), "len:", len(key))
    print("model:", os.getenv("OPENAI_DIARIZATION_MODEL", "gpt-4.1"))
    set_gateway(SecureLLMGateway(provider="openai"))

    try:
        from security_guardrails.provider_adapters import OpenAIProviderAdapter

        raw = OpenAIProviderAdapter(key).chat(
            task_type="probe",
            model=os.getenv("OPENAI_DIARIZATION_MODEL", "gpt-4.1"),
            messages=[
                {"role": "system", "content": "Return only JSON."},
                {"role": "user", "content": 'Return {"ok": true}'},
            ],
            temperature=0,
            max_tokens=50,
            response_format={"type": "json_object"},
        )
        print("RAW_OK", raw[:200])
    except Exception as exc:
        print("RAW_FAIL", type(exc).__name__, exc)

    diarizer = LLMDiarizer()
    diarizer._provider = "openai"
    try:
        turns = diarizer.diarize_transcript(SAMPLE, patient_ref="PT-TEST")
        print("DIAR_OK", json.dumps(turns, ensure_ascii=False)[:1000])
    except Exception as exc:
        print("DIAR_FAIL", type(exc).__name__, exc)
        return

    translator = MedicalTranslator()
    try:
        translated = translator.translate_conversation(turns, patient_ref="PT-TEST")
        print("TR_OK", json.dumps(translated, ensure_ascii=False)[:1000])
    except Exception as exc:
        print("TR_FAIL", type(exc).__name__, exc)
        translated = turns

    soap = SOAPGenerator()
    try:
        note = soap.generate({"_id": "PT-TEST", "age": "40"}, translated)
        print(
            "SOAP_OK",
            json.dumps(
                {
                    "subjective": str(note.get("subjective", ""))[:180],
                    "objective": str(note.get("objective", ""))[:180],
                    "assessment": str(note.get("assessment", ""))[:180],
                    "plan": str(note.get("plan", ""))[:180],
                    "mode": note.get("generation_mode"),
                    "issues": note.get("validation_issues"),
                },
                ensure_ascii=False,
            ),
        )
    except Exception as exc:
        print("SOAP_FAIL", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
