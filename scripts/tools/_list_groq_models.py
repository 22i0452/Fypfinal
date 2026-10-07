from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"')
client = Groq(api_key=key)
models = list(client.models.list().data)
print("total", len(models))
for model in sorted(models, key=lambda item: getattr(item, "id", "")):
    model_id = str(getattr(model, "id", ""))
    print(model_id)
