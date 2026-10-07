"""Probe cleanup + diarization on the user's knee-injury clinic transcript."""
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
from scribe.transcript_cleaner import TranscriptCleaner

# Noisy ASR-style blob matching the user's reported output shape.
SAMPLE = (
    "اسلام علیکم "
    "ڈاکٹر صاحب والیکم اسلام اچھا کیسے آنا ہوگا آپ کا "
    "ڈاکٹر صاحب میں اصل میں کل بائیک چلا رہا تھا جو بائیک چلا چلا تھا اگر تم بہت زور کا گیتا تو سامنے پتھر پر "
    "میرے میرے کھٹنا لگا اوپر سے گاڑ آگا میرے کھٹنا پر لگا اب میں اس ٹانگ پر بلکل بزرگ نہیں ڈال سا اور مجھے "
    "شدیر کے سامنے پر داد ہوتا ہے تو والیکم اسلام اسلام تھوڑا سا خوش لگ ہے کوئی اتنی خیرانی بات نہیں انشاء اللہ "
    "بہتری ہو گئی تو پہلی چیز تو یہ ہے کہ میں آپ کو کچھ دوائیاں کچھ پین کلیس بتا دوں یہ آپ نے لینے ایک صبح لینے "
    "اور ایک شام لینے دوسری چیز یہ ہے کہ آپ نے بہت زیادہ احتیاط کرنا ہے سارے کے بغیر نہیں چلنا اور یہ سوچن "
    "وغیرہ تھوڑے دیر کے لیے رہے گی اور یہ ہے کہ سوچن ایک بار ختم ہو جائے پھر ہم لوگ اس کے اندر ہی اسی تاکہ "
    "میں بہتر طریقے سے پتر لگ سکے کہ وہ مسئلہ کیا ہے"
)


def main() -> None:
    set_gateway(None)
    set_gateway(SecureLLMGateway())
    cleaned = TranscriptCleaner().clean(SAMPLE, patient_ref="PT-KNEE")
    print("CLEANED:")
    print(cleaned)
    print()
    turns = LLMDiarizer().diarize_transcript(cleaned, patient_ref="PT-KNEE")
    print(
        json.dumps(
            [{"speaker": item["speaker"], "text": item["text"]} for item in turns],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
