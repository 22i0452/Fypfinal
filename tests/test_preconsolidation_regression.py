from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import web_server
from receptionist import booking_scheduler
from security_guardrails import SecureLLMGateway, set_gateway
from security_guardrails.provider_adapters import MockProviderAdapter
from tests.support import test_settings


ROOT = Path(__file__).resolve().parents[1]
MODULE2 = ROOT / "scribe"


def _load_module2_server():
    if str(MODULE2) not in sys.path:
        sys.path.insert(0, str(MODULE2))
    spec = importlib.util.spec_from_file_location("baseline_module2_server", MODULE2 / "soap_server.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load Module 2 server")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PreConsolidationRegressionTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_gateway(None)

    def test_legacy_login_and_dashboard_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = web_server.create_app(test_settings(Path(directory)))
            with TestClient(app) as client:
                signup = client.post(
                    "/api/consultation/signup",
                    json={
                        "full_name": "Dr. Synthetic Baseline",
                        "email": "baseline@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                self.assertEqual(signup.status_code, 200)
                login = client.post(
                    "/api/consultation/login",
                    json={"email": "baseline@example.test", "password": "SyntheticPass123!"},
                )
                self.assertEqual(login.status_code, 200)
                self.assertEqual(client.get("/api/consultation/me").status_code, 200)
                self.assertEqual(client.get("/consultation/dashboard").status_code, 200)

    def test_module2_workspace_and_websocket_transport_contract(self) -> None:
        os.environ["MEDFLOW_LLM_PROVIDER"] = "mock"
        module = _load_module2_server()
        with tempfile.TemporaryDirectory() as directory:
            app = module.create_app(test_settings(Path(directory)))
            with TestClient(app) as client:
                client.post(
                    "/api/auth/signup",
                    json={
                        "full_name": "Dr. Synthetic Socket",
                        "email": "socket@example.test",
                        "password": "SyntheticPass123!",
                    },
                )
                client.post(
                    "/api/auth/login",
                    json={"email": "socket@example.test", "password": "SyntheticPass123!"},
                )
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Clinical Notes Workspace", response.text)
                with client.websocket_connect("/ws") as websocket:
                    websocket.send_text(json.dumps({"type": "ping"}))
                    self.assertEqual(websocket.receive_json()["type"], "pong")

    def test_existing_duplicate_booking_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "patient_synthetic_en.json").write_text(
                json.dumps({"name": "Synthetic Patient", "booking_slot_time": "2030-01-02 10:00"}),
                encoding="utf-8",
            )
            result = booking_scheduler.evaluate_booking_slot("2030-01-02 10:00", root)
            self.assertEqual(result.status, "unavailable")

    def test_mock_translation_to_soap_contract(self) -> None:
        mock = MockProviderAdapter()
        mock.set_response(
            "translation",
            {
                "conversation": [
                    {"speaker": "Patient", "text": "Patient reports synthetic fever."}
                ]
            },
        )
        mock.set_response(
            "soap_generation",
            {
                "subjective": "Patient reports synthetic fever.",
                "objective": "Not documented.",
                "assessment": "Fever.",
                "plan": "Rest and clinician review.",
                "visit_date": "2030-01-02",
                "generated_by": "AI Medical Scribe",
                "evidence": [{"utterance_id": "U1", "quote": "synthetic fever"}],
            },
        )
        set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": mock}))

        translator_spec = importlib.util.spec_from_file_location("baseline_translator", MODULE2 / "translator.py")
        soap_spec = importlib.util.spec_from_file_location("baseline_soap", MODULE2 / "soap_generator.py")
        assert translator_spec and translator_spec.loader and soap_spec and soap_spec.loader
        translator_module = importlib.util.module_from_spec(translator_spec)
        soap_module = importlib.util.module_from_spec(soap_spec)
        translator_spec.loader.exec_module(translator_module)
        soap_spec.loader.exec_module(soap_module)

        translated = translator_module.MedicalTranslator().translate_conversation(
            [{"speaker": "Patient", "text": "Synthetic source statement."}]
        )
        soap = soap_module.SOAPGenerator().generate(
            {"_id": "PT-SYNTHETIC-BASELINE", "age": "40 years"},
            translated,
            visit_date="2030-01-02",
        )
        self.assertEqual(soap["state"], "REVIEW_REQUIRED")
        self.assertEqual(translated[0]["speaker"], "Patient")


if __name__ == "__main__":
    unittest.main()
