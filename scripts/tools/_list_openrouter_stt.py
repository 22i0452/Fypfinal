"""List OpenRouter transcription models available to the configured API key."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def main() -> None:
    key = os.getenv("OPENROUTER_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY missing")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models?output_modalities=transcription",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    models = data.get("data") or []
    print(f"count={len(models)}")
    for model in models:
        mid = model.get("id", "")
        name = model.get("name", "")
        pricing = model.get("pricing") or {}
        print(f"{mid} | {name} | {pricing}")


if __name__ == "__main__":
    main()
