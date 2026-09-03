import unittest
from pathlib import Path


class WakeTtsGuardTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")

    def test_tts_uses_soft_suppression(self):
        self.assertIn(
            'wake.suppress_audio(True, reason="tts")',
            self.cli,
        )
        self.assertIn("stream_kept_open=True", self.cli)

    def test_tts_does_not_hard_suspend_wake(self):
        guard = self.cli[
            self.cli.index("    def wake_tts_guard"):
            self.cli.index("    def terminal_event_printer")
        ]
        self.assertNotIn("wake.suspend(", guard)
        self.assertNotIn("wake.resume()", guard)

    def test_soft_suppression_does_not_touch_hard_pause(self):
        start = self.wake.index("    def suppress_audio(")
        end = self.wake.index(
            "    def _resolve_device(",
            start,
        )
        method = self.wake[start:end]
        self.assertNotIn("self._paused.set()", method)
        self.assertNotIn("self._paused.clear()", method)


if __name__ == "__main__":
    unittest.main()
