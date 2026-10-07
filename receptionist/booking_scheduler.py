from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


BOOKING_FIELD_NAMES = (
    "booking_slot_time",
    "booking_time_slot",
    "بکنگ_کا_وقت",
)

_PARSE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M %p",
    "%Y-%m-%d %I %p",
    "%d-%m-%Y %H:%M",
    "%d-%m-%Y %I:%M %p",
    "%d-%m-%Y %I %p",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %I:%M %p",
    "%Y/%m/%d %I %p",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y %I:%M %p",
    "%d/%m/%Y %I %p",
    "%d %b %Y %H:%M",
    "%d %b %Y %I:%M %p",
    "%d %B %Y %H:%M",
    "%d %B %Y %I:%M %p",
    "%b %d %Y %H:%M",
    "%b %d %Y %I:%M %p",
    "%B %d %Y %H:%M",
    "%B %d %Y %I:%M %p",
)


@dataclass(frozen=True)
class BookingCheckResult:
    status: str
    raw_value: str
    normalized_slot: str
    alternatives: list[str]
    conflicting_record: str = ""


def get_booking_slot(record: dict | None) -> str:
    if not isinstance(record, dict):
        return ""
    for key in BOOKING_FIELD_NAMES:
        value = str(record.get(key, "") or "").strip()
        if value:
            return value
    return ""


def normalize_booking_slot(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""

    text = text.replace("،", " ")
    text = text.replace(",", " ")
    text = text.replace("T", " ")
    text = text.replace("/", "-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(AM|PM|am|pm)\b", lambda m: m.group(1).upper(), text)
    text = re.sub(r"\b(\d{1,2})(?!:)(\s*)(AM|PM)\b", r"\1:00 \3", text)

    iso_candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed.replace(second=0, microsecond=0, tzinfo=None).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass

    for fmt in _PARSE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue

    return ""


def load_booked_slots(records_dir: str | Path) -> dict[str, str]:
    booked: dict[str, str] = {}
    records_path = Path(records_dir)
    if not records_path.exists():
        return booked

    for path in sorted(records_path.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        slot = normalize_booking_slot(get_booking_slot(data))
        if slot:
            booked[slot] = path.name

    return booked


def suggest_available_slots(
    records_dir: str | Path,
    *,
    count: int = 3,
    exclude: list[str] | None = None,
) -> list[str]:
    excluded = {
        normalized
        for normalized in (normalize_booking_slot(item) for item in (exclude or []))
        if normalized
    }
    booked = set(load_booked_slots(records_dir)) | excluded

    suggestions: list[str] = []
    candidate = datetime.now().replace(second=0, microsecond=0, minute=0)
    if candidate <= datetime.now().replace(second=0, microsecond=0):
        candidate += timedelta(hours=1)

    if candidate.hour < 9:
        candidate = candidate.replace(hour=9, minute=0)

    checked = 0
    while len(suggestions) < count and checked < 24 * 30:
        if candidate.weekday() < 6 and 9 <= candidate.hour < 17:
            slot = candidate.strftime("%Y-%m-%d %H:%M")
            if slot not in booked:
                suggestions.append(slot)

        candidate += timedelta(hours=1)
        checked += 1

        if candidate.hour >= 17:
            candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=0)

    return suggestions


def evaluate_booking_slot(slot_value: str, records_dir: str | Path) -> BookingCheckResult:
    raw_value = str(slot_value or "").strip()
    alternatives = suggest_available_slots(records_dir, count=3, exclude=[raw_value])

    if not raw_value:
        return BookingCheckResult(
            status="missing",
            raw_value="",
            normalized_slot="",
            alternatives=alternatives,
        )

    normalized_slot = normalize_booking_slot(raw_value)
    if not normalized_slot:
        return BookingCheckResult(
            status="invalid",
            raw_value=raw_value,
            normalized_slot="",
            alternatives=alternatives,
        )

    booked = load_booked_slots(records_dir)
    if normalized_slot in booked:
        return BookingCheckResult(
            status="unavailable",
            raw_value=raw_value,
            normalized_slot=normalized_slot,
            alternatives=alternatives,
            conflicting_record=booked[normalized_slot],
        )

    return BookingCheckResult(
        status="available",
        raw_value=raw_value,
        normalized_slot=normalized_slot,
        alternatives=alternatives,
    )


def build_schedule_prompt_context(records_dir: str | Path) -> str:
    booked = sorted(load_booked_slots(records_dir))
    suggested = suggest_available_slots(records_dir, count=5)
    booked_text = "، ".join(booked[:10]) if booked else "فی الحال کوئی سلاٹ بک نہیں ہے"
    suggested_text = "، ".join(suggested) if suggested else "متبادل سلاٹس ابھی دستیاب نہیں"

    return (
        "کلینک بکنگ کی اضافی ہدایات:\n"
        "- ساتویں لازمی معلومات مریض کا بکنگ سلاٹ ہے۔\n"
        "- مریض سے تاریخ اور وقت دونوں ضرور پوچھیں۔\n"
        "- بکنگ سلاٹ کو خلاصے اور ریکارڈ میں YYYY-MM-DD HH:MM فارمیٹ میں رکھیں۔\n"
        f"- یہ سلاٹس پہلے سے بک ہیں: {booked_text}.\n"
        f"- یہ قریب ترین دستیاب سلاٹس ہیں: {suggested_text}.\n"
        "- اگر مریض ایسا وقت مانگے جو پہلے سے بک ہو تو معذرت کریں، مریض کو بتائیں کہ ڈاکٹر اس وقت دستیاب نہیں، اور 2 یا 3 متبادل اوقات پیش کریں۔\n"
        "- جب تک مریض ایک واضح اور دستیاب بکنگ سلاٹ منتخب نہ کرے، معلومات مکمل نہ سمجھیں۔"
    )