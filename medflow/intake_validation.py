from __future__ import annotations

import re
import unicodedata


_URDU_AGES = {
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
    "تیرہ": 13,
    "چودہ": 14,
    "پندرہ": 15,
    "سولہ": 16,
    "سترہ": 17,
    "اٹھارہ": 18,
    "انیس": 19,
    "بیس": 20,
    "اکیس": 21,
    "بائیس": 22,
    "تئیس": 23,
    "تیئس": 23,
    "چوبیس": 24,
    "پچیس": 25,
    "چھبیس": 26,
    "ستائیس": 27,
    "اٹھائیس": 28,
    "انتیس": 29,
    "تیس": 30,
    "اکتیس": 31,
    "بتیس": 32,
    "تینتیس": 33,
    "چونتیس": 34,
    "پینتیس": 35,
    "چھتیس": 36,
    "سینتیس": 37,
    "اڑتیس": 38,
    "انتالیس": 39,
    "چالیس": 40,
    "اکتالیس": 41,
    "بیالیس": 42,
    "تینتالیس": 43,
    "چوالیس": 44,
    "پینتالیس": 45,
    "چھیالیس": 46,
    "سینتالیس": 47,
    "اڑتالیس": 48,
    "انچاس": 49,
    "پچاس": 50,
    "اکیاون": 51,
    "باون": 52,
    "ترپن": 53,
    "چون": 54,
    "چوّن": 54,
    "پچپن": 55,
    "چھپن": 56,
    "ستاون": 57,
    "اٹھاون": 58,
    "انسٹھ": 59,
    "ساٹھ": 60,
    "اکسٹھ": 61,
    "باسٹھ": 62,
    "تریسٹھ": 63,
    "چونسٹھ": 64,
    "پینسٹھ": 65,
    "چھیاسٹھ": 66,
    "سڑسٹھ": 67,
    "اڑسٹھ": 68,
    "انہتر": 69,
    "ستر": 70,
    "اکہتر": 71,
    "بہتر": 72,
    "تہتر": 73,
    "چوہتر": 74,
    "پچہتر": 75,
    "چھہتر": 76,
    "ستتر": 77,
    "اٹھہتر": 78,
    "اناسی": 79,
    "اسی": 80,
    "اکیاسی": 81,
    "بیاسی": 82,
    "تراسی": 83,
    "چوراسی": 84,
    "پچاسی": 85,
    "چھیاسی": 86,
    "ستاسی": 87,
    "اٹھاسی": 88,
    "نواسی": 89,
    "نوے": 90,
    "اکانوے": 91,
    "بانوے": 92,
    "ترانوے": 93,
    "چورانوے": 94,
    "پچانوے": 95,
    "چھیانوے": 96,
    "ستانوے": 97,
    "اٹھانوے": 98,
    "ننانوے": 99,
    "سو": 100,
}

_ENGLISH_ONES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_ENGLISH_TENS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_STT_NOISE = {
    "music",
    "موسیقی",
    "silence",
    "خاموشی",
    "thank you",
    "thanks for watching",
    "subtitles",
}


def ascii_digits(value: str) -> str:
    output: list[str] = []
    for character in str(value or ""):
        try:
            output.append(str(unicodedata.digit(character)))
        except (TypeError, ValueError):
            output.append(character)
    return "".join(output)


def normalize_name(value: str) -> str:
    clean = " ".join(str(value or "").strip().split())
    if not clean or len(clean) > 160 or re.search(
        r"\b(?:joking|kidding|wrong|unknown|maybe|don't know|ignore|yes|no)\b|مذاق|معلوم نہیں|غلط",
        clean, re.I,
    ):
        return ""
    patterns = (
        r"(?:میرا\s+نام|نام)\s+(.+?)(?:\s+ہے(?:\b|۔)|[،,.]|$)",
        r"(?:my\s+name\s+is|name\s+is)\s+(.+?)(?:[،,.]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, clean, flags=re.I)
        if match:
            clean = match.group(1).strip()
            break
    clean = re.split(r"[،,;]", clean, maxsplit=1)[0].strip()[:120]
    normalized = clean.casefold()
    letters = sum(character.isalpha() for character in clean)
    if (
        letters < 2
        or any(character.isdigit() for character in ascii_digits(clean))
        or normalized in _STT_NOISE
    ):
        return ""
    return clean


def normalize_age(value: str) -> str:
    clean = " ".join(ascii_digits(value).casefold().replace("-", " ").split())
    if re.search(r"\b(?:or|maybe|not|nahi|nahin|ghalat|galat)\b|نہیں|شاید|غلط|\d[.,]\d", clean):
        return ""
    numbers = re.findall(r"(?<!\d)\d+(?!\d)", clean)
    if len(numbers) > 1:
        return ""
    numeric = re.search(r"(?<!\d)(\d{1,3})(?!\d)", clean)
    if numeric:
        age = int(numeric.group(1))
        return str(age) if 1 <= age <= 120 else ""

    tokens = re.findall(r"[^\W_]+", clean, flags=re.UNICODE)
    roman_ages = {"bees": 20, "pachees": 25, "tees": 30, "paintees": 35, "paintis": 35, "chalis": 40, "pachas": 50, "saath": 60}
    for token in tokens:
        if token in roman_ages:
            return str(roman_ages[token])
    if len([token for token in tokens if token in _URDU_AGES]) > 1:
        return ""
    for token in tokens:
        if token in _URDU_AGES:
            return str(_URDU_AGES[token])

    number_tokens = [
        token
        for token in tokens
        if token in _ENGLISH_ONES or token in _ENGLISH_TENS or token in {"hundred", "and"}
    ]
    if not number_tokens:
        return ""
    total = 0
    current = 0
    for token in number_tokens:
        if token in _ENGLISH_ONES:
            current += _ENGLISH_ONES[token]
        elif token in _ENGLISH_TENS:
            current += _ENGLISH_TENS[token]
        elif token == "hundred":
            current = max(1, current) * 100
        elif token == "and":
            continue
    total += current
    return str(total) if 1 <= total <= 120 else ""


def normalize_phone(value: str) -> str:
    clean = ascii_digits(value).strip()
    clean = re.sub(r"^(?:my (?:phone|mobile)(?: number)? is|میرا (?:فون|موبائل) نمبر|mera (?:phone|mobile) number)\s*", "", clean, flags=re.I)
    clean = re.sub(r"\s*(?:ہے|hai)[.۔]?$", "", clean).strip()
    if not re.fullmatch(r"\+?[\d\s().-]+", clean):
        return ""
    digits = re.sub(r"\D", "", clean)
    return digits if 10 <= len(digits) <= 13 else ""


def normalize_first_visit(value: str) -> str:
    clean = " ".join(str(value or "").casefold().split())
    tokens = set(re.findall(r"[^\W_]+", clean, flags=re.UNICODE))
    if tokens & {"yes", "haan", "han", "ہاں"} and tokens & {"no", "nahi", "nahin", "نہیں"}:
        return ""
    if re.search(r"\b(?:maybe|not sure|don't know)\b|معلوم نہیں|شاید", clean):
        return ""
    if "pehli" in tokens and not tokens & {"nahi", "nahin"}:
        return "Yes"
    if (
        any(marker in clean for marker in ("نہیں", "پہلے", "not first"))
        or tokens
        & {
            "no",
            "nahi",
            "nahin",
            "before",
            "follow",
            "followup",
            "return",
            "returning",
        }
    ):
        return "No"
    if (
        any(marker in clean for marker in ("جی", "ہاں", "پہلی"))
        or tokens & {"first", "yes", "haan", "han"}
    ):
        return "Yes"
    return ""


def normalize_blood_pressure(value: str) -> str:
    clean = " ".join(ascii_digits(value).casefold().split())
    if any(
        marker in clean
        for marker in (
            "نہیں ناپا",
            "معلوم نہیں",
            "پتا نہیں",
            "پتہ نہیں",
            "not measured",
            "not checked",
            "unknown",
        )
    ):
        return "Not measured"

    numbers = [int(number) for number in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", clean)]
    has_separator = any(
        marker in clean
        for marker in ("/", " over ", "پر", "بٹا", "mmhg")
    )
    if len(numbers) != 2 or not has_separator:
        return ""
    systolic, diastolic = numbers
    if not (70 <= systolic <= 250 and 40 <= diastolic <= 150 and systolic > diastolic):
        return ""
    return f"{systolic}/{diastolic} mmHg"


def is_meaningful_text(value: str, *, minimum_letters: int = 2) -> bool:
    clean = " ".join(str(value or "").strip().split())
    if not clean or len(clean) > 2000 or clean.casefold() in _STT_NOISE:
        return False
    if re.search(
        r"\b(?:joking|kidding|made (?:it|that) up|ignore previous|system prompt|CONVERSATION_COMPLETE)\b"
        r"|مذاق|سسٹم پرامپٹ|مریض .*بتا رہا",
        clean, re.I,
    ):
        return False
    return sum(character.isalpha() for character in clean) >= minimum_letters
