from __future__ import annotations

import copy
import re
from typing import Any


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?92[- ]?)?0?3\d{2}[- ]?\d{7}(?!\d)")
_CNIC_RE = re.compile(r"\b\d{5}[- ]?\d{7}[- ]?\d\b")
_MRN_RE = re.compile(r"\b(?:MRN|medical record number|record number)[:# ]+[A-Za-z0-9\-]{3,}\b", re.I)
_ADDRESS_RE = re.compile(
    r"\b(?:house|flat|street|st\.|road|rd\.|sector|block|address)[:# ]+[A-Za-z0-9,\- /]{5,80}",
    re.I,
)
_APPOINTMENT_RE = re.compile(
    r"\b(?:booking|appointment|slot|room|clinic room)[:# ]+[A-Za-z0-9,\-: /]{3,80}",
    re.I,
)


_KEY_PLACEHOLDERS = {
    "name": "[PATIENT_NAME]",
    "patient_name": "[PATIENT_NAME]",
    "نام": "[PATIENT_NAME]",
    "phone": "[PHONE]",
    "phone_number": "[PHONE]",
    "فون_نمبر": "[PHONE]",
    "cnic": "[CNIC]",
    "national_id": "[CNIC]",
    "email": "[EMAIL]",
    "address": "[ADDRESS]",
    "mrn": "[MRN]",
    "medical_record_number": "[MRN]",
    "booking_slot_time": "[APPOINTMENT]",
    "booking_time_slot": "[APPOINTMENT]",
    "بکنگ_کا_وقت": "[APPOINTMENT]",
}


def _patient_names(patient_context: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for key in ("name", "patient_name", "نام"):
        value = str((patient_context or {}).get(key, "") or "").strip()
        if value and value.lower() not in {"unknown", "unknown patient"}:
            names.append(value)
    return sorted(set(names), key=len, reverse=True)


def minimize_text(text: str, patient_context: dict[str, Any] | None = None) -> str:
    minimized = str(text or "")
    for name in _patient_names(patient_context):
        minimized = re.sub(re.escape(name), "[PATIENT_NAME]", minimized, flags=re.I)
    minimized = _EMAIL_RE.sub("[EMAIL]", minimized)
    minimized = _PHONE_RE.sub("[PHONE]", minimized)
    minimized = _CNIC_RE.sub("[CNIC]", minimized)
    minimized = _MRN_RE.sub("[MRN]", minimized)
    minimized = _ADDRESS_RE.sub("[ADDRESS]", minimized)
    minimized = _APPOINTMENT_RE.sub("[APPOINTMENT]", minimized)
    return minimized


def minimize_payload(payload: Any, patient_context: dict[str, Any] | None = None) -> Any:
    if isinstance(payload, str):
        return minimize_text(payload, patient_context)
    if isinstance(payload, list):
        return [minimize_payload(item, patient_context) for item in payload]
    if isinstance(payload, tuple):
        return tuple(minimize_payload(item, patient_context) for item in payload)
    if isinstance(payload, dict):
        minimized: dict[str, Any] = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            placeholder = _KEY_PLACEHOLDERS.get(lowered)
            if placeholder is not None:
                minimized[key] = placeholder
            else:
                minimized[key] = minimize_payload(value, patient_context)
        return minimized
    return copy.deepcopy(payload)


def contains_phi(value: Any, patient_context: dict[str, Any] | None = None) -> bool:
    text = str(value)
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text) or _CNIC_RE.search(text):
        return True
    if _MRN_RE.search(text) or _ADDRESS_RE.search(text):
        return True
    lowered = text.lower()
    return any(name.lower() in lowered for name in _patient_names(patient_context))
