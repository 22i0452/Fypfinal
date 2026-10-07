"""Resolve a spoken Urdu/English appointment request to a concrete date and time.

LLMs are unreliable at this (they mistranslate "سات تاریخ" as the 6th, or drop
relative days like "کل"), so the booking call resolves dates in code and reads
the exact result back to the caller.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from medflow.intake_validation import ascii_digits


_UR_L, _UR_R = r"(?<![؀-ۿ])", r"(?![؀-ۿ])"

_URDU_NUMBERS = {
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "چھے": 6, "سات": 7, "آٹھ": 8,
    "نو": 9, "دس": 10, "گیارہ": 11, "بارہ": 12, "تیرہ": 13, "چودہ": 14, "پندرہ": 15,
    "سولہ": 16, "سترہ": 17, "اٹھارہ": 18, "انیس": 19, "بیس": 20, "اکیس": 21, "بائیس": 22,
    "تئیس": 23, "چوبیس": 24, "پچیس": 25, "چھبیس": 26, "ستائیس": 27, "اٹھائیس": 28,
    "انتیس": 29, "تیس": 30, "اکتیس": 31,
}
_URDU_NUMBER_RE = re.compile(
    _UR_L + "(" + "|".join(sorted(_URDU_NUMBERS, key=len, reverse=True)) + ")" + _UR_R
)

_MONTHS = {
    "جنوری": 1, "فروری": 2, "مارچ": 3, "اپریل": 4, "مئی": 5, "جون": 6, "جولائی": 7,
    "اگست": 8, "ستمبر": 9, "اکتوبر": 10, "نومبر": 11, "دسمبر": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

# Monday = 0. "جمعرات" must be tried before "جمعہ".
_WEEKDAYS = (
    (r"جمعرات|thursday", 3),
    (r"سوموار|پیر|monday", 0),
    (r"منگل|tuesday", 1),
    (r"بدھ|wednesday", 2),
    (r"جمعہ|جمعے|friday", 4),
    (r"ہفتہ|ہفتے\s+(?:کو|کے\s+دن)|saturday", 5),
    (r"اتوار|sunday", 6),
)
_WEEKDAY_UR = ("پیر", "منگل", "بدھ", "جمعرات", "جمعہ", "ہفتہ", "اتوار")
_MONTH_UR = ("جنوری", "فروری", "مارچ", "اپریل", "مئی", "جون", "جولائی", "اگست", "ستمبر", "اکتوبر", "نومبر", "دسمبر")


def _normalize(text: str) -> str:
    text = ascii_digits(str(text or "")).casefold()
    return _URDU_NUMBER_RE.sub(lambda match: str(_URDU_NUMBERS[match.group(1)]), text)


def _word(pattern: str) -> str:
    """Whole-word match for Urdu (no \\b support) and Latin words alike."""
    return rf"(?:{_UR_L}(?:{pattern}){_UR_R}|\b(?:{pattern})\b)"


def resolve_day(text: str, today: date) -> date | None:
    clean = _normalize(text)
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", clean)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
    if re.search(_word(r"پرسوں|parson|day after tomorrow"), clean):
        return today + timedelta(days=2)
    if re.search(_word(r"کل|kal|tomorrow"), clean):
        return today + timedelta(days=1)
    if re.search(_word(r"آج|aaj|today"), clean):
        return today
    month = None
    month_match = re.search(rf"(?:{_UR_L}|\b)({_MONTH_RE})(?:{_UR_R}|\b)", clean)
    if month_match:
        month = _MONTHS[month_match.group(1)]
    day_match = (
        re.search(r"(\d{1,2})\s*(?:تاریخ|st|nd|rd|th)", clean)
        or (re.search(rf"(\d{{1,2}})\s+(?:{_MONTH_RE})", clean) if month else None)
        or (re.search(rf"(?:{_MONTH_RE})\s+(\d{{1,2}})(?!\s*(?:بجے|:|am|pm))", clean) if month else None)
    )
    if day_match:
        day = int(day_match.group(1))
        candidates = []
        if month:
            candidates = [(today.year, month), (today.year + 1, month)]
        else:
            next_month = (today.year + (today.month == 12), today.month % 12 + 1)
            candidates = [(today.year, today.month), next_month]
        for year, month_number in candidates:
            try:
                resolved = date(year, month_number, day)
            except ValueError:
                continue
            if resolved >= today:
                return resolved
        return None
    for pattern, weekday in _WEEKDAYS:
        if re.search(_word(pattern), clean):
            ahead = (weekday - today.weekday()) % 7
            if ahead == 0 and re.search(_word(r"اگلے|اگلی|next"), clean):
                ahead = 7
            return today + timedelta(days=ahead)
    return None


def resolve_clock(text: str) -> tuple[int, int] | None:
    clean = _normalize(text)
    hour = minute = None
    match = re.search(r"(\d{1,2})[:.](\d{2})", clean)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        match = (
            re.search(r"(ساڑھے|سوا|پونے)?\s*(\d{1,2})\s*بجے", clean)
            or re.search(r"()(\d{1,2})\s*(?:a\.?m\.?|p\.?m\.?|o'?clock|baje)", clean)
            or re.search(r"()\bat\s+(\d{1,2})\b", clean)
        )
        if not match:
            return None
        hour, minute = int(match.group(2)), 0
        if match.group(1) == "ساڑھے":
            minute = 30
        elif match.group(1) == "سوا":
            minute = 15
        elif match.group(1) == "پونے":
            hour, minute = hour - 1, 45
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if hour <= 12:
        if re.search(r"p\.?m\.?|" + _word(r"شام|رات|evening|night"), clean):
            hour = hour % 12 + 12
        elif re.search(_word(r"دوپہر|afternoon|noon"), clean):
            hour = hour if hour == 12 else (hour + 12 if hour < 6 else hour)
        elif re.search(r"a\.?m\.?|" + _word(r"صبح|morning"), clean):
            hour = 0 if hour == 12 else hour
        elif 1 <= hour <= 6:
            # Without a period, "2 بجے" at a clinic means the afternoon.
            hour += 12
    return hour, minute


def format_slot(moment: datetime) -> tuple[str, str]:
    hour, minute = moment.hour, moment.minute
    if hour < 12:
        period = "صبح"
    elif hour < 16:
        period = "دوپہر"
    elif hour < 19:
        period = "شام"
    else:
        period = "رات"
    h12 = hour % 12 or 12
    clock_ur = f"ساڑھے {h12}" if minute == 30 else (f"{h12}:{minute:02d}" if minute else str(h12))
    urdu = f"{_WEEKDAY_UR[moment.weekday()]} {moment.day} {_MONTH_UR[moment.month - 1]}، {period} {clock_ur} بجے"
    english = f"{moment.strftime('%A')} {moment.day} {moment.strftime('%B')}, {h12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"
    return urdu, english
