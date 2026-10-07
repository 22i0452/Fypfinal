from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from security_guardrails.audio_retention import cleanup_audio_session


class AudioRetentionModeTests(unittest.TestCase):
    def test_explicit_consent_and_feature_flag_store_playable_wav(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "MEDFLOW_AUDIO_RETENTION_ENABLED": "true",
                "MEDFLOW_AUDIO_RETENTION_DIR": directory,
            },
            clear=False,
        ):
            session = {
                "audio_chunks": [np.zeros(16_000, dtype=np.float32)],
                "input_sample_rate": 16_000,
                "audio_retention_consent": True,
                "audio_retention_requested": True,
                "audio_retention_days": 30,
            }
            result = cleanup_audio_session(
                session,
                patient_ref="PT-SYNTHETIC-AUDIO",
                note_ref="NOTE-SYNTHETIC-AUDIO",
            )

            self.assertEqual(result["state"], "AUDIO_RETENTION_CONSENTED")
            self.assertEqual(session["audio_chunks"], [])
            self.assertTrue((Path(directory) / f"{result['audio_ref']}.wav").is_file())
            self.assertTrue((Path(directory) / f"{result['audio_ref']}.json").is_file())

    def test_failure_cleanup_never_retains_even_when_consent_was_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ",
            {
                "MEDFLOW_AUDIO_RETENTION_ENABLED": "true",
                "MEDFLOW_AUDIO_RETENTION_DIR": directory,
            },
            clear=False,
        ):
            session = {
                "audio_chunks": [np.zeros(8_000, dtype=np.float32)],
                "input_sample_rate": 16_000,
                "audio_retention_consent": True,
                "audio_retention_requested": True,
            }
            result = cleanup_audio_session(
                session,
                patient_ref="PT-SYNTHETIC-AUDIO",
                allow_retention=False,
            )

            self.assertEqual(result["state"], "AUDIO_DELETED")
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
