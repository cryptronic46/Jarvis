import unittest
from pathlib import Path
import json


class VoiceContractTests(unittest.TestCase):
    def test_version_is_0193(self):
        text = Path("jarvis_core/__init__.py").read_text(encoding="utf-8")
        self.assertIn("0.27.8", text)

    def test_local_pc_voice_is_retired_but_ptpt_profile_is_preserved(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertFalse(data["local_voice_enabled"])
        self.assertFalse(data["speech_enabled"])
        self.assertEqual(data["speech_voice"], "pt-PT-RaquelNeural")
        self.assertEqual(data["speech_persona_profile"], "velvet_feminine")
        self.assertEqual(data["speech_sapi_prefer_gender"], "Female")

    def test_legacy_voice_handlers_remain_behind_master_guard(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('/voice test', text)
        self.assertIn('/voice feminine', text)
        self.assertIn('speech.say(answer)', text)
        self.assertIn(
            'if not local_voice_enabled and local_voice_command:',
            text,
        )
        self.assertIn('"LOCAL_VOICE_COMMAND_BLOCKED"', text)

    def test_cli_normalizes_settings_schema_before_load(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        main = cli[cli.index("def main() -> None:"):]
        self.assertLess(
            main.index("Settings.ensure_file_schema()"),
            main.index("Settings.load()"),
        )


if __name__ == "__main__":
    unittest.main()
