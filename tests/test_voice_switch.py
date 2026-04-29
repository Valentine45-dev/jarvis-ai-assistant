"""
Regression tests for voice switch reliability paths.
Run with: uv run python -m unittest discover -s tests -p "test_voice_switch.py"
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.settings import config
from core.audio_pipeline import (
    TtsProviderError,
    TtsProviderErrorKind,
    _classify_elevenlabs_error,
)
from core.voice import voice_engine


class VoiceSwitchTests(unittest.TestCase):
    def test_classify_quota_error(self) -> None:
        exc = RuntimeError(
            "status_code: 401, body: {'detail': {'status': 'quota_exceeded', "
            "'message': 'You have 5 credits remaining'}}"
        )
        err = _classify_elevenlabs_error(exc)
        self.assertEqual(err.kind, TtsProviderErrorKind.QUOTA)
        self.assertIn("quota exceeded", str(err).lower())

    def test_switch_rolls_back_on_provider_failure(self) -> None:
        prev_voice = config.tts_voice
        target_voice = "male-american" if prev_voice != "male-american" else "male-british"
        with patch.object(
            voice_engine._tts,
            "probe_elevenlabs_voice",
            side_effect=TtsProviderError(
                TtsProviderErrorKind.QUOTA,
                "Voice switch failed — ElevenLabs quota exceeded.",
            ),
        ):
            ok, msg, kind = voice_engine.switch_tts_voice(
                target_voice,
                validate_provider=True,
                persist=False,
            )
        self.assertFalse(ok)
        self.assertEqual(kind, "quota")
        self.assertIn("quota exceeded", msg.lower())
        self.assertEqual(config.tts_voice, prev_voice)


if __name__ == "__main__":
    unittest.main()
