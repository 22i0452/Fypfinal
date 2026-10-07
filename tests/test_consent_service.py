from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.services import AppointmentRequest, ConsentError
from medflow.domain.enums import ConsentType, EncounterStatus, WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import Encounter
from medflow.orchestration import WorkflowAction
from tests.support import build_container


class ConsentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        (
            self.settings,
            self.container,
            self.user,
            self.patient,
            self.actor,
            self.receptionist,
        ) = build_container(Path(self.temporary.name))
        now = datetime(2030, 1, 7, 8, 0, tzinfo=ZoneInfo("Asia/Karachi"))
        appointment = self.container.appointment_service.create(
            AppointmentRequest(
                patient_id=self.patient.patient_id,
                practitioner_id=self.user.practitioner_id,
                department_id="DEP-GM",
                location_id="LOC-ISB-001",
                visit_type_id="VISIT-NEW",
                start_at=datetime(2030, 1, 7, 10, 0),
                idempotency_key="consent-appointment-create",
            ),
            actor=self.actor,
            now=now,
        )
        workflow = self.container.workflow_orchestrator.create_session(
            patient_id=self.patient.patient_id, actor=self.actor
        )
        workflow = self.container.workflow_orchestrator.perform_action(
            workflow.workflow_id, WorkflowAction.VERIFY_PATIENT, actor=self.actor
        )
        for action in (
            WorkflowAction.START_INTAKE,
            WorkflowAction.COMPLETE_INTAKE,
            WorkflowAction.REQUIRE_BOOKING,
        ):
            workflow = self.container.workflow_orchestrator.perform_action(
                workflow.workflow_id, action, actor=self.receptionist
            )
        workflow = self.container.workflow_orchestrator.link_resources(
            workflow.workflow_id,
            actor=self.receptionist,
            links=__import__(
                "medflow.orchestration.clinic_workflow", fromlist=["WorkflowResourceLinks"]
            ).WorkflowResourceLinks(
                appointment_id=appointment.appointment_id,
                assigned_practitioner_id=self.user.practitioner_id,
            ),
        )
        workflow = self.container.workflow_orchestrator.perform_action(
            workflow.workflow_id, WorkflowAction.CONFIRM_BOOKING, actor=self.receptionist
        )
        workflow = self.container.workflow_orchestrator.perform_action(
            workflow.workflow_id, WorkflowAction.CHECK_IN, actor=self.receptionist
        )
        encounter = Encounter(
            encounter_id=new_id("ENC"),
            patient_id=self.patient.patient_id,
            practitioner_id=self.user.practitioner_id,
            appointment_id=appointment.appointment_id,
            workflow_id=workflow.workflow_id,
            status=EncounterStatus.READY,
        )
        self.container.encounter_repository.save(encounter)
        workflow = self.container.workflow_orchestrator.link_resources(
            workflow.workflow_id,
            actor=self.actor,
            links=__import__(
                "medflow.orchestration.clinic_workflow", fromlist=["WorkflowResourceLinks"]
            ).WorkflowResourceLinks(encounter_id=encounter.encounter_id),
        )
        workflow = self.container.workflow_orchestrator.perform_action(
            workflow.workflow_id, WorkflowAction.PREPARE_CONSULTATION, actor=self.actor
        )
        self.workflow = workflow
        self.encounter = encounter

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _decisions(self, *, documentation: bool = True, retention: bool = False):
        return {
            ConsentType.AUDIO_RECORDING: True,
            ConsentType.AI_TRANSCRIPTION: True,
            ConsentType.AI_DOCUMENTATION: documentation,
            ConsentType.AUDIO_RETENTION: retention,
        }

    def test_recording_blocked_when_any_required_consent_missing(self) -> None:
        self.container.consent_service.capture_bundle(
            encounter_id=self.encounter.encounter_id,
            decisions=self._decisions(documentation=False),
            consent_text_version="CONSENT-1.0",
            capture_method="VERBAL_CONFIRMED_BY_DOCTOR",
            actor=self.actor,
        )
        with self.assertRaisesRegex(ConsentError, "Required recording"):
            self.container.consent_service.authorize_audio_start(
                encounter_id=self.encounter.encounter_id,
                workflow_id=self.workflow.workflow_id,
                patient_id=self.patient.patient_id,
                actor=self.actor,
            )

    def test_all_required_consents_allow_audio_without_retention(self) -> None:
        records = self.container.consent_service.capture_bundle(
            encounter_id=self.encounter.encounter_id,
            decisions=self._decisions(retention=False),
            consent_text_version="CONSENT-1.0",
            capture_method="VERBAL_CONFIRMED_BY_DOCTOR",
            actor=self.actor,
        )
        self.assertEqual(len(records), 4)
        self.assertTrue(all(record.encounter_id == self.encounter.encounter_id for record in records))
        authorization = self.container.consent_service.authorize_audio_start(
            encounter_id=self.encounter.encounter_id,
            workflow_id=self.workflow.workflow_id,
            patient_id=self.patient.patient_id,
            actor=self.actor,
        )
        self.assertFalse(authorization.retain_audio)

    def test_revoked_required_consent_blocks_future_audio(self) -> None:
        records = self.container.consent_service.capture_bundle(
            encounter_id=self.encounter.encounter_id,
            decisions=self._decisions(),
            consent_text_version="CONSENT-1.0",
            capture_method="VERBAL_CONFIRMED_BY_DOCTOR",
            actor=self.actor,
        )
        recording = next(record for record in records if record.consent_type == ConsentType.AUDIO_RECORDING)
        self.container.consent_service.revoke(consent_id=recording.consent_id, actor=self.actor)
        with self.assertRaises(ConsentError):
            self.container.consent_service.authorize_audio_start(
                encounter_id=self.encounter.encounter_id,
                workflow_id=self.workflow.workflow_id,
                patient_id=self.patient.patient_id,
                actor=self.actor,
            )


if __name__ == "__main__":
    unittest.main()
