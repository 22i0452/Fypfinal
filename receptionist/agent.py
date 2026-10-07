"""
agent.py — Orchestrates the full STT → LLM → TTS pipeline.

Data flow per turn
------------------
  Microphone
      │
      ▼
  AudioRecorder.record()          ← energy-based VAD
      │ float32 numpy array
      ▼
  STTEngine.transcribe()          ← Groq Whisper large-v3
      │ Urdu text string
      ▼
  LLMBrain.get_response()         ← Groq LLaMA 3.3-70B
      │ Urdu reply string
      ▼
  TTSEngine.speak()               ← Edge TTS ur-PK-UzmaNeural
      │
      ▼
  Speaker
"""

from __future__ import annotations

import hashlib
import secrets
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .audio_recorder import AudioRecorder
from .llm_module import LLMBrain, build_clinic_schedule_context
from .receptionist_client import ReceptionistAPIClient, ReceptionistAPIError
from .stt_module import SHORT_INTAKE_FIELDS, STTEngine
from .tts_module import TTSEngine



_BANNER = """
╔══════════════════════════════════════════════════════════╗
║   🏥  اردو طبی رسیپشنسٹ ایجنٹ                          ║
║       Urdu Medical Receptionist Agent                    ║
╠══════════════════════════════════════════════════════════╣
║  STT : Groq Whisper (whisper-large-v3)                  ║
║  LLM : Groq / OpenAI (configured via .env)             ║
║  TTS : Edge TTS    (ur-PK-UzmaNeural, free neural)       ║
╚══════════════════════════════════════════════════════════╝
"""


class ReceptionistAgent:
    """End-to-end Urdu-speaking medical receptionist voice agent."""

    def __init__(
        self,
        calibrate_mic: bool = False,
        callbacks: dict[str, Callable] | None = None,
    ) -> None:
        self._cb = callbacks or {}
        silent = bool(callbacks)

        if not silent:
            print(_BANNER)
            print("⏳  Initialising modules…\n")

        self.recorder = AudioRecorder()
        if calibrate_mic:
            self.recorder.calibrate()
        if not silent:
            print("✅  Audio Recorder  (energy VAD)")

        self.stt = STTEngine()
        if not silent:
            print("✅  STT Engine      (Groq Whisper large-v3)")

        self.tts = TTSEngine()
        if not silent:
            print("✅  TTS Engine      (Edge TTS — ur-PK-UzmaNeural)")

        self.api = ReceptionistAPIClient()
        self._configuration = self.api.configuration()
        if not self._configuration.get("practitioners"):
            raise ReceptionistAPIError(
                "NO_BOOKABLE_DOCTORS",
                "No doctor with an active dashboard account is available for booking",
            )
        self._pending: dict | None = None
        self._forward_requested = threading.Event()
        self._forward_revision: int | None = None
        self._intake_token = secrets.token_urlsafe(32)
        self._turn_in_progress = threading.Event()
        self._schedule_revision = -1
        self._doctor_options = [
            self._patient_facing_doctor_name(item.get("display_name", ""))
            for item in self._configuration.get("practitioners") or []
            if str(item.get("display_name") or "").strip()
        ]
        self._department_options = [
            str(item.get("name") or "").strip()
            for item in self._configuration.get("departments") or []
            if str(item.get("name") or "").strip()
        ]
        self._visit_type_options = [
            str(item.get("name") or "").strip()
            for item in self._configuration.get("visit_types") or []
            if str(item.get("name") or "").strip()
        ]
        self._booking_options = self._load_booking_options()
        self.llm = LLMBrain(
            schedule_context=build_clinic_schedule_context(self._configuration),
            doctor_options=self._doctor_options,
            department_options=self._department_options,
            visit_type_options=self._visit_type_options,
            booking_options=self._booking_options,
            button_review="summary_ready" in self._cb,
        )
        visible_slots = self._visible_schedule_options()
        self._notify(
            "schedule_options",
            {
                "doctor_name": self._doctor_options[0] if self._doctor_options else "",
                "slots": visible_slots,
            },
        )
        if not silent:
            print("✅  Clinic API      (pending scheduling and doctor queue)")
            print("✅  LLM Brain       (Groq LLaMA 3.3-70B)\n")

    def _notify(self, event: str, payload=None) -> None:
        """Fire a UI callback safely from the agent thread."""
        fn = self._cb.get(event)
        if fn:
            try:
                fn(payload) if payload is not None else fn()
            except Exception:
                pass

    @staticmethod
    def _divider() -> None:
        print("\n" + "─" * 60)

    @staticmethod
    def _fmt_ms(seconds: float) -> str:
        return f"{seconds * 1000:.0f} ms"

    def _stt_turn_context(self) -> tuple[str, Callable[[str], bool] | None]:
        """Return a server-controlled STT hint and validator for this turn."""
        if self.llm.is_awaiting_confirmation():
            return "confirmation", self.llm.accepts_spoken_turn

        expected_field = self.llm.expected_field()
        if not expected_field:
            return "", None
        return expected_field, self.llm.accepts_spoken_turn

    def _short_spoken_reply(self) -> bool:
        return self.llm.expected_field() in SHORT_INTAKE_FIELDS

    def request_forward(self, expected_revision: int | None = None) -> bool:
        """Queue the trusted Save & Forward action from the UI thread."""
        if getattr(self, "_turn_in_progress", threading.Event()).is_set():
            return False
        if not self.llm.is_awaiting_confirmation():
            return False
        revision = self.llm.record.revision
        if expected_revision is not None and expected_revision != revision:
            return False
        self._forward_revision = revision
        self._forward_requested.set()
        return True

    def _process_forward_request(self) -> bool:
        self._forward_requested.clear()
        if not self.llm.confirm_current_summary(getattr(self, "_forward_revision", None)):
            return False
        self._notify("summary_ready", False)
        self._notify("status", "processing")
        return self._on_complete()

    def _publish_intake(self) -> None:
        self._notify("patient_data", self.llm.local_intake_data())
        self._notify("summary_ready", {
            "ready": self.llm.is_awaiting_confirmation(),
            "revision": self.llm.record.revision,
        })

    def _refresh_schedule_for_turn(self) -> None:
        if self.llm.expected_field() != "booking_slot_time" or self._schedule_revision == self.llm.record.revision:
            return
        self._booking_options = self._load_booking_options()
        self.llm.set_booking_options(self._booking_options)
        self._schedule_revision = self.llm.record.revision
        visible = list(self.llm._current_booking_options())
        self._notify("schedule_options", {
            "doctor_name": self.llm.local_intake_data().get("ڈاکٹر_کی_ترجیح", ""),
            "slots": visible,
        })

    @staticmethod
    def _patient_facing_doctor_name(value: str) -> str:
        clean = " ".join(str(value or "").replace("_", " ").split())
        return re.sub(r"(?i)\bdr\.(?=\S)", "Dr. ", clean)

    def _doctor_selection_prompt(self) -> str:
        choices = "، ".join(
            f"نمبر {index}: {name}"
            for index, name in enumerate(self._doctor_options, start=1)
        )
        return (
            f"ڈاکٹر کی ترجیح کے لیے دستیاب ڈاکٹر یہ ہیں: {choices}۔ "
            "براہ کرم ڈاکٹر کا نام یا نمبر بتائیں، یا کہیں کہ کوئی خاص ترجیح نہیں۔"
        )

    def _load_booking_options(self) -> list[dict]:
        options: list[dict] = []
        for practitioner in self._configuration.get("practitioners") or []:
            practitioner_id = str(practitioner.get("practitioner_id") or "")
            practitioner_name = self._patient_facing_doctor_name(
                practitioner.get("display_name", "")
            )
            if not practitioner_id:
                continue
            for visit_type in self._configuration.get("visit_types") or []:
                visit_type_id = str(visit_type.get("visit_type_id") or "")
                if not visit_type_id:
                    continue
                try:
                    result = self.api.availability(
                        practitioner_id=practitioner_id,
                        visit_type_id=visit_type_id,
                        days=14,
                        limit=8,
                    )
                except ReceptionistAPIError:
                    continue
                for slot in result.get("slots") or []:
                    options.append(
                        {
                            **slot,
                            "practitioner_id": practitioner_id,
                            "practitioner_name": practitioner_name,
                            "visit_type_id": visit_type_id,
                            "visit_type_name": str(visit_type.get("name") or ""),
                        }
                    )
        options.sort(key=lambda item: str(item.get("start_at") or ""))
        if not options:
            raise ReceptionistAPIError(
                "NO_AVAILABLE_SLOTS",
                "No appointment slots are available in the next 14 days",
            )
        return options

    def _visible_schedule_options(self) -> list[dict]:
        first_visit_type = str(
            (self._configuration.get("visit_types") or [{}])[0].get("visit_type_id")
            or ""
        )
        visible = [
            item
            for item in self._booking_options
            if not first_visit_type or item.get("visit_type_id") == first_visit_type
        ]
        return visible[:8]


    def run(self) -> None:
        """Start the receptionist; runs until conversation completes or Ctrl-C."""
        silent = bool(self._cb)
        if not silent:
            print("=" * 60)
            print("  Ready — press Ctrl-C at any time to quit.")
            print("=" * 60 + "\n")

        try:
            self._notify("status", "greeting")
            if not silent:
                print("🤖  ثمرہ: ", end="", flush=True)
            greeting = self.llm.start_conversation()
            if not silent:
                print(greeting)
            self._notify("agent_msg", greeting)
            self._notify("status", "speaking")
            self.tts.speak(greeting)
            self._notify("status", "idle")

            while True:
                if self._forward_requested.is_set():
                    if self._process_forward_request():
                        break
                    continue

                if self.llm.is_waiting_for_forward():
                    self._notify("status", "review")
                    self._forward_requested.wait(timeout=0.25)
                    continue

                if not silent:
                    self._divider()

                self._notify("status", "listening")
                audio = self.recorder.record(
                    interrupt_event=self._forward_requested,
                    short_response=self._short_spoken_reply(),
                )
                if self._forward_requested.is_set():
                    if self._process_forward_request():
                        break
                    continue

                if audio is None:
                    notice = "آپ کی آواز نہیں سنائی دی، براہ کرم دوبارہ بولیں۔"
                    if not silent:
                        print(f"⚠️  {notice}")
                    self._notify("agent_msg", notice)
                    self._notify("status", "speaking")
                    self.tts.speak(notice)
                    self._notify("status", "idle")
                    continue

                self._notify("status", "processing")
                self._turn_in_progress.set()
                self._notify("summary_ready", False)
                t0 = time.perf_counter()
                expected_field, validator = self._stt_turn_context()
                patient_text = self.stt.transcribe(
                    audio, expected_field=expected_field, validator=validator,
                    language_hint=self.llm.language,
                )
                stt_ms = time.perf_counter() - t0

                if not patient_text:
                    self._turn_in_progress.clear()
                    self._publish_intake()
                    notice = "معاف کیجیے، سمجھ نہیں آیا۔ براہ کرم دوبارہ کہیں۔"
                    if not silent:
                        print(f"⚠️  {notice}")
                    self._notify("agent_msg", notice)
                    self._notify("status", "speaking")
                    self.tts.speak(notice)
                    self._notify("status", "idle")
                    continue

                if not silent:
                    print("Patient response received.")
                    print(f"    ⏱  STT  :  {self._fmt_ms(stt_ms)}")
                self._notify("patient_msg", patient_text)

                t1 = time.perf_counter()
                agent_reply = self.llm.get_response(patient_text)
                try:
                    self._refresh_schedule_for_turn()
                except ReceptionistAPIError:
                    self.llm.set_booking_options([])
                if self.llm.expected_field() == "booking_slot_time":
                    agent_reply = self.llm._field_prompt("بکنگ_کا_وقت")
                self._turn_in_progress.clear()
                self._publish_intake()
                llm_ms = time.perf_counter() - t1

                if not silent:
                    print("Receptionist response prepared.")
                    print(f"    ⏱  LLM  :  {self._fmt_ms(llm_ms)}")
                self._notify("agent_msg", agent_reply)

                self._notify("status", "speaking")
                t2 = time.perf_counter()
                self.tts.speak(agent_reply)
                tts_ms = time.perf_counter() - t2
                self._notify("status", "idle")

                if not silent:
                    print(f"    ⏱  TTS  :  {self._fmt_ms(tts_ms)}")
                    print(f"    ⏱  Round-trip: {self._fmt_ms(stt_ms+llm_ms+tts_ms)}")

                if self._forward_requested.is_set():
                    if self._process_forward_request():
                        break
                    continue

                if self.llm.is_complete():
                    self._notify("status", "processing")
                    if self._on_complete():
                        break

        except KeyboardInterrupt:
            if not silent:
                print("\n\n⚠️  Interrupted by user.")

        if not silent:
            print("\n" + "=" * 60)
            print("  Session ended. Goodbye! / خداحافظ!")
            print("=" * 60)

    @staticmethod
    def _build_booking_retry_message(
        status: str,
        alternatives: list[str],
        slot: str = "",
    ) -> str:
        suggestions = "، ".join(alternatives)
        if status == "missing":
            return (
                "براہ کرم اپائنٹمنٹ کے لیے مکمل تاریخ اور وقت بتا دیں، "
                "مثلاً 2026-08-15 14:00۔"
            )
        if status == "selection":
            return slot
        if suggestions:
            return (
                f"معذرت، {slot} پر مطلوبہ وقت دستیاب نہیں ہے۔ "
                f"ان متبادل اوقات میں سے ایک منتخب کریں: {suggestions}"
            )
        return (
            f"معذرت، {slot} کے بعد قریب کوئی وقت دستیاب نہیں ملا۔ "
            "براہ کرم کوئی دوسری تاریخ اور وقت بتا دیں۔"
        )

    def _normalise_selection(self, data: dict) -> tuple[dict, str]:
        departments = self._configuration.get("departments") or []
        practitioners = self._configuration.get("practitioners") or []
        visit_types = self._configuration.get("visit_types") or []

        practitioner_label = str(
            data.get("ڈاکٹر_کی_ترجیح", data.get("practitioner_preference", "")) or ""
        ).strip()
        practitioner_id = self._match_config_id(
            practitioners,
            "practitioner_id",
            "display_name",
            str(data.get("practitioner_id") or ""),
            practitioner_label,
        )
        no_preference = self._is_no_doctor_preference(practitioner_label)
        if practitioner_label and not practitioner_id and not no_preference:
            return data, self._doctor_selection_prompt()

        department_id = self._match_config_id(
            departments,
            "department_id",
            "name",
            str(data.get("department_id") or ""),
            str(data.get("شعبہ", data.get("department", "")) or ""),
        )
        selected_practitioner = next(
            (
                item for item in practitioners
                if str(item.get("practitioner_id")) == practitioner_id
            ),
            None,
        )
        if not department_id and len(departments) == 1:
            department_id = str(departments[0].get("department_id") or "")
        if selected_practitioner:
            practitioner_department = str(selected_practitioner.get("department_id") or "")
            if department_id and department_id != practitioner_department:
                return data, "منتخب ڈاکٹر اس شعبے میں نہیں ہیں۔ براہ کرم شعبہ یا ڈاکٹر دوبارہ منتخب کریں۔"
            department_id = practitioner_department
        if not department_id:
            return data, "براہ کرم دستیاب فہرست میں سے مطلوبہ شعبہ دوبارہ بتائیں۔"

        visit_type_id = self._match_config_id(
            visit_types,
            "visit_type_id",
            "name",
            str(data.get("visit_type_id") or ""),
            str(data.get("ملاقات_کی_قسم", data.get("visit_type", "")) or ""),
        )
        if not visit_type_id:
            visit_type_id = self._infer_visit_type_id(
                visit_types,
                str(data.get("ملاقات_کی_قسم", data.get("visit_type", "")) or ""),
                str(data.get("پہلی_بار", data.get("first_visit", "")) or ""),
            )
        if not visit_type_id:
            return data, "براہ کرم ملاقات کی قسم دوبارہ بتائیں۔"

        slot = str(
            data.get(
                "بکنگ_کا_وقت",
                data.get("booking_slot_time", data.get("booking_time_slot", "")),
            )
            or ""
        ).strip()
        if not slot:
            return data, self._build_booking_retry_message("missing", [])
        slot = self._resolve_booking_slot(slot)
        if not slot:
            return data, (
                "بکنگ کی تاریخ اور وقت واضح نہیں ہے۔ مکمل تاریخ اور وقت دوبارہ بتائیں، "
                "مثلاً کل دوپہر دو بجے یا 2026-08-15 14:00۔"
            )
        available_slot = self._match_available_slot(
            slot,
            visit_type_id=visit_type_id,
            practitioner_id=practitioner_id,
        )
        if getattr(self, "_booking_options", None) and not available_slot:
            return data, (
                "یہ وقت دکھائے گئے دستیاب سلاٹس میں شامل نہیں ہے۔ "
                "براہ کرم فہرست میں سے سلاٹ نمبر منتخب کریں۔"
            )
        if available_slot:
            slot = available_slot

        department = next(
            item for item in departments
            if str(item.get("department_id")) == department_id
        )
        visit_type = next(
            item for item in visit_types
            if str(item.get("visit_type_id")) == visit_type_id
        )
        normalized = dict(data)
        normalized["department_id"] = department_id
        normalized["practitioner_id"] = practitioner_id
        normalized["visit_type_id"] = visit_type_id
        normalized["شعبہ"] = str(department.get("name") or "")
        normalized["ڈاکٹر_کی_ترجیح"] = (
            self._patient_facing_doctor_name(
                selected_practitioner.get("display_name") or ""
            )
            if selected_practitioner
            else "کوئی خاص ترجیح نہیں"
        )
        normalized["ملاقات_کی_قسم"] = str(visit_type.get("name") or "")
        normalized["بکنگ_کا_وقت"] = slot
        return normalized, ""

    def _match_available_slot(
        self,
        value: str,
        *,
        visit_type_id: str = "",
        practitioner_id: str = "",
    ) -> str:
        options = getattr(self, "_booking_options", None) or []
        if not options:
            return ""
        try:
            candidate = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return ""
        timezone_name = str(
            (self._configuration.get("clinic") or {}).get("timezone")
            or "Asia/Karachi"
        )
        timezone = ZoneInfo(timezone_name)
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone)
        else:
            candidate = candidate.astimezone(timezone)
        matching = []
        for option in options:
            if visit_type_id and option.get("visit_type_id") != visit_type_id:
                continue
            if practitioner_id and option.get("practitioner_id") != practitioner_id:
                continue
            try:
                option_start = datetime.fromisoformat(str(option.get("start_at") or ""))
            except ValueError:
                continue
            if option_start.tzinfo is None:
                option_start = option_start.replace(tzinfo=timezone)
            else:
                option_start = option_start.astimezone(timezone)
            if option_start == candidate:
                matching.append(str(option["start_at"]))
        return matching[0] if len(set(matching)) == 1 else ""

    @staticmethod
    def _normalized_choice(value: str) -> str:
        text = unicodedata.normalize("NFKC", str(value or "")).casefold()
        text = text.replace("_", " ").replace("ڈاکٹر", " ")
        text = re.sub(r"\b(?:dr|doctor)\.?", " ", text)
        return " ".join(
            re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        )

    @staticmethod
    def _spoken_selection_index(value: str, item_count: int) -> int | None:
        converted: list[str] = []
        for character in str(value or ""):
            try:
                converted.append(str(unicodedata.digit(character)))
            except (TypeError, ValueError):
                converted.append(character)
        normalized = " ".join("".join(converted).casefold().split())
        number_match = re.search(r"(?:نمبر|number|option)?\s*(\d+)", normalized)
        if number_match:
            index = int(number_match.group(1)) - 1
            return index if 0 <= index < item_count else None
        ordinal_markers = (
            (0, ("پہلا", "پہلے", "first")),
            (1, ("دوسرا", "دوسرے", "second")),
            (2, ("تیسرا", "تیسرے", "third")),
        )
        for index, markers in ordinal_markers:
            if index < item_count and any(marker in normalized for marker in markers):
                return index
        return None

    @staticmethod
    def _match_config_id(
        items: list[dict],
        id_key: str,
        name_key: str,
        candidate_id: str,
        candidate_label: str,
    ) -> str:
        clean_id = str(candidate_id or "").strip()
        if clean_id:
            exact = next(
                (item for item in items if str(item.get(id_key) or "") == clean_id),
                None,
            )
            if exact:
                return str(exact[id_key])
        raw_label = str(candidate_label or clean_id)
        if name_key == "display_name":
            selected_index = ReceptionistAgent._spoken_selection_index(
                raw_label,
                len(items),
            )
            if selected_index is not None:
                return str(items[selected_index].get(id_key) or "")
        label = ReceptionistAgent._normalized_choice(raw_label)
        if not label:
            return ""
        matches = [
            item for item in items
            if label == ReceptionistAgent._normalized_choice(item.get(name_key, ""))
        ]
        if len(matches) == 1:
            return str(matches[0][id_key])
        contains = [
            item for item in items
            if (
                label in ReceptionistAgent._normalized_choice(item.get(name_key, ""))
                or ReceptionistAgent._normalized_choice(item.get(name_key, "")) in label
            )
        ]
        return str(contains[0][id_key]) if len(contains) == 1 else ""

    @staticmethod
    def _infer_visit_type_id(
        visit_types: list[dict],
        label: str,
        first_visit: str,
    ) -> str:
        label_text = " ".join(str(label or "").casefold().split())
        first_text = " ".join(str(first_visit or "").casefold().split())

        def choose(*terms: str, remote: bool | None = None) -> str:
            for item in visit_types:
                item_text = " ".join(
                    (
                        str(item.get("visit_type_id") or ""),
                        str(item.get("name") or ""),
                    )
                ).casefold()
                if remote is not None:
                    is_remote = str(item.get("mode") or "").upper() == "REMOTE"
                    if is_remote == remote:
                        return str(item.get("visit_type_id") or "")
                if any(term in item_text for term in terms):
                    return str(item.get("visit_type_id") or "")
            return ""

        if any(
            term in label_text
            for term in ("tele", "remote", "online", "آن لائن", "ویڈیو", "فون پر")
        ):
            return choose(remote=True)
        if any(
            term in label_text
            for term in ("follow", "فالو", "دوبارہ", "پہلے بھی")
        ):
            return choose("follow")
        if any(
            term in label_text
            for term in ("new", "نئی", "نیا", "پہلی")
        ):
            return choose("new")

        returning = any(
            term in first_text
            for term in ("نہیں", "پہلے", "return", "not first", "no")
        )
        if returning:
            return choose("follow")
        if any(term in first_text for term in ("ہاں", "جی", "پہلی", "first", "yes")):
            return choose("new")
        return ""

    def _resolve_booking_slot(self, value: str) -> str:
        text_parts: list[str] = []
        for character in str(value or ""):
            try:
                text_parts.append(str(unicodedata.digit(character)))
            except (TypeError, ValueError):
                text_parts.append(character)
        text = " ".join("".join(text_parts).strip().split())
        if not text:
            return ""

        direct = re.search(
            r"(?<!\d)(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?!\d)",
            text,
        )
        if direct:
            candidate = f"{direct.group(1)} {int(direct.group(2)):02d}:{direct.group(3)}"
            try:
                datetime.fromisoformat(candidate)
                return candidate
            except ValueError:
                return ""

        clinic = self._configuration.get("clinic") or {}
        current_text = str(clinic.get("current_time") or "")
        timezone_name = str(clinic.get("timezone") or "Asia/Karachi")
        try:
            reference = datetime.fromisoformat(current_text)
        except ValueError:
            reference = datetime.now(ZoneInfo(timezone_name))

        normalized = text.casefold()
        date_match = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", normalized)
        if date_match:
            try:
                target_date = datetime.fromisoformat(date_match.group(1)).date()
            except ValueError:
                return ""
        elif "tomorrow" in normalized or re.search(
            r"(?:^|[\s،,])کل(?:$|[\s،,])",
            normalized,
        ):
            target_date = (reference + timedelta(days=1)).date()
        elif "today" in normalized or "آج" in normalized:
            target_date = reference.date()
        else:
            return ""

        hour: int | None = None
        minute = 0
        explicit_time = re.search(
            r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
            normalized,
        )
        meridiem = ""
        if explicit_time:
            hour = int(explicit_time.group(1))
            minute = int(explicit_time.group(2))
        else:
            am_pm = re.search(r"(?<!\d)(1[0-2]|0?[1-9])(?:[:.]([0-5]\d))?\s*(am|pm)\b", normalized)
            if am_pm:
                hour = int(am_pm.group(1))
                minute = int(am_pm.group(2) or "0")
                meridiem = am_pm.group(3)
            else:
                word_hours = {
                    "ایک": 1,
                    "دو": 2,
                    "تین": 3,
                    "چار": 4,
                    "پانچ": 5,
                    "چھ": 6,
                    "سات": 7,
                    "آٹھ": 8,
                    "اٹھ": 8,
                    "نو": 9,
                    "دس": 10,
                    "گیارہ": 11,
                    "بارہ": 12,
                }
                if "بج" in normalized:
                    hour = next(
                        (number for word, number in word_hours.items() if word in normalized),
                        None,
                    )
        if hour is None:
            return ""
        afternoon = any(
            marker in normalized
            for marker in ("دوپہر", "شام", "رات", "afternoon", "evening", "night")
        )
        if meridiem == "pm" or afternoon:
            if hour < 12:
                hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        try:
            resolved = datetime.combine(target_date, datetime.min.time()).replace(
                hour=hour,
                minute=minute,
            )
        except ValueError:
            return ""
        return resolved.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _is_no_doctor_preference(value: str) -> bool:
        normalized = str(value or "").casefold()
        if not normalized:
            return True
        return any(
            phrase in normalized
            for phrase in (
                "no preference",
                "any doctor",
                "کوئی خاص",
                "کوئی بھی",
                "ترجیح نہیں",
            )
        )

    def _attempt_booking(self, data: dict) -> tuple[str, bool]:
        if not self._pending:
            return "بکنگ سیشن دستیاب نہیں ہے۔ براہ کرم دوبارہ آغاز کریں۔", False
        payload = {
            "patient_id": self._pending["patient_id"],
            "workflow_id": self._pending["workflow_id"],
            "department_id": data["department_id"],
            "practitioner_id": data.get("practitioner_id", ""),
            "visit_type_id": data["visit_type_id"],
            "start_at": data["بکنگ_کا_وقت"],
            "idempotency_key": self._booking_idempotency_key(data),
            "intake_token": self._intake_token,
            "revision": self.llm.record.revision,
        }
        try:
            result = self.api.book(payload)
        except ReceptionistAPIError as exc:
            if exc.code in {
                "DEPARTMENT_NOT_FOUND",
                "PRACTITIONER_UNAVAILABLE",
                "PROFILE_MISMATCH",
                "VISIT_TYPE_NOT_FOUND",
            }:
                message = (
                    "کلینک کی دستیاب فہرست بدل گئی ہے۔ "
                    "براہ کرم شعبہ، ڈاکٹر کی ترجیح اور ملاقات کی قسم دوبارہ بتائیں۔"
                )
            else:
                message = (
                "اس وقت محفوظ بکنگ سروس سے رابطہ نہیں ہو سکا۔ "
                "اپائنٹمنٹ کنفرم نہیں ہوئی؛ براہ کرم دوبارہ کوشش کہیں۔"
                )
            self.llm.continue_after_assistant_prompt(message)
            self._publish_intake()
            return message, False

        if result.get("status") not in {"BOOKED", "REQUESTED"}:
            raw_alternatives = result.get("alternatives") or []
            selected_visit = next(
                (
                    item
                    for item in self._configuration.get("visit_types") or []
                    if str(item.get("visit_type_id") or "") == data["visit_type_id"]
                ),
                {},
            )
            refreshed_options = [
                {
                    **item,
                    "label": self._format_alternative(item),
                    "visit_type_name": str(selected_visit.get("name") or ""),
                }
                for item in raw_alternatives
            ]
            if refreshed_options:
                self._booking_options = refreshed_options
                self.llm.set_booking_options(refreshed_options)
                self._notify(
                    "schedule_options",
                    {
                        "doctor_name": str(
                            refreshed_options[0].get("practitioner_name") or ""
                        ),
                        "slots": refreshed_options,
                    },
                )
            alternatives = [
                f"نمبر {index}: {self._format_alternative(item)}"
                for index, item in enumerate(raw_alternatives, start=1)
            ]
            message = self._build_booking_retry_message(
                "unavailable",
                alternatives,
                data["بکنگ_کا_وقت"],
            )
            self._pending["data"] = data
            self.llm.continue_after_assistant_prompt(message, field="booking_slot_time")
            self._publish_intake()
            return message, False

        appointment = result.get("appointment") or {}
        data["بکنگ_کا_وقت"] = str(appointment.get("start_at") or data["بکنگ_کا_وقت"])
        data["ڈاکٹر_کی_ترجیح"] = str(
            appointment.get("practitioner_name") or data["ڈاکٹر_کی_ترجیح"]
        )
        data["ڈاکٹر_کی_ترجیح"] = self._patient_facing_doctor_name(
            data["ڈاکٹر_کی_ترجیح"]
        )
        data["appointment_id"] = str(appointment.get("appointment_id") or "")
        self._pending["data"] = data
        self._pending["appointment"] = appointment
        self.llm.mark_forwarded()
        self._notify("patient_data", data)
        requested = str(appointment.get("status") or "") == "REQUESTED"
        print(
            "✅  Appointment forwarded through clinic API "
            f"({data['appointment_id'] or 'opaque appointment reference'})."
        )
        formatted_time = self._format_booking_time(data["بکنگ_کا_وقت"])
        doctor_name = data["ڈاکٹر_کی_ترجیح"]
        if requested:
            return (
                f"{doctor_name} کے ساتھ {formatted_time} کا سلاٹ محفوظ کرکے "
                "ڈاکٹر کے ڈیش بورڈ پر بھیج دیا گیا ہے۔ "
                "ڈاکٹر کے ورک اسپیس میں فون OTP کی تصدیق کے بعد اپائنٹمنٹ حتمی کنفرم ہوگی۔"
            ), True
        return (
            f"آپ کی اپائنٹمنٹ {doctor_name} کے ساتھ {formatted_time} پر کنفرم ہوگئی ہے۔ "
            "یہ اپائنٹمنٹ ڈاکٹر کے ڈیش بورڈ پر بھیج دی گئی ہے۔ شکریہ۔"
        ), True

    def _booking_idempotency_key(self, data: dict) -> str:
        source = "|".join(
            [
                str(self._pending["workflow_id"]) if self._pending else "",
                str(data.get("department_id") or ""),
                str(data.get("practitioner_id") or "AUTO"),
                str(data.get("visit_type_id") or ""),
                str(data.get("بکنگ_کا_وقت") or ""),
            ]
        )
        return f"receptionist-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:32]}"

    @staticmethod
    def _format_booking_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return parsed.strftime("%d %B %Y، %I:%M %p")

    def _format_alternative(self, alternative: dict) -> str:
        when = self._format_booking_time(str(alternative.get("start_at") or ""))
        doctor = str(alternative.get("practitioner_name") or "")
        return f"{when}، {doctor}" if doctor else when

    def _deliver_followup(self, message: str, *, complete: bool = False) -> None:
        self._notify("agent_msg", message)
        self._notify("status", "speaking")
        self.tts.speak(message)
        self._notify("status", "complete" if complete else "idle")

    def _on_complete(self) -> bool:
        """Save a confirmed intake and forward a pending booking to the doctor."""
        if not self.llm.is_complete():
            return False
        print("Preparing confirmed intake.")
        data = self.llm.extract_patient_data()
        if not data:
            message = "معلومات مکمل طور پر سمجھ نہیں آئیں۔ براہ کرم آخری تفصیل دوبارہ بتائیں۔"
            self.llm.continue_after_assistant_prompt(message)
            self._deliver_followup(message)
            return False

        data, selection_error = self._normalise_selection(data)
        if selection_error:
            message = self._build_booking_retry_message(
                "selection",
                [],
                selection_error,
            )
            self.llm.continue_after_assistant_prompt(message)
            self._notify("patient_data", data)
            self._deliver_followup(message)
            return False

        intake_payload = {
            "name": data.get("نام", ""),
            "age_text": data.get("عمر", ""),
            "phone_number": data.get("فون_نمبر", ""),
            "first_visit": data.get("پہلی_بار", ""),
            "past_medical_history": data.get("پچھلی_بیماریاں", ""),
            "current_complaint": data.get("آج_کی_شکایت", ""),
            "intake_token": self._intake_token,
            "revision": self.llm.record.revision,
            "confirmed_revision": self.llm.record.confirmed_revision,
        }
        try:
            if self._pending:
                result = self.api.update_intake(self._pending["patient_id"], {
                    **intake_payload,
                    "workflow_id": self._pending["workflow_id"],
                    "expected_revision": self._pending["revision"],
                })
            else:
                result = self.api.create_intake(intake_payload)
        except ReceptionistAPIError:
            message = (
                "معلومات محفوظ سروس میں درج نہیں ہو سکیں۔ "
                "کوئی اپائنٹمنٹ نہیں بنی؛ براہ کرم دوبارہ کوشش کہیں۔"
            )
            self.llm.continue_after_assistant_prompt(message)
            self._publish_intake()
            self._deliver_followup(message)
            return False

        self._pending = {
            "patient_id": result["patient_id"],
            "workflow_id": result["workflow_id"],
            "data": data,
            "revision": result["revision"],
        }
        self._notify("patient_data", data)
        message, complete = self._attempt_booking(data)
        self._deliver_followup(message, complete=complete)
        return complete
