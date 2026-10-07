from __future__ import annotations

import tempfile
import unittest

from medflow.domain.enums import WorkflowState
from medflow.orchestration import (
    ClinicWorkflowOrchestrator,
    WorkflowAccessError,
    WorkflowAction,
    WorkflowConflictError,
    WorkflowTransitionError,
)
from medflow.repositories import JsonWorkflowRepository
from security_guardrails import Actor


PATIENT_A = "PT-SYNTHETIC-A"
PATIENT_B = "PT-SYNTHETIC-B"


class WorkflowOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repository = JsonWorkflowRepository(self.temporary.name)
        self.orchestrator = ClinicWorkflowOrchestrator(self.repository)
        self.receptionist = Actor("reception-1", "receptionist", {PATIENT_A}, PATIENT_A)
        self.doctor = Actor("doctor-1", "doctor", {PATIENT_A}, PATIENT_A)
        self.system = Actor.system("system_agent", PATIENT_A)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_flow_02_illegal_transition_is_rejected(self) -> None:
        workflow = self.orchestrator.create_session(patient_id=PATIENT_A, actor=self.receptionist)
        with self.assertRaises(WorkflowTransitionError):
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.START_CONSULTATION,
                actor=self.doctor,
            )

    def test_complete_deterministic_flow_requires_doctor_approval(self) -> None:
        workflow = self.orchestrator.create_session(patient_id=PATIENT_A, actor=self.receptionist)
        for action in (
            WorkflowAction.VERIFY_PATIENT,
            WorkflowAction.START_INTAKE,
            WorkflowAction.COMPLETE_INTAKE,
            WorkflowAction.REQUIRE_BOOKING,
            WorkflowAction.CONFIRM_BOOKING,
            WorkflowAction.CHECK_IN,
        ):
            workflow = self.orchestrator.perform_action(workflow.workflow_id, action, actor=self.receptionist)

        for action in (
            WorkflowAction.PREPARE_CONSULTATION,
            WorkflowAction.START_CONSULTATION,
            WorkflowAction.START_DOCUMENTATION,
        ):
            workflow = self.orchestrator.perform_action(workflow.workflow_id, action, actor=self.doctor)

        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.DOCUMENTATION_READY,
            actor=self.system,
        )
        self.assertEqual(workflow.state, WorkflowState.NOTE_REVIEW_REQUIRED)

        with self.assertRaises(WorkflowAccessError):
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.APPROVE_NOTE,
                actor=self.receptionist,
            )

        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.APPROVE_NOTE,
            actor=self.doctor,
        )
        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.COMPLETE_ENCOUNTER,
            actor=self.doctor,
        )
        self.assertEqual(workflow.state, WorkflowState.ENCOUNTER_COMPLETED)

    def test_cross_patient_access_is_denied(self) -> None:
        workflow = self.orchestrator.create_session(patient_id=PATIENT_A, actor=self.receptionist)
        other_doctor = Actor("doctor-b", "doctor", {PATIENT_B}, PATIENT_B)
        with self.assertRaises(WorkflowAccessError):
            self.orchestrator.get_session(workflow.workflow_id, actor=other_doctor)

    def test_failure_can_resume_previous_state(self) -> None:
        workflow = self.orchestrator.create_session(patient_id=PATIENT_A, actor=self.receptionist)
        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.VERIFY_PATIENT,
            actor=self.receptionist,
        )
        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.MARK_FAILED,
            actor=self.system,
            error_code="STT temporary failure with unsafe detail",
        )
        self.assertEqual(workflow.state, WorkflowState.FAILED)
        self.assertEqual(workflow.resume_state, WorkflowState.PATIENT_VERIFIED)
        self.assertNotIn(" ", workflow.last_error_code)

        workflow = self.orchestrator.perform_action(
            workflow.workflow_id,
            WorkflowAction.RESUME,
            actor=self.receptionist,
        )
        self.assertEqual(workflow.state, WorkflowState.PATIENT_VERIFIED)
        self.assertIsNone(workflow.resume_state)

    def test_stale_version_is_rejected(self) -> None:
        workflow = self.orchestrator.create_session(patient_id=PATIENT_A, actor=self.receptionist)
        with self.assertRaises(WorkflowConflictError):
            self.orchestrator.perform_action(
                workflow.workflow_id,
                WorkflowAction.VERIFY_PATIENT,
                actor=self.receptionist,
                expected_version=workflow.version + 1,
            )


if __name__ == "__main__":
    unittest.main()
