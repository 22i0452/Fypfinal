"""Spoken Urdu/English appointment times resolve to exact clinic-local slots."""
from __future__ import annotations

import unittest
from datetime import date, datetime

from app.services.slot_time import format_slot, resolve_clock, resolve_day


TODAY = date(2026, 10, 6)  # Tuesday


class SlotTimeTests(unittest.TestCase):
    def test_resolves_days(self) -> None:
        cases = {
            "سات تاریخ، سات اکتوبر کو": date(2026, 10, 7),
            "کل": date(2026, 10, 7),
            "پرسوں": date(2026, 10, 8),
            "آج": TODAY,
            "اگلے سوموار": date(2026, 10, 12),
            "جمعرات کو": date(2026, 10, 8),
            "منگل": TODAY,
            "اگلے منگل": date(2026, 10, 13),
            "5 تاریخ": date(2026, 11, 5),  # already past this month
            "7th October": date(2026, 10, 7),
            "tomorrow": date(2026, 10, 7),
            "2 جنوری": date(2027, 1, 2),
        }
        for text, expected in cases.items():
            self.assertEqual(resolve_day(text, TODAY), expected, text)

    def test_resolves_clock_times(self) -> None:
        cases = {
            "سات بجے صبح": (7, 0),
            "دوپہر 2 بجے": (14, 0),
            "شام 4 بجے": (16, 0),
            "ساڑھے دس بجے": (10, 30),
            "پونے گیارہ بجے": (10, 45),
            "دو بجے": (14, 0),  # no period: afternoon at a clinic
            "11 بجے": (11, 0),
            "3 pm": (15, 0),
            "10:30 am": (10, 30),
            "12 بجے دوپہر": (12, 0),
        }
        for text, expected in cases.items():
            self.assertEqual(resolve_clock(text), expected, text)

    def test_missing_parts_are_none(self) -> None:
        self.assertIsNone(resolve_day("دو بجے", TODAY))
        self.assertIsNone(resolve_clock("کل"))
        self.assertIsNone(resolve_day("جیسے آپ کہیں", TODAY))

    def test_format_slot(self) -> None:
        self.assertEqual(
            format_slot(datetime(2026, 10, 7, 7, 0)),
            ("بدھ 7 اکتوبر، صبح 7 بجے", "Wednesday 7 October, 7:00 AM"),
        )
        self.assertEqual(
            format_slot(datetime(2026, 10, 8, 14, 30)),
            ("جمعرات 8 اکتوبر، دوپہر ساڑھے 2 بجے", "Thursday 8 October, 2:30 PM"),
        )


if __name__ == "__main__":
    unittest.main()
