"""Server-owned booking call: no forgotten answers, read-back confirmations."""
from __future__ import annotations

import unittest
from datetime import date

from app.services.booking_flow import BookingFlow
from app.services.demo_call_service import DemoCallService


def _field(key: str, ur: str, en: str | None = None) -> dict:
    return {"intent": "answer", "fields": {key: {"ur": ur, "en": en or ur}}, "fix": []}


# A fixed Tuesday, so resolved dates in read-backs are predictable.
TODAY = date(2026, 10, 6)


def _h(flow: BookingFlow, text: str, extraction: dict | None) -> tuple[str, str]:
    return flow.handle(text, extraction, today=TODAY)


YES = {"intent": "yes", "fields": {}, "fix": []}
NO = {"intent": "no", "fields": {}, "fix": []}
UNCLEAR = {"intent": "unclear", "fields": {}, "fix": []}


def _complete_until_summary(flow: BookingFlow) -> list[str]:
    """Answer every slot once (confirming read-backs) and return the English replies."""
    script = [
        _field("name", "شہزیب علی خان", "Shahzaib Ali Khan"), YES,
        _field("age", "22"), YES,
        _field("phone", "03037556360"), YES,
        _field("first_visit", "جی ہاں", "Yes"),
        _field("history", "کوئی نہیں", "None"),
        _field("complaint", "گھٹنے میں درد", "Knee pain"),
        _field("department", "جنرل میڈیسن", "General Medicine"),
        _field("doctor", "کوئی بھی دستیاب ڈاکٹر", "Any available doctor"),
        _field("time", "6 تاریخ، صبح 11 بجے", "6th, 11:00 AM"), YES,
    ]
    return [_h(flow, "", extraction)[1] for extraction in script]


class BookingFlowTests(unittest.TestCase):
    def test_reads_back_name_and_asks_each_detail_once(self) -> None:
        flow = BookingFlow()
        replies = _complete_until_summary(flow)

        self.assertEqual(replies[0], "Your name is Shahzaib Ali Khan, is that correct?")
        self.assertEqual(replies[1], "What is your age?")
        self.assertIn("Your age is 22 years, is that correct?", replies)
        self.assertIn("Your number is 0303 755 6360, is that correct?", replies)
        self.assertIn("You would like to come on Tuesday 6 October, 11:00 AM, is that correct?", replies)
        # Every question is asked exactly once; nothing is re-asked.
        for question in ("What is your age?", "What is your mobile number?", "Which day and time would you like to come?"):
            self.assertEqual(sum(question in reply for reply in replies), 1, question)
        self.assertTrue(replies[-1].startswith("Your details: Name: Shahzaib Ali Khan; Age: 22 years"))
        self.assertEqual(flow.step, "summary")

        ur, en = _h(flow, "جی سب درست ہے", YES)
        self.assertTrue(flow.done)
        self.assertIn("General Medicine on Tuesday 6 October, 11:00 AM", en)

    def test_no_with_correct_value_reads_back_the_new_value(self) -> None:
        flow = BookingFlow()
        _h(flow, "", _field("age", "2"))  # stashed: not the current slot yet
        _h(flow, "", _field("name", "علی", "Ali"))
        _h(flow, "", YES)  # name confirmed -> prefilled age is read back
        self.assertEqual(flow.pending["en"], "2")

        _, en = _h(flow, "نہیں 22", {"intent": "no", "fields": {"age": {"ur": "22", "en": "22"}}, "fix": []})
        self.assertEqual(en, "Your age is 22 years, is that correct?")
        _h(flow, "جی", YES)
        self.assertEqual(flow.values["age"]["en"], "22")

    def _at_time_confirmation(self) -> BookingFlow:
        flow = BookingFlow({"step": "collect", "current": "time"})
        _h(flow, "", _field("time", "سات تاریخ، صبح سات بجے", "7th, 7:00 AM"))
        self.assertEqual(flow.step, "confirm")
        return flow

    def test_yes_with_reworded_value_is_still_a_yes(self) -> None:
        # Reported bug: "بلکل یہ درست ہے" came back as yes plus a reworded time,
        # and the agent read the time back again in a loop.
        flow = self._at_time_confirmation()
        reworded = {"intent": "yes", "fields": {"time": {"ur": "سات اکتوبر، صبح سات بجے", "en": "7th, 7th October, 7:00 AM"}}}
        _h(flow, "بلکل یہ درست ہے۔", reworded)
        self.assertEqual(flow.values["time"]["en"], "Wednesday 7 October, 7:00 AM")
        self.assertNotEqual(flow.step, "confirm")

    def test_local_yes_backs_up_unsure_llm(self) -> None:
        for reply in ("بلکل یہ درست ہے۔", "جی ہاں یہ درست ہے۔", "بالکل صحیح", "ٹھیک ہے", "yes correct", "ji bilkul"):
            flow = self._at_time_confirmation()
            reworded = {"intent": "answer", "fields": {"time": {"ur": "سات اکتوبر", "en": "7th, 7th October, 7:00 AM"}}}
            _h(flow, reply, reworded)
            self.assertIn("time", flow.values, reply)
            flow = self._at_time_confirmation()
            _h(flow, reply, UNCLEAR)
            self.assertIn("time", flow.values, reply)

    def test_local_no_and_spoken_new_number_are_not_a_yes(self) -> None:
        flow = self._at_time_confirmation()
        _h(flow, "نہیں یہ غلط ہے", UNCLEAR)
        self.assertNotIn("time", flow.values)
        self.assertEqual(flow.step, "collect")

        flow = self._at_time_confirmation()
        _, en = _h(flow, "جی، 8 بجے", {"intent": "yes", "fields": {"time": {"ur": "صبح 8 بجے", "en": "7th, 8:00 AM"}}})
        self.assertEqual(en, "You would like to come on Wednesday 7 October, 8:00 AM, is that correct?")

    def test_summary_yes_that_echoes_details_finishes(self) -> None:
        flow = BookingFlow()
        _complete_until_summary(flow)
        echo = {"intent": "yes", "fields": {"time": {"ur": "7 اکتوبر", "en": "6th October, 11 AM"}}}
        _h(flow, "جی سب درست ہے", echo)
        self.assertTrue(flow.done)

    def test_yes_no_questions_answered_locally_when_llm_unsure(self) -> None:
        for reply in ("کوئی بھی", "بلکل یہ درست ہے۔", "نہیں کوئی خاص نہیں", "any doctor"):
            flow = BookingFlow({"step": "collect", "current": "doctor"})
            _h(flow, reply, UNCLEAR)
            self.assertEqual(flow.values.get("doctor"), {"ur": "کوئی بھی دستیاب ڈاکٹر", "en": "Any available doctor"}, reply)

        flow = BookingFlow({"step": "collect", "current": "first_visit"})
        _h(flow, "جی ہاں", UNCLEAR)
        self.assertEqual(flow.values["first_visit"]["en"], "Yes")

        flow = BookingFlow({"step": "collect", "current": "history"})
        _h(flow, "نہیں", UNCLEAR)
        self.assertEqual(flow.values["history"]["en"], "None")

    def test_yes_word_does_not_match_inside_other_words(self) -> None:
        from app.services.booking_flow import spoken_yes_no

        self.assertIsNone(spoken_yes_no("جیسے آپ کہیں"))
        self.assertEqual(spoken_yes_no("جی ہاں"), "yes")
        self.assertEqual(spoken_yes_no("جی نہیں"), "no")

    def test_callers_words_beat_llm_date_translation(self) -> None:
        # The LLM turned "سات تاریخ" (7th) into "6th" and gave no exact date.
        flow = BookingFlow({"step": "collect", "current": "time"})
        _, en = _h(flow, "سات تاریخ، سات اکتوبر کو، سات بجے صبح", _field("time", "سات تاریخ، صبح سات بجے", "6th, 7:00 AM"))
        self.assertEqual(en, "You would like to come on Wednesday 7 October, 7:00 AM, is that correct?")
        self.assertEqual(flow.pending["iso"], "2026-10-07T07:00")

    def test_time_found_in_caller_words_when_llm_returns_nothing(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "time"})
        _, en = _h(flow, "کل صبح 11 بجے", UNCLEAR)
        self.assertEqual(en, "You would like to come on Wednesday 7 October, 11:00 AM, is that correct?")

    def test_day_and_hour_can_come_in_separate_turns(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "time"})
        _, en = _h(flow, "کل", _field("time", "کل", "tomorrow"))
        self.assertEqual(en, "At what time would you like to come?")
        restored = BookingFlow.from_history([flow.state_message()])
        _, en = _h(restored, "دوپہر 2 بجے", _field("time", "دوپہر 2 بجے", "2 PM"))
        self.assertEqual(en, "You would like to come on Wednesday 7 October, 2:00 PM, is that correct?")

    def test_correcting_only_the_hour_keeps_the_day(self) -> None:
        flow = self._at_time_confirmation()
        _, en = _h(flow, "نہیں، 8 بجے", {"intent": "no", "fields": {"time": {"ur": "8 بجے", "en": "8 AM"}}})
        self.assertEqual(en, "You would like to come on Wednesday 7 October, 8:00 AM, is that correct?")
        _h(flow, "جی", YES)
        self.assertEqual(flow.values["time"]["iso"], "2026-10-07T08:00")

    def test_plain_no_asks_the_same_detail_again(self) -> None:
        flow = BookingFlow()
        _h(flow, "", _field("name", "شازیب", "Shazeb"))
        _, en = _h(flow, "نہیں", NO)
        self.assertEqual(en, "Sorry about that. Please tell me your full name.")
        self.assertNotIn("name", flow.values)

    def test_unclear_answer_is_not_guessed(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "age", "values": {"name": {"ur": "علی", "en": "Ali"}}})
        _, en = _h(flow, "دوئی سال", UNCLEAR)
        self.assertEqual(en, "Sorry, that was not clear. What is your age?")
        self.assertNotIn("age", flow.values)

    def test_incomplete_mobile_number_is_rejected(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "phone"})
        _, en = _h(flow, "0303755636", _field("phone", "0303755636"))
        self.assertIn("incomplete", en)
        self.assertNotIn("phone", flow.values)

    def test_unavailable_department_offers_the_clinic_departments(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "department"})
        ur, en = _h(flow, "", _field("department", "آرتھوپیڈک", "Orthopedics"))
        self.assertIn("آرتھوپیڈک", ur)
        self.assertIn("General Medicine, Cardiology or Pediatrics", en)
        self.assertNotIn("department", flow.values)

    def test_summary_correction_reasks_only_that_field(self) -> None:
        flow = BookingFlow()
        _complete_until_summary(flow)

        _, en = _h(flow, "عمر غلط ہے", {"intent": "no", "fields": {}, "fix": ["age"]})
        self.assertEqual(en, "What is your age?")
        _, en = _h(flow, "", _field("age", "23"))
        self.assertEqual(en, "Your age is 23 years, is that correct?")
        _, en = _h(flow, "", YES)
        # Straight back to the summary; nothing else is asked again.
        self.assertTrue(en.startswith("Your details:"))
        self.assertIn("Age: 23 years", en)

    def test_repeat_replays_last_question(self) -> None:
        flow = BookingFlow({"step": "collect", "current": "age", "last_prompt": ["آپ کی عمر کتنی ہے؟", "What is your age?"]})
        self.assertEqual(_h(flow, "دوبارہ بتائیں", {"intent": "repeat"})[1], "What is your age?")

    def test_state_survives_history_round_trip(self) -> None:
        flow = BookingFlow()
        _h(flow, "", _field("name", "شہزیب", "Shahzaib"))
        _h(flow, "", YES)
        restored = BookingFlow.from_history([{"role": "assistant", "content": "x"}, flow.state_message()])
        self.assertEqual(restored.values["name"]["en"], "Shahzaib")
        self.assertEqual(restored.current, "age")


class DemoBookingCallTests(unittest.TestCase):
    def _service(self, extractions: list[dict]) -> DemoCallService:
        service = DemoCallService(groq_api_key="", groq_llm_model="", openrouter_api_key="")
        queue = list(extractions)
        service._extract = lambda flow, text: queue.pop(0)  # type: ignore[method-assign]
        return service

    def test_long_call_never_forgets_early_answers(self) -> None:
        # Many unclear turns would have pushed the name out of the old 11-message window.
        extractions = [_field("name", "شہزیب", "Shahzaib"), YES, *[UNCLEAR] * 15, _field("age", "22")]
        service = self._service(extractions)
        result = service.start("in-new-booking")
        history = result["history"]
        for _ in extractions:
            result = service.turn(scenario_id="in-new-booking", history=history, user_message="...")
            history = result["history"]

        self.assertIn("Your age is 22 years", result["reply"])
        self.assertEqual(BookingFlow.from_history(history).values["name"]["en"], "Shahzaib")
        self.assertLessEqual(len(history), 21)
        self.assertNotIn("name", result["reply"].lower())

    def test_reply_is_two_bilingual_lines(self) -> None:
        service = self._service([_field("name", "شہزیب علی خان", "Shahzaib Ali Khan")])
        history = service.start("in-new-booking")["history"]
        result = service.turn(scenario_id="in-new-booking", history=history, user_message="میرا نام شہزیب علی خان ہے")
        urdu, english = result["reply"].split("\n")
        self.assertEqual(urdu, "آپ کا نام شہزیب علی خان ہے، کیا یہ درست ہے؟")
        self.assertEqual(english, "Your name is Shahzaib Ali Khan, is that correct?")
        self.assertEqual(result["speech_text"], urdu)

    def test_without_llm_fallback_still_collects_name(self) -> None:
        service = DemoCallService(groq_api_key="", groq_llm_model="", openrouter_api_key="")
        history = service.start("in-new-booking")["history"]
        result = service.turn(scenario_id="in-new-booking", history=history, user_message="میرا نام شہزیب علی خان ہے")
        self.assertIn("آپ کا نام شہزیب علی خان ہے", result["reply"])


if __name__ == "__main__":
    unittest.main()
