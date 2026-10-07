from __future__ import annotations

import hashlib
import re
import uuid


_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")


def new_id(prefix: str) -> str:
    normalized = str(prefix or "").strip().upper()
    if not _PREFIX_RE.fullmatch(normalized):
        raise ValueError("Identifier prefix must contain 2-8 uppercase letters or digits")
    return f"{normalized}-{uuid.uuid4().hex[:16].upper()}"


def legacy_patient_id(legacy_ref: str) -> str:
    """Create a stable opaque migration ID without using patient demographics."""
    normalized = str(legacy_ref or "").strip().lower()
    if not normalized:
        raise ValueError("Legacy patient reference is required")
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16].upper()
    return f"PT-{digest}"
