from __future__ import annotations

import io
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["APP_ENV"] = "test"
os.environ["MEDFLOW_LLM_PROVIDER"] = "mock"

from scripts.verify_guardrails import (  # noqa: E402
    audio_cleanup_succeeds,
    doctor_approval_required,
    unsupported_clinical_fact_flagged,
)


RESULTS_PATH = ROOT / "artifacts" / "clinic-agent-test-results.json"
REPORT_PATH = ROOT / "artifacts" / "clinic-agent-test-report.md"


def unittest_check(test_name: str) -> Callable[[], dict[str, Any]]:
    def run() -> dict[str, Any]:
        suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
        stream = io.StringIO()
        result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
        if not result.wasSuccessful():
            raise AssertionError("Mapped synthetic test failed")
        return {"test": test_name, "tests_run": result.testsRun}

    return run


CHECKS: list[tuple[str, str, Callable[[], dict[str, Any]]]] = [
    (
        "FLOW-01",
        "Existing MedFlow demo path still works",
        unittest_check("tests.test_preconsolidation_regression.PreConsolidationRegressionTests"),
    ),
    (
        "FLOW-02",
        "Illegal workflow transition is rejected",
        unittest_check(
            "tests.test_workflow_orchestrator.WorkflowOrchestratorTests.test_flow_02_illegal_transition_is_rejected"
        ),
    ),
    (
        "FLOW-03",
        "Consultation recording is blocked without consent",
        unittest_check(
            "tests.test_consultation_websocket.ConsultationWebSocketTests.test_flow_03_and_04_backend_blocks_then_allows_recording"
        ),
    ),
    (
        "FLOW-04",
        "Consultation recording is allowed with valid consent",
        unittest_check(
            "tests.test_consultation_websocket.ConsultationWebSocketTests.test_flow_03_and_04_backend_blocks_then_allows_recording"
        ),
    ),
    (
        "FLOW-05",
        "Duplicate appointment is prevented",
        unittest_check(
            "tests.test_appointment_service.AppointmentServiceTests.test_create_is_idempotent_and_duplicate_slot_is_prevented"
        ),
    ),
    (
        "FLOW-06",
        "Appointment can be rescheduled safely",
        unittest_check(
            "tests.test_appointment_service.AppointmentServiceTests.test_reschedule_and_cancel_lifecycle"
        ),
    ),
    (
        "FLOW-07",
        "Cancelled appointment cannot start consultation",
        unittest_check(
            "tests.test_appointment_service.AppointmentServiceTests.test_reschedule_and_cancel_lifecycle"
        ),
    ),
    (
        "FLOW-08",
        "Diarization preserves utterance IDs",
        unittest_check(
            "tests.test_transcript_identity.TranscriptIdentityTests.test_flow_08_diarization_assigns_stable_ids_and_marks_unknown"
        ),
    ),
    (
        "FLOW-09",
        "Translation preserves utterance IDs and speaker labels",
        unittest_check(
            "tests.test_transcript_identity.TranscriptIdentityTests.test_flow_09_translation_preserves_id_speaker_and_source_text"
        ),
    ),
    (
        "FLOW-10",
        "SOAP claims contain valid evidence references",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_10_and_11_soap_evidence_must_reference_known_utterances"
        ),
    ),
    (
        "FLOW-11",
        "Unknown evidence references are rejected",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_10_and_11_soap_evidence_must_reference_known_utterances"
        ),
    ),
    ("FLOW-12", "Unsupported clinical facts are flagged", unsupported_clinical_fact_flagged),
    (
        "FLOW-13",
        "AI-generated note starts as a draft",
        unittest_check(
            "tests.test_note_lifecycle.NoteLifecycleTests.test_draft_requires_submit_then_authenticated_doctor_approval"
        ),
    ),
    ("FLOW-14", "LLM output cannot approve a note", doctor_approval_required),
    (
        "FLOW-15",
        "Authenticated doctor can approve a note",
        unittest_check(
            "tests.test_note_lifecycle.NoteLifecycleTests.test_draft_requires_submit_then_authenticated_doctor_approval"
        ),
    ),
    (
        "FLOW-16",
        "Editing an approved note creates an amendment",
        unittest_check(
            "tests.test_note_lifecycle.NoteLifecycleTests.test_editing_approved_note_creates_amendment_and_preserves_history"
        ),
    ),
    (
        "FLOW-17",
        "Pre-visit summary uses approved records only",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_17_previsit_summary_uses_approved_records_only"
        ),
    ),
    (
        "FLOW-18",
        "After-visit summary rejects an unapproved note",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_18_and_19_after_visit_requires_approval_and_preserves_source"
        ),
    ),
    (
        "FLOW-19",
        "After-visit summary preserves approved content",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_18_and_19_after_visit_requires_approval_and_preserves_source"
        ),
    ),
    (
        "FLOW-20",
        "ICD suggestion rejects an unapproved note",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_20_and_21_coding_requires_approval_evidence_and_human_review"
        ),
    ),
    (
        "FLOW-21",
        "ICD suggestion retains evidence and SUGGESTED state",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_20_and_21_coding_requires_approval_evidence_and_human_review"
        ),
    ),
    (
        "FLOW-22",
        "Receptionist cannot approve clinical notes",
        unittest_check(
            "tests.test_note_lifecycle.NoteLifecycleTests.test_receptionist_cannot_read_or_approve_clinical_note"
        ),
    ),
    (
        "FLOW-23",
        "Unauthorized user cannot access another patient",
        unittest_check(
            "tests.test_workflow_orchestrator.WorkflowOrchestratorTests.test_cross_patient_access_is_denied"
        ),
    ),
    (
        "FLOW-24",
        "JSON repository continues to support the current demo",
        unittest_check("tests.test_domain_repositories.DomainRepositoryTests"),
    ),
    (
        "FLOW-25",
        "FHIR mapping produces expected R4 resource structures",
        unittest_check(
            "tests.test_clinic_extensions.ClinicExtensionTests.test_flow_25_fhir_mapping_produces_expected_r4_resource_shapes"
        ),
    ),
    ("FLOW-26", "Temporary audio cleanup still works", audio_cleanup_succeeds),
]


def run() -> int:
    results: list[dict[str, Any]] = []
    for check_id, name, check in CHECKS:
        try:
            evidence = check()
            status = "PASS"
        except Exception:
            evidence = {"error": "Synthetic verification failed; inspect the test command output."}
            status = "FAIL"
        results.append({"id": check_id, "name": name, "status": status, "evidence": evidence})
        print(f"{check_id} {status} - {name}")

    passed = sum(item["status"] == "PASS" for item in results)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic_data_only": True,
        "summary": {"passed": passed, "failed": len(results) - passed, "total": len(results)},
        "tests": results,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    REPORT_PATH.write_text(render_report(payload), encoding="utf-8")
    return 0 if passed == len(results) else 1


def render_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Clinic Agent Test Report",
        "",
        f"PASS: {payload['summary']['passed']}",
        f"FAIL: {payload['summary']['failed']}",
        f"TOTAL: {payload['summary']['total']}",
        "",
        "| Test | Status | Control |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {item['id']} | {item['status']} | {item['name']} |" for item in payload["tests"]
    )
    lines.extend(
        [
            "",
            "All checks use synthetic data and mock providers. This report is not a claim of HIPAA compliance, clinical certification, or complete production readiness.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(run())
