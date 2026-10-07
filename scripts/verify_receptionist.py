"""Run synthetic receptionist tests and write reviewable evidence."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.subcases = 0

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({"test": test.id(), "result": "PASS"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({"test": test.id(), "result": "FAIL"})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({"test": test.id(), "result": "ERROR"})

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.subcases += 1
        if err:
            self.cases.append({"test": test.id(), "result": "FAIL", "subtest": True})


def main() -> int:
    from security_guardrails import SecureLLMGateway, set_gateway
    from security_guardrails.provider_adapters import MockProviderAdapter

    provider = MockProviderAdapter()
    provider.set_response("intake_intent", {"intent": "answer", "fields": []})
    set_gateway(SecureLLMGateway(provider="mock", adapters={"mock": provider}))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_receptionist*.py", top_level_dir=str(ROOT))
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = unittest.TextTestRunner(stream=output, verbosity=2, resultclass=EvidenceResult).run(suite)
    finally:
        set_gateway(None)
    artifacts = ROOT / "artifacts" / "receptionist"
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "synthetic_only": True,
        "mock_provider": True, "tests_run": result.testsRun, "subtests_run": result.subcases,
        "failures": len(result.failures), "errors": len(result.errors),
        "successful": result.wasSuccessful(), "cases": result.cases,
    }
    (artifacts / "receptionist-results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    fence = chr(96) * 3
    (artifacts / "receptionist-report.md").write_text(
        "# Receptionist verification\n\n"
        "Command: .venv/Scripts/python.exe scripts/verify_receptionist.py\n\n"
        f"Tests: {result.testsRun}; subtests: {result.subcases}; failures: {len(result.failures)}; errors: {len(result.errors)}.\n\n"
        "All patient data and provider responses are synthetic. Live microphone/STT accuracy is not measured by these tests.\n\n"
        + fence + "text\n" + output.getvalue() + "\n" + fence + "\n", encoding="utf-8",
    )
    print(output.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
