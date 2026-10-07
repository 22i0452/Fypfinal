from __future__ import annotations

import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from receptionist.tts_module import TTSEngine


class _HangingCommunicate:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def save(self, _path: str) -> None:
        await asyncio.sleep(1)


class TTSResilienceTests(unittest.TestCase):
    def test_doctor_shaimaan_name_is_expanded_for_urdu_speech(self) -> None:
        spoken = TTSEngine._normalize_speech_text(
            "آپ کی ملاقات Dr.Shaimaan کے ساتھ ہے۔"
        )

        self.assertIn("ڈاکٹر شیمان", spoken)
        self.assertNotIn("Dr.", spoken)

    def test_long_structured_summary_is_split_into_bounded_chunks(self) -> None:
        text = "Synthetic summary\n" + "\n".join(
            f"Field {index}: synthetic value with enough detail for speech."
            for index in range(1, 16)
        )

        chunks = TTSEngine._speech_chunks(text, max_chars=120)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(0 < len(chunk) <= 120 for chunk in chunks))
        self.assertEqual(
            " ".join(text.split()),
            " ".join("\n".join(chunks).split()),
        )

    def test_edge_synthesis_timeout_returns_without_playback(self) -> None:
        engine = TTSEngine.__new__(TTSEngine)
        fake_edge_tts = SimpleNamespace(Communicate=_HangingCommunicate)

        with (
            patch.dict(sys.modules, {"edge_tts": fake_edge_tts}),
            patch("receptionist.tts_module._EDGE_SYNTHESIS_TIMEOUT_SECONDS", 0.01),
            patch.object(engine, "_play_mp3_file") as playback,
        ):
            result = engine._speak_edge_chunk("Synthetic timeout text")

        self.assertFalse(result)
        playback.assert_not_called()

    def test_later_chunks_are_not_attempted_after_synthesis_failure(self) -> None:
        engine = TTSEngine.__new__(TTSEngine)

        with (
            patch.object(
                engine,
                "_speech_chunks",
                return_value=["Synthetic first", "Synthetic second", "Synthetic third"],
            ),
            patch.object(engine, "_speak_edge_chunk", side_effect=(True, False)) as speak,
        ):
            result = engine._speak_edge_tts("Synthetic summary")

        self.assertFalse(result)
        self.assertEqual(speak.call_count, 2)
