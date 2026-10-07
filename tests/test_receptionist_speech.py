from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import numpy as np

from receptionist.agent import ReceptionistAgent
from receptionist.audio_recorder import AudioRecorder
from receptionist.stt_module import STTEngine
from tests.test_receptionist_corrections import fill, make_brain


class ReceptionistSpeechTests(unittest.TestCase):
    def setUp(self):
        self.brain = fill(make_brain(language="ur"), 1)
        self.engine = STTEngine.__new__(STTEngine)
        self.audio = (0.02 * np.sin(np.arange(8000) * 2 * np.pi * 220 / 16000)).astype(np.float32)

    def transcribe(self, **kwargs):
        return self.engine.transcribe(
            self.audio, expected_field=self.brain.expected_field(),
            validator=self.brain.accepts_spoken_turn, **kwargs,
        )

    def test_urdu_age_uses_language_hint_without_a_sample_age_or_identity(self):
        with patch.object(self.engine, "_transcribe_approved", return_value="پینتیس سال") as call:
            result = self.transcribe(language_hint="ur")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.kwargs["language"], "ur")
        prompt = call.call_args.kwargs["prompt"]
        self.assertIn("عمر", prompt)
        self.assertNotRegex(prompt, r"[A-Za-z0-9]")
        self.assertNotIn("Synthetic", prompt)
        self.brain.get_response(result)
        self.assertEqual(self.brain.local_intake_data()["عمر"], "35")
        self.assertEqual(self.brain.expected_field(), "phone_number")

    def test_unrelated_short_words_retry_the_same_recording(self):
        for garbage in ("Tentacle", "Cheers!", "Thank you"):
            with self.subTest(garbage=garbage), patch.object(
                self.engine, "_transcribe_approved", side_effect=[garbage, "چالیس سال"]
            ) as call:
                result = self.transcribe(language_hint="ur")
                self.assertEqual(result, "چالیس سال")
                self.assertEqual(call.call_count, 2)
                self.assertEqual(call.call_args_list[0].kwargs["language"], "ur")
                self.assertIsNone(call.call_args_list[1].kwargs["language"])
                self.assertEqual(call.call_args_list[0].args[0], call.call_args_list[1].args[0])

    def test_two_implausible_attempts_do_not_become_an_age(self):
        with patch.object(self.engine, "_transcribe_approved", side_effect=["Tentacle", "Cheers!"]) as call:
            result = self.transcribe(language_hint="ur")
        self.assertEqual(result, "")
        self.assertEqual(call.call_count, 2)
        self.assertNotIn("عمر", self.brain.local_intake_data())

    def test_english_hint_and_language_switch_are_supported(self):
        with patch.object(self.engine, "_transcribe_approved", return_value="twenty four") as call:
            self.assertEqual(self.transcribe(language_hint="en"), "twenty four")
        self.assertEqual(call.call_args.kwargs["language"], "en")
        with patch.object(self.engine, "_transcribe_approved", side_effect=["Tentacle", "I am twenty four"]):
            result = self.transcribe(language_hint="ur")
        self.brain.get_response(result)
        self.assertEqual(self.brain.local_intake_data()["عمر"], "24")
        self.assertEqual(self.brain.language, "en")

    def test_corrections_and_uncertainty_are_not_discarded_as_non_numeric(self):
        for phrase in (
            "My name was wrong", "میں مذاق کر رہا تھا", "Mera naam ghalat tha",
            "I don't know", "not 35", "maybe thirty five", "no more corrections",
            "start over", "نہیں", "Actually my name is different",
        ):
            with self.subTest(phrase=phrase), patch.object(
                self.engine, "_transcribe_approved", return_value=phrase
            ):
                self.assertEqual(self.transcribe(language_hint="ur"), phrase)
        self.assertFalse(self.brain.valid_answer("age", "not 35"))

    def test_prompt_echo_retries_without_prompt(self):
        def respond(_audio, *, prompt, language):
            return prompt if prompt else "پچیس"

        with patch.object(self.engine, "_transcribe_approved", side_effect=respond) as call:
            self.assertEqual(self.transcribe(language_hint="ur"), "پچیس")
        self.assertEqual(call.call_count, 2)
        self.assertIsNone(call.call_args.kwargs["prompt"])

    def test_silence_empty_and_invalid_audio_do_not_reach_provider(self):
        for audio in (
            np.array([], dtype=np.float32), np.zeros(8000, dtype=np.float32),
            np.full(8000, 0.02, dtype=np.float32),
            np.array([np.nan], dtype=np.float32), np.array([np.inf], dtype=np.float32),
        ):
            with self.subTest(size=audio.size), patch.object(self.engine, "_transcribe_approved") as call:
                self.assertEqual(self.engine.transcribe(audio), "")
                call.assert_not_called()

    def test_provider_exception_does_not_leak_transcript_or_credentials(self):
        output = io.StringIO()
        with patch("receptionist.stt_module.get_gateway", side_effect=RuntimeError("synthetic-secret-and-transcript")), redirect_stdout(output):
            self.assertEqual(self.engine._transcribe_approved(b"synthetic", None), "")
        self.assertNotIn("synthetic-secret-and-transcript", output.getvalue())

    def test_agent_passes_current_language_and_enables_short_age_capture(self):
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
        agent.llm = self.brain
        agent.recorder = Mock()
        agent.recorder.record.side_effect = [self.audio, KeyboardInterrupt]
        agent.stt = Mock()
        agent.stt.transcribe.return_value = "پینتیس سال"
        agent.tts = Mock()
        agent._forward_requested = threading.Event()
        agent._turn_in_progress = threading.Event()
        agent._cb = {"status": Mock(), "summary_ready": Mock()}
        agent.run()
        self.assertTrue(agent.recorder.record.call_args_list[0].kwargs["short_response"])
        self.assertEqual(agent.stt.transcribe.call_args.kwargs["language_hint"], "ur")
        self.assertEqual(agent.stt.transcribe.call_args.kwargs["expected_field"], "age")
        self.assertEqual(agent.llm.local_intake_data()["عمر"], "35")


class ReceptionistCaptureTests(unittest.TestCase):
    def stream(self, chunks):
        stream = Mock()
        stream.__enter__ = Mock(return_value=stream)
        stream.__exit__ = Mock(return_value=False)
        stream.read.side_effect = chunks
        return stream

    def test_quiet_short_age_keeps_initial_audio_and_waits_for_silence(self):
        recorder = AudioRecorder()
        recorder._max_chunks = 10
        recorder._silence_limit = 2
        onset = np.full((1600, 1), 0.002, dtype=np.float32)
        voice = np.full((1600, 1), 0.005, dtype=np.float32)
        silence = np.zeros((1600, 1), dtype=np.float32)
        stream = self.stream([(onset, False), (voice, False), (silence, False), (silence, False)])
        with patch("receptionist.audio_recorder.sd.InputStream", return_value=stream):
            audio = recorder.record(short_response=True)
        self.assertIsNotNone(audio)
        np.testing.assert_array_equal(audio[:1600], onset.flatten())
        self.assertEqual(stream.read.call_count, 4)

    def test_wait_for_speech_is_bounded(self):
        recorder = AudioRecorder()
        recorder._max_chunks = 3
        silence = np.zeros((1600, 1), dtype=np.float32)
        stream = self.stream([(silence, False)] * 3)
        with patch("receptionist.audio_recorder.sd.InputStream", return_value=stream):
            self.assertIsNone(recorder.record(short_response=True))
        self.assertEqual(stream.read.call_count, 3)

    def test_capture_overflow_discards_incomplete_audio(self):
        stream = self.stream([(np.ones((1600, 1), dtype=np.float32), True)])
        with patch("receptionist.audio_recorder.sd.InputStream", return_value=stream):
            self.assertIsNone(AudioRecorder().record(short_response=True))


if __name__ == "__main__":
    unittest.main()
