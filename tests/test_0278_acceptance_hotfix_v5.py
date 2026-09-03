import unittest
from pathlib import Path


class AcceptanceHotfixV5Tests(unittest.TestCase):
    def test_setup_vision_settings_update_uses_temp_python_file(self):
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("jarvis_vision_settings_", text)
        self.assertIn("WriteAllText($SettingsHelper", text)
        self.assertIn("& $Python $SettingsHelper", text)
        self.assertIn("Remove-Item -LiteralPath $SettingsHelper", text)
        self.assertNotIn("& $Python -c $SettingsCode", text)

    def test_direct_url_returns_local_synthesis_before_learning_note(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('final_answer = str(result.text or "").strip()', text)
        self.assertIn('print(f"\\nJARVIS > {final_answer}\\n")', text)
        self.assertIn('speech.say(final_answer)', text)
        self.assertIn('learning_note = (', text)

    def test_cli_has_no_literal_backslash_n_jarvis_wrappers(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertNotIn('f"\\\\nJARVIS >', text)


if __name__ == "__main__":
    unittest.main()
