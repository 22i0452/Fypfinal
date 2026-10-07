"""Isolated browser QA server: synthetic audio/providers, real booking and storage.

Run only for tests. The /audit endpoints are not part of the production app.
"""
import io
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.inbound_call_service import FastUrduTTS
FastUrduTTS.warmup = lambda self, phrases: None
from app.main import create_app
from tests.test_central_app_auth import _settings
from fastapi import Request
from security_guardrails import SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter

root = Path(tempfile.mkdtemp(prefix="medflow-hands-free-qa-"))
settings = replace(_settings(root), app_env="test", development_quick_start_enabled=True,
                   receptionist_service_token="synthetic-browser-service-token", groq_api_key="",
                   openrouter_api_key="", primary_doctor_email="hands-free@example.test")
adapter = MockProviderAdapter()
set_gateway(SecureLLMGateway(provider="mock", adapters={"openrouter": adapter}))
app = create_app(settings)
c = app.state.container
c.initialize()
doctor = c.auth_repository.create_doctor("Synthetic Voice Doctor", "hands-free@example.test", "SyntheticPass123!")
controls = {"text": "Ahmed Khan", "stt_delay": 0, "tts_seconds": .25, "fail": False}
original_stt = adapter.transcribe

def transcription(*args, **kwargs):
    time.sleep(controls["stt_delay"])
    if controls["fail"]:
        raise RuntimeError("Synthetic transcription failure")
    adapter.set_response("stt_intake", controls["text"])
    return original_stt(*args, **kwargs)

adapter.transcribe = transcription

def synthetic_tts(text):
    import numpy as np
    import soundfile as sf
    output = io.BytesIO()
    sf.write(output, np.sin(np.arange(int(16000 * controls["tts_seconds"])) / 20).astype("float32") * .03, 16000, format="WAV")
    return c.inbound_call_service.media_store.save_audio(output.getvalue(), ext="wav"), "synthetic-QA-tone", "wav"

c.inbound_call_service.tts.synthesize = synthetic_tts

@app.post("/audit/voice-answer")
async def answer(request: Request):
    for key, value in (await request.json()).items():
        if key in controls:
            controls[key] = value
    return {"ready": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
