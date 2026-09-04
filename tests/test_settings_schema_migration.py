import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings


class SettingsSchemaMigrationTests(unittest.TestCase):
    def test_missing_fields_are_added_without_overwriting_user_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({
                    "user_name": "Owner",
                    "speech_enabled": False,
                }),
                encoding="utf-8",
            )

            result = Settings.ensure_file_schema(path)
            data = json.loads(
                path.read_text(encoding="utf-8")
            )

            self.assertTrue(result["ok"])
            self.assertGreater(
                result["added_count"],
                0,
            )
            self.assertEqual(
                data["user_name"],
                "Owner",
            )
            self.assertFalse(
                data["speech_enabled"]
            )
            self.assertIn(
                "personal_learning_enabled",
                data,
            )
            self.assertIn(
                "proactive_enabled",
                data,
            )
            self.assertIn(
                "proactive_quiet_start_hour",
                data,
            )


    def test_legacy_default_voice_is_migrated_to_feminine_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({
                    "speech_voice": "pt-PT-DuarteNeural",
                    "speech_rate": "-7%",
                    "speech_pitch": "-16Hz",
                }),
                encoding="utf-8",
            )
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["speech_voice"], "pt-PT-RaquelNeural")
            self.assertEqual(data["speech_rate"], "-9%")
            self.assertEqual(data["speech_pitch"], "-8Hz")
            self.assertEqual(data["speech_persona_profile"], "velvet_feminine")
            self.assertEqual(result["voice_migrated_count"], 3)

    def test_custom_voice_is_not_overwritten_by_schema_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({
                    "speech_voice": "pt-PT-FernandaNeural",
                    "speech_rate": "+2%",
                    "speech_pitch": "+1Hz",
                }),
                encoding="utf-8",
            )
            Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["speech_voice"], "pt-PT-FernandaNeural")
            self.assertEqual(data["speech_rate"], "+2%")
            self.assertEqual(data["speech_pitch"], "+1Hz")

    def test_mojibake_stt_guidance_is_repaired_without_touching_other_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({
                    "user_name": "Owner",
                    "wake_stt_initial_prompt": "TranscriÃ§Ã£o fiel em portuguÃªs.",
                    "wake_stt_hotwords": "Jarvis Ã¡udio grÃ¡fica",
                }),
                encoding="utf-8",
            )
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["user_name"], "Owner")
            self.assertEqual(
                data["wake_stt_initial_prompt"],
                "Transcrição fiel em português.",
            )
            self.assertEqual(data["wake_stt_hotwords"], "Jarvis áudio gráfica")
            self.assertEqual(result["encoding_migrated_count"], 2)
    def test_current_release_settings_has_complete_schema(self):
        data = json.loads(
            Path("settings.json").read_text(
                encoding="utf-8"
            )
        )
        expected = set(
            Settings.__dataclass_fields__
        )
        self.assertEqual(
            expected - set(data),
            set(),
        )

    def test_utf8_bom_settings_are_accepted_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({
                    "user_name": "Owner",
                    "speech_enabled": False,
                }),
                encoding="utf-8-sig",
            )

            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            result = Settings.ensure_file_schema(path)
            loaded = Settings.load(path)

            self.assertTrue(result["ok"])
            self.assertTrue(result["utf8_bom_normalized"])
            self.assertFalse(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            self.assertEqual(loaded.user_name, "Owner")
            self.assertFalse(loaded.speech_enabled)

    def test_update_file_values_accepts_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"speech_enabled": True}),
                encoding="utf-8-sig",
            )
            result = Settings.update_file_values(
                {"speech_enabled": False},
                path,
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["changed_count"], 1)
            self.assertFalse(Settings.load(path).speech_enabled)


if __name__ == "__main__":
    unittest.main()
