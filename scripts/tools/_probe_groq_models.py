from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from security_guardrails.provider_adapters import GroqProviderAdapter

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"')
adapter = GroqProviderAdapter(key)
for model in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b"):
    try:
        out = adapter.chat(
            task_type="probe",
            model=model,
            messages=[
                {"role": "system", "content": "Return only JSON."},
                {"role": "user", "content": 'Return {"ok": true}'},
            ],
            temperature=0,
            max_tokens=40,
            response_format={"type": "json_object"},
        )
        print(model, "OK", out[:120].replace("\n", " "))
    except Exception as exc:
        print(model, "FAIL", type(exc).__name__, str(exc)[:200])
