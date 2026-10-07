"""Probe Groq/OpenAI chat auth without printing secrets or Urdu to console."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from security_guardrails.provider_adapters import GroqProviderAdapter, OpenAIProviderAdapter, ProviderAdapterError


def probe(name: str, fn) -> None:
    try:
        out = fn()
        print(f"{name}: OK ({len(out)} chars)")
    except ProviderAdapterError as exc:
        print(f"{name}: FAIL {exc}")
    except Exception as exc:
        print(f"{name}: FAIL {type(exc).__name__}: {exc}")


def main() -> None:
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"')
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"')
    print("groq_key_set:", bool(groq_key), "openai_key_set:", bool(openai_key))

    if groq_key:
        probe(
            "groq",
            lambda: GroqProviderAdapter(groq_key).chat(
                task_type="probe",
                model=os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile"),
                messages=[
                    {"role": "system", "content": "Return only JSON."},
                    {"role": "user", "content": '{"ok":true}'},
                ],
                temperature=0,
                max_tokens=40,
                response_format={"type": "json_object"},
            ),
        )
    if openai_key:
        for model in (
            os.getenv("OPENAI_DIARIZATION_MODEL", "gpt-4.1"),
            "gpt-4o-mini",
            "gpt-4o",
        ):
            probe(
                f"openai:{model}",
                lambda model=model: OpenAIProviderAdapter(openai_key).chat(
                    task_type="probe",
                    model=model,
                    messages=[
                        {"role": "system", "content": "Return only JSON."},
                        {"role": "user", "content": 'Return {"ok": true}'},
                    ],
                    temperature=0,
                    max_tokens=40,
                    response_format={"type": "json_object"},
                ),
            )


if __name__ == "__main__":
    main()
