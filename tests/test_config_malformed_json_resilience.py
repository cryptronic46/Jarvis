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

            # Core safety invariants must hold even when settings.json is bad.
            self.assertEqual(settings.hybrid_mode, "local")
            self.assertFalse(settings.external_ai_enabled)
            self.assertFalse(settings.cloud_enabled)
            self.assertFalse(settings.cloud_fallback_on_local_error)
            self.assertFalse(settings.external_ai_auto_escalate_complex)
            self.assertFalse(settings.expert_escalation_enabled)
            self.assertFalse(settings.performance_cloud_offload_under_pressure)

            # PC-local voice and listening are retired. A corrupt settings
            # file must never resurrect any historical audio subsystem.
            self.assertFalse(settings.local_voice_enabled)
            self.assertFalse(settings.speech_enabled)
            self.assertFalse(settings.speaker_lock_enabled)
            self.assertFalse(settings.wake_enabled)
            self.assertFalse(settings.wake_auto_start)
            self.assertFalse(settings.proactive_speech_enabled)
            self.assertFalse(settings.listening_watchdog_enabled)
            self.assertFalse(settings.voice_v2_preload_stt)


if __name__ == "__main__":
    unittest.main()
