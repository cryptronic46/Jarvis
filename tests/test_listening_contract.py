import json
import unittest
from pathlib import Path


class ListeningContractTests(unittest.TestCase):
    def test_version_is_0193(self):
        self.assertIn(
            "0.27.8",
            Path("jarvis_core/__init__.py").read_text(encoding="utf-8"),
        )

    def test_settings_include_voice_input(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["stt_language"], "pt")
        self.assertEqual(data["stt_model"], "small")
        self.assertEqual(data["stt_device"], "cpu")

    def test_cli_exposes_listen_and_mic_controls(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('/listen', text)
        self.assertIn('/mic list', text)
        self.assertIn('microphone.capture_phrase()', text)
        self.assertIn('microphone.transcribe_command_file(wav_path)', text)


if __name__ == "__main__":
    unittest.main()
