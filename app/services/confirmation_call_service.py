"""Outbound Telnyx appointment confirmation calls (Urdu IVR)."""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from medflow.domain.enums import AppointmentStatus
from medflow.domain.ids import new_id
from medflow.intake_validation import normalize_phone
from security_guardrails import Actor

from app.services.appointment_service import AppointmentError, AppointmentService


logger = logging.getLogger(__name__)


class ConfirmationCallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ConfirmationCallSession:
    call_control_id: str
    appointment_id: str
    patient_id: str
    patient_name: str
    to_number: str
    doctor_name: str
    start_at: str
    status: str = "initiated"
    digits: str = ""
    outcome: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


def to_e164_pakistan(phone: str) -> str:
    """Normalize clinic phones (03… / 923…) to E.164 +92…."""
    digits = re.sub(r"\D", "", normalize_phone(phone) or phone or "")
    if not digits:
        raise ConfirmationCallError("INVALID_PHONE", "A valid patient phone number is required")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("92") and len(digits) == 12:
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+92{digits[1:]}"
    if len(digits) == 10 and digits.startswith("3"):
        return f"+92{digits}"
    if digits.startswith("1") and len(digits) == 11:
        # US/Canada numbers for local Telnyx testing
        return f"+{digits}"
    if phone.strip().startswith("+") and 10 <= len(digits) <= 15:
        return f"+{digits}"
    raise ConfirmationCallError(
        "INVALID_PHONE",
        "Phone must be a Pakistani mobile (03XXXXXXXXX) or E.164 (+92…)",
    )


class ConfirmationCallService:
    """Place Telnyx Call Control outbound confirmation calls and handle webhooks."""

    def __init__(
        self,
        *,
        api_key: str,
        from_number: str,
        connection_id: str,
        webhook_base_url: str,
        appointments: AppointmentService,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.from_number = (from_number or "").strip()
        self.connection_id = (connection_id or "").strip()
        self.webhook_base_url = (webhook_base_url or "").rstrip("/")
        self.appointments = appointments
        self._sessions: dict[str, ConfirmationCallSession] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.from_number and self.connection_id and self.webhook_base_url)

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "from_number": self.from_number or None,
            "connection_id": bool(self.connection_id),
            "webhook_base_url": self.webhook_base_url or None,
            "mode": "telnyx_call_control_ivr",
            "language": "ur-roman",
        }

    def start_call(
        self,
        *,
        to_number: str,
        appointment_id: str,
        patient_id: str,
        patient_name: str,
        doctor_name: str,
        start_at: str,
    ) -> dict[str, Any]:
        if not self.configured:
            raise ConfirmationCallError(
                "TELNYX_NOT_CONFIGURED",
                "Telnyx is not configured. Set TELNYX_API_KEY, TELNYX_NUMBER, "
                "TELNYX_CONNECTION_ID, and TELNYX_WEBHOOK_BASE_URL.",
            )

        e164 = to_e164_pakistan(to_number)
        webhook_url = f"{self.webhook_base_url}/api/webhooks/telnyx"
        client_state = self._encode_state(
            {
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "doctor_name": doctor_name,
                "start_at": start_at,
            }
        )
        payload = {
            "connection_id": self.connection_id,
            "to": e164,
            "from": self.from_number,
            "webhook_url": webhook_url,
            "webhook_url_method": "POST",
            "client_state": client_state,
            "timeout_secs": 45,
            "answering_machine_detection": "disabled",
        }
        response = self._telnyx("POST", "/calls", payload)
        data = response.get("data") or {}
        call_control_id = str(data.get("call_control_id") or "")
        if not call_control_id:
            raise ConfirmationCallError("TELNYX_DIAL_FAILED", "Telnyx did not return a call_control_id")

        session = ConfirmationCallSession(
            call_control_id=call_control_id,
            appointment_id=appointment_id,
            patient_id=patient_id,
            patient_name=patient_name,
            to_number=e164,
            doctor_name=doctor_name,
            start_at=start_at,
            status="initiated",
        )
        with self._lock:
            self._sessions[call_control_id] = session

        return {
            "ok": True,
            "call_control_id": call_control_id,
            "call_session_id": data.get("call_session_id"),
            "to": e164,
            "from": self.from_number,
            "appointment_id": appointment_id,
            "status": "initiated",
            "message": "Outbound Urdu confirmation call started.",
        }

    def get_session(self, call_control_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(call_control_id)
            return None if session is None else session.__dict__.copy()

    def handle_webhook(self, body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        event_type = str(
            data.get("event_type")
            or body.get("event_type")
            or (data.get("payload") or {}).get("event_type")
            or ""
        )
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
        call_control_id = str(payload.get("call_control_id") or "")
        client_state = self._decode_state(payload.get("client_state"))

        if call_control_id:
            with self._lock:
                session = self._sessions.get(call_control_id)
                if session is None and client_state:
                    session = ConfirmationCallSession(
                        call_control_id=call_control_id,
                        appointment_id=str(client_state.get("appointment_id") or ""),
                        patient_id=str(client_state.get("patient_id") or ""),
                        patient_name=str(client_state.get("patient_name") or ""),
                        to_number=str(payload.get("to") or ""),
                        doctor_name=str(client_state.get("doctor_name") or ""),
                        start_at=str(client_state.get("start_at") or ""),
                    )
                    self._sessions[call_control_id] = session
                if session is not None:
                    session.status = event_type or session.status

        if event_type == "call.answered":
            self._prompt_confirmation(call_control_id, client_state)
            return {"ok": True, "action": "gather_using_speak"}

        if event_type in {"call.gather.ended", "call.gather.ended.partial"}:
            digits = str(payload.get("digits") or payload.get("digit") or "").strip()
            outcome = self._apply_digits(call_control_id, digits, client_state)
            self._speak_outcome(call_control_id, outcome)
            return {"ok": True, "action": "handled_digits", "digits": digits, "outcome": outcome}

        if event_type == "call.speak.ended":
            with self._lock:
                session = self._sessions.get(call_control_id)
                should_hangup = bool(session and session.outcome)
            if should_hangup:
                self._hangup(call_control_id)
                return {"ok": True, "action": "hangup_after_speak"}
            return {"ok": True, "action": "speak_ended"}

        if event_type == "call.hangup":
            return {"ok": True, "action": "hangup"}

        return {"ok": True, "action": "ignored", "event_type": event_type}

    def _prompt_confirmation(self, call_control_id: str, client_state: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(call_control_id)
        doctor = (session.doctor_name if session else "") or client_state.get("doctor_name") or "doctor"
        start_at = (session.start_at if session else "") or client_state.get("start_at") or ""
        when = self._format_when_urdu(start_at)
        patient = (session.patient_name if session else "") or client_state.get("patient_name") or ""
        name_bit = f" {patient} sahib," if patient else ""

        prompt = (
            f"Assalam o alaikum{name_bit}. Main Medflow clinic se baat kar rahi hoon. "
            f"Aap ka appointment {doctor} ke saath {when} hai. "
            "Confirm karne ke liye ek dabain. Cancel karne ke liye do dabain."
        )
        self._telnyx(
            "POST",
            f"/calls/{call_control_id}/actions/gather_using_speak",
            {
                "payload": prompt,
                "payload_type": "text",
                "service_level": "premium",
                "voice": "female",
                "language": "hi-IN",
                "valid_digits": "12",
                "maximum_digits": 1,
                "minimum_digits": 1,
                "timeout_millis": 12000,
                "inter_digit_timeout_millis": 4000,
                "client_state": self._encode_state(client_state or {}),
            },
        )

    def _apply_digits(
        self,
        call_control_id: str,
        digits: str,
        client_state: dict[str, Any],
    ) -> str:
        with self._lock:
            session = self._sessions.get(call_control_id)
            appointment_id = (session.appointment_id if session else "") or str(
                client_state.get("appointment_id") or ""
            )
            patient_id = (session.patient_id if session else "") or str(client_state.get("patient_id") or "")
            if session is not None:
                session.digits = digits

        if not appointment_id:
            return "missing_appointment"

        actor = Actor(
            actor_id="telnyx-confirmation-agent",
            role="receptionist",
            authorized_patient_ids={patient_id, "*"} if patient_id else {"*"},
            current_patient_id=patient_id or "",
        )
        try:
            if digits == "1":
                current = self.appointments.get(appointment_id, actor=actor)
                if current.status == AppointmentStatus.REQUESTED:
                    self.appointments.confirm_requested(appointment_id, actor=actor)
                outcome = "confirmed"
            elif digits == "2":
                self.appointments.cancel(
                    appointment_id,
                    reason_code="PATIENT_DECLINED_CALL",
                    idempotency_key=new_id("CXL"),
                    actor=actor,
                )
                outcome = "cancelled"
            else:
                outcome = "no_input"
        except AppointmentError as exc:
            logger.warning("Confirmation call appointment update failed: %s", exc)
            outcome = f"error:{exc.code}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Confirmation call appointment update failed")
            outcome = f"error:{exc}"

        with self._lock:
            session = self._sessions.get(call_control_id)
            if session is not None:
                session.outcome = outcome
                session.status = outcome
        return outcome

    def _speak_outcome(self, call_control_id: str, outcome: str) -> None:
        if outcome == "confirmed":
            message = "Shukriya. Aap ki appointment confirm ho gayi hai. Allah hafiz."
        elif outcome == "cancelled":
            message = "Theek hai. Aap ki appointment cancel kar di gayi hai. Allah hafiz."
        else:
            message = "Maazrat, jawab samajh nahi aaya. Dobara clinic se rabta karein. Allah hafiz."
        try:
            self._telnyx(
                "POST",
                f"/calls/{call_control_id}/actions/speak",
                {
                    "payload": message,
                    "payload_type": "text",
                    "service_level": "premium",
                    "voice": "female",
                    "language": "hi-IN",
                },
            )
        except ConfirmationCallError:
            logger.exception("Failed to speak confirmation outcome")
            self._hangup(call_control_id)

    def _hangup(self, call_control_id: str) -> None:
        try:
            self._telnyx("POST", f"/calls/{call_control_id}/actions/hangup", {})
        except ConfirmationCallError:
            logger.exception("Failed to hang up confirmation call")

    def _telnyx(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"https://api.telnyx.com/v2{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.error("Telnyx API %s %s failed: %s", method, path, detail)
            raise ConfirmationCallError(
                "TELNYX_API_ERROR",
                f"Telnyx request failed ({exc.code}): {detail[:300]}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ConfirmationCallError("TELNYX_NETWORK_ERROR", f"Telnyx network error: {exc.reason}") from exc

    @staticmethod
    def _encode_state(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _decode_state(value: Any) -> dict[str, Any]:
        if not value:
            return {}
        try:
            raw = base64.b64decode(str(value).encode("ascii"))
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _format_when_urdu(start_at: str) -> str:
        if not start_at:
            return "muqarrara waqt"
        try:
            text = start_at.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Karachi"))
            local = dt.astimezone(ZoneInfo("Asia/Karachi"))
            return local.strftime("%d %B %Y, %I:%M %p").lstrip("0")
        except Exception:  # noqa: BLE001
            return start_at
