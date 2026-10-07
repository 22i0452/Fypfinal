"""Interactive receptionist Demo Call scenarios (live chat + voice turns)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.services.appointment_service import AppointmentError
from app.services.booking_flow import OPENING as BOOKING_OPENING
from app.services.booking_flow import SLOT_BY_KEY, BookingFlow
from app.services.receptionist_integration_service import (
    ReceptionistBooking,
    ReceptionistIntake,
    ReceptionistIntegrationError,
    ReceptionistIntegrationService,
)


logger = logging.getLogger(__name__)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
# Clinic-local "today" lets the extractor resolve "6th" or "kal" to a date.
_CLINIC_TIMEZONE = ZoneInfo("Asia/Karachi")
# The patient record cannot be created without these details.
_INTAKE_KEYS = ("name", "age", "phone", "first_visit", "history", "complaint")


class DemoCallError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_ARABIC_CHAR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_SCRIPT_RUN = re.compile(
    r"(?:[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF"
    r"\s\u060C\u061B\u061F،؟.!،:؛\-—0-9]*)"
    r"|(?:[A-Za-z][A-Za-z0-9\s,'\-\.?!:;/%]*)"
)

_LANG_RULES = """\
LANGUAGE RULES (mandatory — follow exactly):
- Understand caller input in Urdu script, Roman Urdu, or English.
- EVERY assistant reply MUST be exactly TWO lines, never mixed on one line:
  Line 1: complete Urdu in Arabic/Nastaliq script ONLY (no Latin letters, NOT Roman Urdu)
  Line 2: complete English translation ONLY (no Urdu script)
- Keep proper names as spoken/typed (e.g. شہزیب علی خان / Shahzaib Ali Khan). Do not invent alternate spellings.
- If the caller message looks garbled, truncated, or nonsensical, do NOT guess. Ask them to repeat clearly.
- Never invent an appointment confirmation from unclear time/name/phone. Only confirm after clear details.
- Phone numbers: keep digits. Times: use clear numbers (e.g. تین بجے / 3 PM).
- One short question only per turn. Keep each language line brief.
- No parentheses, stage directions, or meta notes.
"""

SCENARIOS: dict[str, dict[str, Any]] = {
    "in-new-booking": {
        "direction": "inbound",
        "title": "Appointment Booking — New Patient",
        "opening": "\n".join(BOOKING_OPENING),
        # Server-owned slot filling (booking_flow.py): the LLM only extracts
        # the caller's answer; collected details live in the call state.
        "flow": "booking",
    },
    "in-existing-booking": {
        "direction": "inbound",
        "title": "Appointment Booking — Existing Patient",
        "opening": (
            "السلام علیکم، میڈفلو کلینک۔ میں ثمرہ بول رہی ہوں۔ اپنا نام اور فون نمبر بتائیں۔\n"
            "Assalam o alaikum, Medflow clinic. This is Samra. Please tell me your name and phone number."
        ),
        "system": f"""\
You are Samra. INBOUND: existing/returning patient booking follow-up or new visit.
Confirm identity (name/phone), then follow-up vs new visit, doctor preference, and time. Confirm booking at the end.
{_LANG_RULES}""",
    },
    "in-cancel": {
        "direction": "inbound",
        "title": "Appointment Cancellation",
        "opening": (
            "السلام علیکم، میڈفلو کلینک۔ میں ثمرہ ہوں۔ میں آپ کی کیسے مدد کر سکتی ہوں؟\n"
            "Assalam o alaikum, Medflow clinic. I am Samra. How can I help you today?"
        ),
        "system": f"""\
You are Samra. INBOUND: patient wants to cancel an existing appointment.
Get name and phone, confirm which appointment, cancel it, and offer to reschedule.
{_LANG_RULES}""",
    },
    "out-reminder-24h": {
        "direction": "outbound",
        "title": "Appointment Reminder — 24 Hours",
        "opening": (
            "السلام علیکم، میں ثمرہ ہوں میڈفلو کلینک سے۔ یہ آپ کی کل کی اپائنٹمنٹ کی یاد دہانی ہے۔ کیا آپ سن رہے ہیں؟\n"
            "Assalam o alaikum, I am Samra from Medflow clinic. This is a reminder for your appointment tomorrow. Can you hear me?"
        ),
        "system": f"""\
You are Samra. OUTBOUND 24-hour appointment reminder.
You may use demo details: tomorrow 10:00 AM, Dr. Ayesha Khan, clinic on Main Boulevard.
Confirm whether the patient will attend or wants to reschedule.
{_LANG_RULES}""",
    },
    "out-followup": {
        "direction": "outbound",
        "title": "Post-Visit Clinical Follow-Up",
        "opening": (
            "السلام علیکم، میڈفلو کلینک سے ثمرہ بات کر رہی ہوں۔ ڈاکٹر کے پلان کے مطابق یہ فالو اپ کال ہے۔ کیا آپ بات کر سکتے ہیں؟\n"
            "Assalam o alaikum, this is Samra from Medflow clinic. This is a follow-up call as per the doctor's plan. Can you talk?"
        ),
        "system": f"""\
You are Samra. OUTBOUND clinical follow-up.
Ask if symptoms are better / same / worse.
If worse: flag clinical team and offer rebooking.
If better: log positive outcome and thank them.
{_LANG_RULES}""",
    },
    "out-noshow": {
        "direction": "outbound",
        "title": "No-Show Recovery",
        "opening": (
            "السلام علیکم، میڈفلو کلینک۔ میں ثمرہ ہوں۔ آج کی آپ کی اپائنٹمنٹ مس ہو گئی تھی۔ کیا اب بات ہو سکتی ہے؟\n"
            "Assalam o alaikum, Medflow clinic. I am Samra. You missed today's appointment. Can we talk now?"
        ),
        "system": f"""\
You are Samra. OUTBOUND no-show recovery.
Confirm the missed appointment, offer next slots (e.g. tomorrow 3 PM or day-after 11 AM), capture preference, and note the new booking.
{_LANG_RULES}""",
    },
}


class DemoCallService:
    def __init__(self, *, groq_api_key: str, groq_llm_model: str, openrouter_api_key: str) -> None:
        self.groq_api_key = (groq_api_key or "").strip()
        self.groq_llm_model = groq_llm_model or "qwen/qwen3.8-27b"
        self.openrouter_api_key = (openrouter_api_key or "").strip()

    def list_scenarios(self) -> dict[str, list[dict[str, str]]]:
        inbound: list[dict[str, str]] = []
        outbound: list[dict[str, str]] = []
        for scenario_id, meta in SCENARIOS.items():
            item = {
                "id": scenario_id,
                "title": str(meta["title"]),
                "direction": str(meta["direction"]),
                "opening": str(meta["opening"]),
            }
            if meta["direction"] == "outbound":
                outbound.append(item)
            else:
                inbound.append(item)
        return {"inbound": inbound, "outbound": outbound}

    def start(self, scenario_id: str) -> dict[str, Any]:
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            raise DemoCallError("UNKNOWN_SCENARIO", "Unknown demo scenario")
        opening = self.format_bilingual(str(scenario["opening"]))
        first = (
            BookingFlow().state_message()
            if scenario.get("flow") == "booking"
            else {"role": "system", "content": str(scenario["system"])}
        )
        return {
            "scenario_id": scenario_id,
            "title": scenario["title"],
            "direction": scenario["direction"],
            "reply": opening,
            "speech_text": self.urdu_for_speech(opening),
            "history": [first, {"role": "assistant", "content": opening}],
        }

    def turn(self, *, scenario_id: str, history: list[dict[str, str]], user_message: str) -> dict[str, Any]:
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            raise DemoCallError("UNKNOWN_SCENARIO", "Unknown demo scenario")
        clean = " ".join((user_message or "").split())
        if not clean:
            raise DemoCallError("EMPTY_MESSAGE", "Please say or type a reply")
        if scenario.get("flow") == "booking":
            return self._booking_turn(scenario_id, history, clean)

        messages: list[dict[str, str]] = []
        has_system = False
        for item in history or []:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role not in {"system", "user", "assistant"} or not content:
                continue
            if role == "system":
                has_system = True
            messages.append({"role": role, "content": content})
        if not has_system:
            messages.insert(0, {"role": "system", "content": str(scenario["system"])})
        lang_hint = (
            "Caller message language hint: English/Latin."
            if re.search(r"[A-Za-z]", clean) and not _ARABIC_CHAR.search(clean)
            else "Caller message language hint: Urdu."
            if _ARABIC_CHAR.search(clean)
            else "Caller message language hint: mixed/Roman Urdu."
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{clean}\n\n[{lang_hint} Reply with exactly two lines: "
                    "Urdu script first, English second. Never mix scripts on one line. "
                    "Keep any Latin-script names exactly as written.]"
                ),
            }
        )
        # Keep prompt short for latency
        trimmed = [messages[0], *messages[-11:]] if messages else messages
        reply = self.format_bilingual(self._chat(trimmed))
        # Store clean user text in history (without internal hint)
        for item in reversed(trimmed):
            if item.get("role") == "user":
                item["content"] = clean
                break
        next_history = [*trimmed, {"role": "assistant", "content": reply}]
        return {
            "scenario_id": scenario_id,
            "reply": reply,
            "speech_text": self.urdu_for_speech(reply),
            "history": next_history,
        }

    def _booking_turn(self, scenario_id: str, history: list[dict[str, str]], clean: str) -> dict[str, Any]:
        flow = BookingFlow.from_history(history)
        today = datetime.now(_CLINIC_TIMEZONE).date()
        urdu, english = flow.handle(clean, self._extract(flow, clean), today=today)
        reply = f"{urdu}\n{english}"
        # The transcript is display-only here (the LLM never sees it), so keep
        # it bounded; the call state carries every collected detail.
        transcript = [
            {"role": str(item.get("role")), "content": str(item.get("content") or "")}
            for item in history or []
            if item.get("role") in {"user", "assistant"}
        ]
        transcript += [{"role": "user", "content": clean}, {"role": "assistant", "content": reply}]
        return {
            "scenario_id": scenario_id,
            "reply": reply,
            "speech_text": self.urdu_for_speech(reply),
            "history": [flow.state_message(), *transcript[-20:]],
            "booking_complete": flow.done,
        }

    def finish(
        self,
        *,
        scenario_id: str,
        history: list[dict[str, str]],
        integration: ReceptionistIntegrationService,
    ) -> dict[str, Any]:
        """Save what the demo booking call collected as a real patient intake and booking.

        Uses the same intake/booking path as the receptionist form, keyed on the
        call's token, so ending a call twice returns the same saved records.
        """
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            raise DemoCallError("UNKNOWN_SCENARIO", "Unknown demo scenario")
        if scenario.get("flow") != "booking":
            return {"supported": False, "saved": False}
        flow = BookingFlow.from_history(history)
        result: dict[str, Any] = {
            "supported": True,
            "saved": False,
            "confirmed": flow.done,
            "details": flow.details(),
            "missing": [SLOT_BY_KEY[key].label_en for key in _INTAKE_KEYS if key not in flow.values],
        }
        if result["missing"]:
            return result
        values = flow.values
        try:
            created = integration.create_intake(
                ReceptionistIntake(
                    name=values["name"]["en"],
                    age_text=values["age"]["en"],
                    phone_number=values["phone"]["en"],
                    first_visit=values["first_visit"]["en"],
                    past_medical_history=values["history"]["en"],
                    current_complaint=values["complaint"]["en"],
                    intake_token=flow.token,
                    revision=1,
                    confirmed_revision=1,
                )
            )
        except ReceptionistIntegrationError as exc:
            result["error"] = str(exc)
            return result
        result.update(
            saved=True,
            patient_id=created["patient_id"],
            workflow_id=created["workflow_id"],
            workflow_state=created.get("workflow_state", ""),
            intake_token=flow.token,
            revision=1,
            booking=self._book_from_call(flow, created, integration),
        )
        return result

    @staticmethod
    def _book_from_call(
        flow: BookingFlow,
        created: dict[str, Any],
        integration: ReceptionistIntegrationService,
    ) -> dict[str, Any]:
        values = flow.values
        if "department" not in values or "time" not in values:
            return {"status": "NOT_REQUESTED", "message": "The call ended before a department and time were agreed."}
        requested = values["time"]["en"]
        if not values["time"].get("iso"):
            return {"status": "TIME_UNCLEAR", "requested_time": requested, "message": "The requested time could not be resolved to a date."}
        try:
            config = integration.configuration()
            department = next(
                (item for item in config["departments"] if item["name"].casefold() == values["department"]["en"].casefold()),
                None,
            )
            if department is None:
                return {
                    "status": "NO_DOCTOR",
                    "requested_time": requested,
                    "message": f"No bookable doctor is available in {values['department']['en']}.",
                }
            doctors = [item for item in config["practitioners"] if item["department_id"] == department["department_id"]]
            wanted = values.get("doctor", {}).get("en", "")
            # Match a named doctor by any distinctive word ("Ayesha" -> "Dr. Ayesha Khan").
            words = {word for word in re.findall(r"[a-z]{3,}", wanted.casefold()) if word not in {"any", "available", "doctor"}}
            practitioner = next(
                (item for item in doctors if words & set(re.findall(r"[a-z]{3,}", item["display_name"].casefold()))),
                None,
            )
            new_patient = values["first_visit"]["en"] == "Yes"
            visit_type = next(
                (
                    item
                    for item in config["visit_types"]
                    if ("new" if new_patient else "follow") in str(item["name"]).casefold()
                ),
                config["visit_types"][0],
            )
            booking = integration.book(
                ReceptionistBooking(
                    patient_id=created["patient_id"],
                    workflow_id=created["workflow_id"],
                    department_id=department["department_id"],
                    practitioner_id=practitioner["practitioner_id"] if practitioner else "",
                    visit_type_id=visit_type["visit_type_id"],
                    start_at=datetime.fromisoformat(values["time"]["iso"]),
                    idempotency_key=f"demo-{flow.token}",
                    intake_token=flow.token,
                    revision=1,
                )
            )
        except (ReceptionistIntegrationError, AppointmentError) as exc:
            return {"status": "ERROR", "requested_time": requested, "message": str(exc)}
        return {
            **booking,
            "requested_time": requested,
            "department_id": department["department_id"],
            "visit_type_id": visit_type["visit_type_id"],
        }

    def _extract(self, flow: BookingFlow, caller_text: str) -> dict[str, Any]:
        messages = flow.extraction_messages(caller_text, today=datetime.now(_CLINIC_TIMEZONE).date())
        for url, api_key, model in self._providers():
            try:
                raw = self._completion(url, api_key, model, messages, max_tokens=400, raw=True)
                match = re.search(r"\{.*\}", _THINK_BLOCK.sub("", raw), re.S)
                if match:
                    return json.loads(match.group(0))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Booking extraction via %s failed: %s", model, exc)
        return flow.fallback_extraction(caller_text)

    def _providers(self) -> list[tuple[str, str, str]]:
        providers = []
        if self.groq_api_key:
            providers.append(("https://api.groq.com/openai/v1/chat/completions", self.groq_api_key, self.groq_llm_model))
        if self.openrouter_api_key:
            providers.append(("https://openrouter.ai/api/v1/chat/completions", self.openrouter_api_key, "openai/gpt-4o-mini"))
        return providers

    @staticmethod
    def format_bilingual(text: str) -> str:
        """Force Urdu (line 1) and English (line 2), never interleaved."""
        raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not raw:
            return raw

        lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
        if len(lines) >= 2:
            urdu_candidate = lines[0]
            eng_candidate = " ".join(lines[1:])
            urdu_has_arabic = bool(_ARABIC_CHAR.search(urdu_candidate))
            eng_has_latin = bool(re.search(r"[A-Za-z]", eng_candidate))
            urdu_has_latin_words = bool(re.search(r"[A-Za-z]{3,}", urdu_candidate))
            eng_has_arabic = bool(_ARABIC_CHAR.search(eng_candidate))
            if urdu_has_arabic and eng_has_latin and not urdu_has_latin_words and not eng_has_arabic:
                return f"{urdu_candidate}\n{eng_candidate}"

        urdu_parts: list[str] = []
        eng_parts: list[str] = []
        for match in _SCRIPT_RUN.finditer(raw.replace("\n", " ")):
            chunk = match.group(0).strip()
            if not chunk:
                continue
            if _ARABIC_CHAR.search(chunk):
                urdu_parts.append(chunk)
            else:
                eng_parts.append(chunk)

        urdu = re.sub(r"\s+", " ", " ".join(urdu_parts)).strip()
        eng = re.sub(r"\s+", " ", " ".join(eng_parts)).strip()
        if urdu and eng:
            return f"{urdu}\n{eng}"
        if urdu:
            return urdu
        if eng:
            return eng
        return re.sub(r"[ \t]+", " ", raw).strip()

    @staticmethod
    def urdu_for_speech(text: str) -> str:
        formatted = DemoCallService.format_bilingual(text)
        urdu = formatted.split("\n", 1)[0].strip()
        if _ARABIC_CHAR.search(urdu):
            return urdu
        return formatted.replace("\n", " ").strip()

    def _chat(self, messages: list[dict[str, str]]) -> str:
        if self.groq_api_key:
            try:
                return self._completion(
                    "https://api.groq.com/openai/v1/chat/completions",
                    self.groq_api_key,
                    self.groq_llm_model,
                    messages,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Demo Groq chat failed: %s", exc)
        if self.openrouter_api_key:
            return self._completion(
                "https://openrouter.ai/api/v1/chat/completions",
                self.openrouter_api_key,
                "openai/gpt-4o-mini",
                messages,
            )
        raise DemoCallError("LLM_NOT_CONFIGURED", "No LLM API key configured for demo calls")

    @staticmethod
    def _completion(
        url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 160,
        raw: bool = False,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0 if raw else 0.2,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://medflow.local",
                "X-Title": "MedFlowAI Demo Call",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            raise DemoCallError("LLM_ERROR", f"Demo LLM failed ({exc.code}): {detail}") from exc
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if raw:
            return content
        content = re.sub(r"\([^)]*\)", "", content)
        if not content.strip():
            raise DemoCallError("EMPTY_REPLY", "Demo agent returned an empty reply")
        return content.strip()[:600]
