import unittest
from pathlib import Path


class VoiceIdModelSetupTests(unittest.TestCase):
    def test_setup_downloads_and_hash_checks_model(self):
        text = Path("setup_voiceid.ps1").read_text(encoding="utf-8")
        self.assertIn("speaker-recognition-models", text)
        self.assertIn("Get-FileHash -Algorithm SHA256", text)
        self.assertIn("8ebcd0b04c1bb50d5fe77166f9a123206bf08ed14bcfd6a0b95fe8fcb2e25926", text)

    def test_setup_does_not_install_speechbrain(self):
        text = Path("setup_voiceid.ps1").read_text(encoding="utf-8").lower()
        self.assertNotIn("speechbrain", text)
        self.assertNotIn("scipy", text)

    def test_doctor_command_exists(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('/voiceid doctor', text)
        self.assertIn("speaker.ensure_ready()", text)


if __name__ == "__main__":
    unittest.main()
