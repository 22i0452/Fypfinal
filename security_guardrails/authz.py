from __future__ import annotations

from dataclasses import dataclass, field

from .audit import audit_event


class AuthorizationError(PermissionError):
    """Raised when an actor is not allowed to perform an action."""


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    authorized_patient_ids: set[str] = field(default_factory=set)
    current_patient_id: str = ""

    @property
    def ref(self) -> str:
        return f"{self.role}:{self.actor_id}"

    @classmethod
    def system(cls, role: str = "system_agent", patient_id: str = "") -> "Actor":
        return cls(
            actor_id=role,
            role=role,
            authorized_patient_ids={patient_id} if patient_id else set(),
            current_patient_id=patient_id,
        )


_ROLE_ACTIONS: dict[str, set[str]] = {
    "receptionist": {
        "create_intake",
        "book_appointment",
        "run_receptionist",
        "stt_intake",
        "llm_receptionist",
        "intake_extract",
        "intake_translate",
    },
    "doctor": {
        "read_patient",
        "list_patients",
        "read_notes",
        "create_note_draft",
        "approve_note",
        "finalize_note",
        "generate_previsit_summary",
        "generate_after_visit_summary",
        "generate_code_suggestions",
        "review_code_suggestion",
        "export_fhir",
        "patient_assistant_answer",
        "audio_playback",
        "module2_recording",
    },
    "patient_assistant": {"patient_assistant_answer"},
    "diarizer": {"diarize"},
    "translator": {"translate"},
    "soap_generator": {"soap_generate", "clinical_suggestions", "coding_suggestions"},
    "system_agent": {
        "diarize",
        "translate",
        "transcript_cleanup",
        "soap_generate",
        "stt_intake",
        "module2_stt",
        "llm_receptionist",
        "intake_extract",
        "intake_translate",
        "clinical_suggestions",
        "coding_suggestions",
    },
}

_PATIENT_SCOPED_ACTIONS = {
    "read_patient",
    "read_notes",
    "create_note_draft",
    "approve_note",
    "finalize_note",
    "generate_previsit_summary",
    "generate_after_visit_summary",
    "generate_code_suggestions",
    "review_code_suggestion",
    "export_fhir",
    "patient_assistant_answer",
    "audio_playback",
    "module2_recording",
}

_TOOL_POLICY: dict[str, set[str]] = {
    "diarizer": set(),
    "translator": set(),
    "soap_generator": set(),
    "patient_assistant": {"read_current_patient", "read_current_note"},
    "receptionist": {"create_intake", "book_appointment"},
    "doctor": {"read_authorized_patient", "read_authorized_notes", "approve_note"},
}


def is_patient_authorized(actor: Actor, patient_id: str) -> bool:
    if not patient_id:
        return True
    if "*" in actor.authorized_patient_ids:
        return True
    if patient_id in actor.authorized_patient_ids:
        return True
    return bool(actor.current_patient_id and patient_id == actor.current_patient_id)


def authorize(actor: Actor, action: str, patient_id: str = "") -> bool:
    allowed_actions = _ROLE_ACTIONS.get(actor.role, set())
    allowed = action in allowed_actions
    if allowed and action in _PATIENT_SCOPED_ACTIONS:
        allowed = is_patient_authorized(actor, patient_id)
    audit_event(
        "authorization_check",
        actor_ref=actor.ref,
        action=action,
        patient_ref=patient_id,
        result="allow" if allowed else "deny",
    )
    return allowed


def require_authorized(actor: Actor, action: str, patient_id: str = "") -> None:
    if not authorize(actor, action, patient_id):
        raise AuthorizationError(f"{actor.role} is not authorized for {action}")


def require_tool(actor: Actor, tool_name: str) -> None:
    allowed_tools = _TOOL_POLICY.get(actor.role, set())
    allowed = tool_name in allowed_tools
    audit_event(
        "agent_tool_check",
        actor_ref=actor.ref,
        action=f"tool:{tool_name}",
        patient_ref=actor.current_patient_id,
        result="allow" if allowed else "deny",
    )
    if not allowed:
        raise AuthorizationError(f"{actor.role} cannot use tool {tool_name}")
