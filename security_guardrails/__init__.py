"""Essential MedFlowAI security guardrails."""

from .audit import audit_event, get_audit_events, reset_audit_events
from .authz import Actor, AuthorizationError, authorize, require_authorized
from .gateway import SecureLLMGateway, get_gateway, set_gateway
from .phi import contains_phi, minimize_payload, minimize_text
from .schemas import (
    AI_DIFFERENTIAL_LABEL,
    AI_MANAGEMENT_LABEL,
    NoteState,
    SOAPValidationError,
    approve_note_record,
    create_draft_note_record,
    finalize_note_record,
    has_ai_differential_label,
    has_ai_management_label,
    validate_soap_output,
)

__all__ = [
    "Actor",
    "AuthorizationError",
    "AI_DIFFERENTIAL_LABEL",
    "AI_MANAGEMENT_LABEL",
    "NoteState",
    "SOAPValidationError",
    "SecureLLMGateway",
    "approve_note_record",
    "audit_event",
    "authorize",
    "contains_phi",
    "create_draft_note_record",
    "finalize_note_record",
    "get_audit_events",
    "get_gateway",
    "has_ai_differential_label",
    "has_ai_management_label",
    "minimize_payload",
    "minimize_text",
    "require_authorized",
    "reset_audit_events",
    "set_gateway",
    "validate_soap_output",
]
