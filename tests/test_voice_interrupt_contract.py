import unittest
from pathlib import Path


class VoiceInterruptContractTests(unittest.TestCase):
    def setUp(self):
        self.wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.speech = Path(
            "jarvis_core/services/speech.py"
        ).read_text(encoding="utf-8")

    def test_separate_profile(self):
        self.assertIn("interrupt_template_path", self.wake)
        self.assertIn("enroll_interrupt", self.wake)
        self.assertIn("_match_interrupt_probe", self.wake)

    def test_tts_interrupt_uses_bargein_v2_and_whisper(self):
        self.assertIn("VOICE_INTERRUPT_DETECTED", self.wake)
        self.assertIn(
            "_transcribe_interrupt_candidate",
            self.wake,
        )
        self.assertIn(
            "_interrupt_transcript_confirmed",
            self.wake,
        )
        self.assertIn(
            'confirmation="bargein-v2+whisper"',
            self.wake,
        )
        self.assertIn("self.on_interrupt()", self.wake)

    def test_false_candidate_can_pause_and_resume_edge(self):
        self.assertIn(
            "def pause_for_bargein",
            self.speech,
        )
        self.assertIn(
            "def resume_after_bargein",
            self.speech,
        )
        self.assertIn(
            "on_interrupt_probe_start=on_interrupt_probe_start",
            self.cli,
        )
        self.assertIn(
            "on_interrupt_probe_end=on_interrupt_probe_end",
            self.cli,
        )

    def test_callback_stops_tts(self):
        block = self.cli[
            self.cli.index("    def on_interrupt()"):
            self.cli.index("    legacy_wake = WakeWordService(")
        ]
        self.assertIn(
            "speech.stop(clear_queue=True)",
            block,
        )

    def test_commands(self):
        self.assertIn(
            'if lower == "/interrupt enroll":',
            self.cli,
        )
        self.assertIn(
            'if lower == "/interrupt status":',
            self.cli,
        )


if __name__ == "__main__":
    unittest.main()
