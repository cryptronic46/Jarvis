import unittest
from pathlib import Path


class WakeWhisperAfterOnlyTests(unittest.TestCase):
    def setUp(self):
        self.wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

    def test_transcription_happens_only_in_command_method(self):
        # The callback invocation should live in _transcribe_command, not in
        # the idle acoustic matcher.
        match_start = self.wake.index("    def _match_probe(")
        match_end = self.wake.index(
            "    def _save_command_wav(",
            match_start,
        )
        match_code = self.wake[match_start:match_end]
        self.assertNotIn("transcribe_callback", match_code)

        cmd_start = self.wake.index("    def _transcribe_command(")
        cmd_end = self.wake.index("    def doctor(", cmd_start)
        command_code = self.wake[cmd_start:cmd_end]
        self.assertIn("self.transcribe_callback(", command_code)

    def test_unmatched_speech_is_discarded_without_whisper(self):
        stream_start = self.wake.index("    def _listen_persistent_stream(")
        stream_end = self.wake.index("    def _run(", stream_start)
        stream = self.wake[stream_start:stream_end]
        self.assertIn("if matched:", stream)
        self.assertIn("_transcribe_command(", stream)

    def test_cli_has_enrollment_commands(self):
        self.assertIn('if lower == "/wake enroll":', self.cli)
        self.assertIn('if lower == "/wake delete":', self.cli)

    def test_auto_start_requires_enrolled_profile(self):
        self.assertIn("and wake.enrolled()", self.cli)


if __name__ == "__main__":
    unittest.main()
