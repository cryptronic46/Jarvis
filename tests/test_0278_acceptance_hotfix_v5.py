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

    def test_direct_external_learning_exposes_local_synthesis_after_validated_store(self):
        text = Path(
            "jarvis_core/services/external_learning.py"
        ).read_text(
            encoding="utf-8"
        )

        start = text.index(
            "def execute_authorized_external_learning("
        )

        block = text[
            start:
        ]

        store = block.index(
            "stored = authorized_learning().add("
        )

        rejection = block.index(
            'not stored.get("ok")',
            store,
        )

        summary = block.rindex(
            '"summary": str('
        )

        self.assertLess(
            store,
            rejection,
        )

        self.assertLess(
            rejection,
            summary,
        )

        self.assertIn(
            "result.text",
            block[
                summary:
            ],
        )

        self.assertNotIn(
            "cloud_brain.ask(",
            block,
        )

    def test_cli_has_no_literal_backslash_n_jarvis_wrappers(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertNotIn('f"\\\\nJARVIS >', text)


if __name__ == "__main__":
    unittest.main()
