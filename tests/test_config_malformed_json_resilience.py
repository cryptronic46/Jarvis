import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings


class MalformedSettingsJsonResilienceTests(unittest.TestCase):
    def _broken_settings(self, root: Path) -> Path:
        path = root / "settings.json"
        path.write_bytes(
            b'{"user_name":"OWNER","speech_enabled":true,'
        )
        return path

    def test_ensure_file_schema_fails_closed_without_overwriting_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._broken_settings(Path(td))
            before = path.read_bytes()

            result = Settings.ensure_file_schema(path)

            self.assertFalse(result["ok"])
            self.assertEqual(
                result["error"],
                "SETTINGS_JSON_INVALID",
            )
            self.assertEqual(path.read_bytes(), before)

    def test_update_file_values_fails_closed_without_overwriting_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._broken_settings(Path(td))
            before = path.read_bytes()

            result = Settings.update_file_values(
                {"user_name": "NEW_OWNER"},
                path,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(
                result["error"],
                "SETTINGS_JSON_INVALID",
            )
            self.assertEqual(path.read_bytes(), before)


    def test_load_uses_safe_defaults_without_modifying_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._broken_settings(Path(td))
            before = path.read_bytes()

            settings = Settings.load(path)

            self.assertIsInstance(settings, Settings)
            self.assertEqual(path.read_bytes(), before)

            self.assertEqual(settings.hybrid_mode, "local")
            self.assertFalse(settings.external_ai_enabled)
            self.assertFalse(settings.cloud_enabled)
            self.assertFalse(settings.cloud_fallback_on_local_error)
            self.assertFalse(
                settings.external_ai_auto_escalate_complex
            )
            self.assertFalse(settings.expert_escalation_enabled)
            self.assertFalse(
                settings.performance_cloud_offload_under_pressure
            )

            self.assertFalse(settings.local_voice_enabled)


if __name__ == "__main__":
    unittest.main()
