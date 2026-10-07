from __future__ import annotations

from typing import Any

from medflow.domain.ids import new_id
from medflow.domain.models import AuditEvent
from medflow.repositories.protocols import AuditRepository
from security_guardrails import audit_event
from security_guardrails.audit import sanitize_metadata


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

    def record(
        self,
        event_type: str,
        *,
        actor_ref: str,
        action: str,
        patient_ref: str = "",
        resource_ref: str = "",
        result: str = "allow",
        request_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        safe_metadata = sanitize_metadata(metadata)
        in_memory = audit_event(
            event_type,
            actor_ref=actor_ref,
            action=action,
            patient_ref=patient_ref,
            result=result,
            request_id=request_id,
            metadata=safe_metadata,
        )
        event = AuditEvent(
            audit_event_id=new_id("AUD"),
            event_type=event_type,
            actor_ref=actor_ref,
            action=action,
            patient_ref=patient_ref,
            resource_ref=resource_ref,
            result=result,
            request_id=in_memory["request_id"],
            timestamp=in_memory["timestamp"],
            metadata=safe_metadata,
        )
        return self.repository.append(event)
