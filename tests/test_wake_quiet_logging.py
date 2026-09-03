import unittest
from pathlib import Path


class WakeQuietLoggingTests(unittest.TestCase):
    def test_noisy_old_events_are_not_visible(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        visible = cli[
            cli.index("VISIBLE_EVENTS = {"):
            cli.index("}\n\n\ndef event_printer")
        ]
        self.assertNotIn('"WAKE_CANDIDATE_TRANSCRIBED"', visible)
        self.assertNotIn('"WAKE_SPEECH_DETECTED"', visible)
        self.assertNotIn('"WAKE_PHRASE_CAPTURED"', visible)

    def test_useful_wake_and_command_events_remain(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('"WAKE_WORD_DETECTED":"WAKE"', cli)
        self.assertIn('"WAKE_COMMAND_TRANSCRIBED":"WAKE"', cli)


if __name__ == "__main__":
    unittest.main()
