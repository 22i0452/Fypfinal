from __future__ import annotations

import re
from dataclasses import dataclass

from medflow.domain.enums import WorkflowState
from medflow.domain.ids import new_id
from medflow.domain.models import WorkflowSession, utc_now
from medflow.repositories.json_repositories import RepositoryConflictError
from medflow.repositories.protocols import WorkflowRepository
from security_guardrails import Actor, audit_event, require_authorized
from security_guardrails.authz import is_patient_authorized

from .workflow_states import (
    CLINICAL_ACTIONS,
    EARLY_ACTIONS,
    STANDARD_TRANSITIONS,
    TERMINAL_STATES,
    WorkflowAction,
)


class WorkflowError(RuntimeError):
    pass


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowTransitionError(WorkflowError):
    pass


class WorkflowAccessError(WorkflowError):
    pass


class WorkflowConflictError(WorkflowError):
    pass


_SAFE_ERROR_RE = re.compile(r"[^A-Z0-9_:-]+")


@dataclass(frozen=True)
class WorkflowResourceLinks:
    appointment_id: str | None = None
    encounter_id: str | None = None
    note_id: str | None = None
    assigned_practitioner_id: str | None = None


class ClinicWorkflowOrchestrator:
    """Owns legal workflow changes; callers request actions, never target states."""

    def __init__(self, repository: WorkflowRepository) -> None:
        self.repository = repository

    def create_session(
        self,
        *,
        patient_id: str,
        actor: Actor,
        workflow_id: str | None = None,
    ) -> WorkflowSession:
        self._require_patient_access(actor, patient_id)
        if actor.role not in {"receptionist", "doctor", "system_agent"}:
            self._deny(actor, patient_id, "create_workflow")
        session = WorkflowSession(
            workflow_id=workflow_id or new_id("WF"),
            patient_id=patient_id,
        )
        try:
            saved = self.repository.save(session, expected_version=0)
        except RepositoryConflictError as exc:
            raise WorkflowConflictError("Workflow already exists") from exc
        self._audit(saved, actor, "create_workflow", None, saved.state)
        return saved

    def get_session(self, workflow_id: str, *, actor: Actor) -> WorkflowSession:
        session = self.repository.get(workflow_id)
        if session is None:
            raise WorkflowNotFoundError("Workflow not found")
        self._require_patient_access(actor, session.patient_id)
        return session

    def link_resources(
        self,
        workflow_id: str,
        *,
        actor: Actor,
        links: WorkflowResourceLinks,
        expected_version: int | None = None,
    ) -> WorkflowSession:
        session = self.get_session(workflow_id, actor=actor)
        if actor.role not in {"receptionist", "doctor", "system_agent"}:
            self._deny(actor, session.patient_id, "link_workflow_resources")
        self._check_expected_version(session, expected_version)
        updated = session.model_copy(
            update={
                "appointment_id": links.appointment_id or session.appointment_id,
                "encounter_id": links.encounter_id or session.encounter_id,
                "note_id": links.note_id or session.note_id,
                "assigned_practitioner_id": links.assigned_practitioner_id or session.assigned_practitioner_id,
                "version": session.version + 1,
                "updated_at": utc_now(),
            }
        )
        return self._save(updated, previous_version=session.version)

    def perform_action(
        self,
        workflow_id: str,
        action: WorkflowAction,
        *,
        actor: Actor,
        expected_version: int | None = None,
        error_code: str = "",
    ) -> WorkflowSession:
        session = self.get_session(workflow_id, actor=actor)
        self._check_expected_version(session, expected_version)
        self._require_action_role(actor, action, session.patient_id)

        if session.state in TERMINAL_STATES:
            raise WorkflowTransitionError(f"Workflow is terminal in state {session.state.value}")

        target, resume_state = self._resolve_target(session, action)
        safe_error = ""
        if action == WorkflowAction.MARK_FAILED:
            safe_error = _SAFE_ERROR_RE.sub("_", str(error_code or "WORKFLOW_FAILURE").upper())[:64]

        updated = session.model_copy(
            update={
                "state": target,
                "resume_state": resume_state,
                "last_error_code": safe_error,
                "version": session.version + 1,
                "updated_at": utc_now(),
            }
        )
        saved = self._save(updated, previous_version=session.version)
        self._audit(saved, actor, action.value, session.state, target)
        return saved

    def allowed_actions(self, workflow_id: str, *, actor: Actor) -> list[WorkflowAction]:
        session = self.get_session(workflow_id, actor=actor)
        candidates = [
            action
            for (state, action), _ in STANDARD_TRANSITIONS.items()
            if state == session.state
        ]
        if session.state not in TERMINAL_STATES:
            candidates.extend(
                [WorkflowAction.CANCEL, WorkflowAction.MARK_FAILED, WorkflowAction.REQUEST_HUMAN_ASSISTANCE]
            )
        if session.state in {WorkflowState.FAILED, WorkflowState.HUMAN_ASSISTANCE_REQUIRED} and session.resume_state:
            candidates.append(WorkflowAction.RESUME)
        if session.state == WorkflowState.FAILED and session.resume_state == WorkflowState.DOCUMENTATION_PROCESSING and not session.note_id:
            candidates.append(WorkflowAction.RETRY_DOCUMENTATION)
        return [action for action in candidates if self._role_allows(actor.role, action)]

    def _resolve_target(
        self,
        session: WorkflowSession,
        action: WorkflowAction,
    ) -> tuple[WorkflowState, WorkflowState | None]:
        standard = STANDARD_TRANSITIONS.get((session.state, action))
        if standard is not None:
            return standard, None
        if action == WorkflowAction.RETRY_DOCUMENTATION:
            if session.state != WorkflowState.FAILED or session.resume_state != WorkflowState.DOCUMENTATION_PROCESSING or session.note_id:
                raise WorkflowTransitionError("Only failed documentation without a saved note can be recorded again")
            return WorkflowState.CONSULTATION_ACTIVE, None
        if action == WorkflowAction.CANCEL:
            return WorkflowState.CANCELLED, None
        if action == WorkflowAction.MARK_FAILED:
            return WorkflowState.FAILED, session.state
        if action == WorkflowAction.REQUEST_HUMAN_ASSISTANCE:
            return WorkflowState.HUMAN_ASSISTANCE_REQUIRED, session.state
        if action == WorkflowAction.RESUME:
            if session.state not in {WorkflowState.FAILED, WorkflowState.HUMAN_ASSISTANCE_REQUIRED}:
                raise WorkflowTransitionError("Only failed or human-assistance workflows can resume")
            if session.resume_state is None or session.resume_state in TERMINAL_STATES:
                raise WorkflowTransitionError("Workflow has no resumable state")
            return session.resume_state, None
        raise WorkflowTransitionError(
            f"Action {action.value} is illegal from {session.state.value}"
        )

    def _require_action_role(self, actor: Actor, action: WorkflowAction, patient_id: str) -> None:
        if action == WorkflowAction.APPROVE_NOTE:
            try:
                require_authorized(actor, "approve_note", patient_id)
            except PermissionError as exc:
                raise WorkflowAccessError("Only an authorized doctor may approve a note") from exc
            return
        if not self._role_allows(actor.role, action):
            self._deny(actor, patient_id, action.value)

    @staticmethod
    def _role_allows(role: str, action: WorkflowAction) -> bool:
        normalized = str(role or "").lower()
        common = {
            WorkflowAction.CANCEL,
            WorkflowAction.REQUEST_HUMAN_ASSISTANCE,
            WorkflowAction.RESUME,
        }
        if normalized == "receptionist":
            return action in EARLY_ACTIONS | common
        if normalized == "doctor":
            return action in EARLY_ACTIONS | CLINICAL_ACTIONS | common
        if normalized == "system_agent":
            return action in {
                WorkflowAction.START_DOCUMENTATION,
                WorkflowAction.DOCUMENTATION_READY,
                WorkflowAction.MARK_FAILED,
                WorkflowAction.REQUEST_HUMAN_ASSISTANCE,
                WorkflowAction.RESUME,
            }
        return False

    @staticmethod
    def _require_patient_access(actor: Actor, patient_id: str) -> None:
        if not is_patient_authorized(actor, patient_id):
            audit_event(
                "authorization_denial",
                actor_ref=actor.ref,
                action="workflow_patient_access",
                patient_ref=patient_id,
                result="deny",
            )
            raise WorkflowAccessError("Actor is not authorized for this patient")

    @staticmethod
    def _deny(actor: Actor, patient_id: str, action: str) -> None:
        audit_event(
            "authorization_denial",
            actor_ref=actor.ref,
            action=action,
            patient_ref=patient_id,
            result="deny",
        )
        raise WorkflowAccessError(f"Role {actor.role} cannot perform {action}")

    @staticmethod
    def _check_expected_version(session: WorkflowSession, expected_version: int | None) -> None:
        if expected_version is not None and session.version != expected_version:
            raise WorkflowConflictError("Stale workflow version")

    def _save(self, workflow: WorkflowSession, *, previous_version: int) -> WorkflowSession:
        try:
            return self.repository.save(workflow, expected_version=previous_version)
        except RepositoryConflictError as exc:
            raise WorkflowConflictError("Concurrent workflow update") from exc

    @staticmethod
    def _audit(
        session: WorkflowSession,
        actor: Actor,
        action: str,
        from_state: WorkflowState | None,
        to_state: WorkflowState,
    ) -> None:
        audit_event(
            "workflow_transition",
            actor_ref=actor.ref,
            action=action,
            patient_ref=session.patient_id,
            result="allow",
            metadata={
                "workflow_id": session.workflow_id,
                "from_state": from_state.value if from_state else "",
                "to_state": to_state.value,
                "version": session.version,
            },
        )
