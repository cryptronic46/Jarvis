import unittest
from pathlib import Path


class VoiceLearningSecurity0273Tests(unittest.TestCase):
    def test_smart_app_control_prevents_windows_scipy_reinstall(self):
        text = Path("setup_voice_learning.ps1").read_text(encoding="utf-8")
        self.assertIn("0.27.8 - VOICE LEARNING ENVIRONMENT", text)
        self.assertIn("$Policy.smart_app_control_detected", text)
        self.assertIn("usa -Mode WSL", text)


if __name__ == "__main__":
    unittest.main()
