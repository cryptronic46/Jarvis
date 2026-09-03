import unittest
from pathlib import Path

from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class WakeSoftSuppressionTests(unittest.TestCase):
    def make_service(self):
        return WakeWordService(
            DummyEvents(),
            WakeWordConfig(tts_tail_seconds=0.01),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": True, "text": "Jarvis"},
        )

    def test_suppress_and_release(self):
        wake = self.make_service()
        wake.suppress_audio(True, reason="tts")
        self.assertTrue(wake._audio_is_suppressed())
        self.assertFalse(wake._paused.is_set())

        wake.suppress_audio(False, reason="tts", tail_seconds=0.0)
        self.assertFalse(wake._audio_is_suppressed())
        self.assertFalse(wake._paused.is_set())

    def test_stream_callback_keeps_running_during_suppression(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        method = text[
            text.index("    def _listen_persistent_stream("):
            text.index("    def _run(", text.index("    def _listen_persistent_stream("))
        ]
        self.assertIn("if self._audio_is_suppressed():", method)
        self.assertIn("continue", method)
        self.assertNotIn("suspend(", method)


if __name__ == "__main__":
    unittest.main()
