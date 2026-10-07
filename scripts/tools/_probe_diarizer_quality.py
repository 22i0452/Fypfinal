"""Probe live LLM diarization quality on a mixed Urdu clinic transcript."""
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

SAMPLE = (
    "اسلام علیکم ڈاکٹر صاحب کیسے ہیں؟ کیسی صحت؟ "
    "و علیکم اسلام میں ٹھیک ہوں آپ کیسے ہیں؟ "
    "ڈاکٹر صاحب میری کمر میں شدید درد ہے میں جب چلتا ہوں تو درد بڑھ جاتا ہے۔ "
    "درد کب سے ہے اور کیا آپ کو ٹانگوں میں بھی درد ہوتا ہے؟ "
    "تقریبا دو ہفتے سے ہے اور کبھی کبھی بائیں ٹانگ میں بھی جاتا ہے۔ "
    "ٹھیک ہے میں آپ کا معائنہ کرتا ہوں آپ کو پین کلرز اور فزیوتھراپی تجویز کرتا ہوں۔"
)


def main() -> None:
    set_gateway(None)
    set_gateway(SecureLLMGateway())
    result = LLMDiarizer().diarize_transcript(SAMPLE, patient_ref="PT-DIAR-PROBE")
    print(json.dumps(
        [{"speaker": item["speaker"], "text": item["text"][:80]} for item in result],
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
