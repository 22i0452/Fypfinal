from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any


_AUDIT_EVENTS: list[dict[str, Any]] = []
_BLOCKED_VALUE = "[REDACTED]"
_SENSITIVE_KEYS = {
    "name",
    "patient_name",
    "phone",
    "phone_number",
    "cnic",
    "address",
    "email",
    "transcript",
    "soap",
    "audio",
    "api_key",
    "token",
    "prompt",
    "messages",
    "content",
}
_PHI_PATTERNS = (
    re.compile(r"\b03\d{2}[- ]?\d{7}\b"),
    re.compile(r"\b\d{5}[- ]?\d{7}[- ]?\d\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b(?:sk|gsk|xai|hf|ghp)_[A-Za-z0-9_\-]{12,}\b"),
)


def _safe_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(token in lowered for token in _SENSITIVE_KEYS):
        return _BLOCKED_VALUE
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _PHI_PATTERNS):
            return _BLOCKED_VALUE
        if len(value) > 160:
            return value[:160] + "..."
    if isinstance(value, dict):
        return {str(k): _safe_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value[:20]]
    return value


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): _safe_value(str(key), value) for key, value in (metadata or {}).items()}


def audit_event(
    event_type: str,
    *,
    actor_ref: str = "system",
    action: str = "",
    patient_ref: str = "",
    result: str = "allow",
    request_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "event_type": event_type,
        "actor_ref": actor_ref or "system",
        "action": action or event_type,
        "patient_ref": patient_ref or "",
        "result": result,
        "request_id": request_id or f"req_{int(time.time() * 1000)}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "metadata": sanitize_metadata(metadata),
    }
    _AUDIT_EVENTS.append(event)
    return event


def get_audit_events() -> list[dict[str, Any]]:
    return [dict(event) for event in _AUDIT_EVENTS]


def reset_audit_events() -> None:
    _AUDIT_EVENTS.clear()


def write_audit_events(path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        for event in _AUDIT_EVENTS:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
