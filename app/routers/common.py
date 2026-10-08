from __future__ import annotations

from fastapi import HTTPException, status


def service_http_error(error: Exception, *, default_status: int = status.HTTP_400_BAD_REQUEST) -> HTTPException:
    code = str(getattr(error, "code", "REQUEST_REJECTED"))
    status_code = default_status
    error_name = type(error).__name__.upper()
    if code in {"FORBIDDEN", "PATIENT_MISMATCH", "WORKFLOW_MISMATCH", "APPOINTMENT_MISMATCH"} or any(
        marker in error_name for marker in ("ACCESS", "AUTHORIZATION")
    ):
        status_code = status.HTTP_403_FORBIDDEN
    elif code.endswith("_NOT_FOUND") or code in {
        "CHALLENGE_NOT_FOUND",
        "CONSENT_NOT_FOUND",
        "ENCOUNTER_NOT_FOUND",
        "APPOINTMENT_REQUIRED",
    }:
        status_code = status.HTTP_404_NOT_FOUND
    elif code in {
        "IDEMPOTENCY_CONFLICT",
        "VERSION_CONFLICT",
        "INVALID_NOTE_STATE",
        "INTAKE_CONFLICT",
        "BOOKING_ALREADY_FORWARDED",
        "SLOT_CONFLICT",
        "APPOINTMENT_CONFLICT",
        "VERIFICATION_LOCKED",
        "RESEND_COOLDOWN",
        "RESEND_LIMIT",
        "OTP_ALREADY_USED",
        "ACTION_IN_PROGRESS",
        "MEDICINE_REVIEW_REQUIRED",
    }:
        status_code = status.HTTP_409_CONFLICT
    elif code in {
        "REQUIRES_EXTERNAL_SERVICE",
        "FEATURE_DISABLED",
        "TELNYX_NOT_CONFIGURED",
        "TELNYX_API_ERROR",
        "TELNYX_NETWORK_ERROR",
        "TELNYX_DIAL_FAILED",
        "LLM_NOT_CONFIGURED",
        "LLM_ERROR",
        "STT_FAILED",
        "CODING_UNAVAILABLE",
        "SOAP_FAILED",
        "TRANSLATION_FAILED",
    }:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=status_code, detail={"code": code, "message": str(error)})
