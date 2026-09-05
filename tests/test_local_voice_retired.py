import json
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.cli import help_text


ROOT = Path(__file__).resolve().parents[1]


class LocalVoiceRetiredTests(unittest.TestCase):
    def test_master_switch_defaults_to_off(self):
        settings = Settings()
        self.assertFalse(settings.local_voice_enabled)

    def test_persisted_local_audio_is_off_but_vision_remains_on(self):
        data = json.loads(
            (ROOT / "settings.json").read_text(encoding="utf-8")
        )

        for key in (
            "local_voice_enabled",
            "speech_enabled",
            "speaker_lock_enabled",
            "wake_enabled",
            "wake_auto_start",
            "proactive_speech_enabled",
            "listening_watchdog_enabled",
            "voice_v2_preload_stt",
        ):
            with self.subTest(key=key):
                self.assertIs(data.get(key), False)

        self.assertIs(data.get("vision_enabled"), True)
        self.assertIs(data.get("vision_camera_enabled"), True)

    def test_schema_normalization_cannot_resurrect_local_voice(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            data = json.loads(
                (ROOT / "settings.json").read_text(encoding="utf-8")
            )

            for key in (
                "local_voice_enabled",
                "speech_enabled",
                "speaker_lock_enabled",
                "wake_enabled",
                "wake_auto_start",
                "proactive_speech_enabled",
                "listening_watchdog_enabled",
                "voice_v2_preload_stt",
            ):
                data[key] = True

            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            Settings.ensure_file_schema(path)

            repaired = json.loads(
                path.read_text(encoding="utf-8")
            )

            for key in (
                "local_voice_enabled",
                "speech_enabled",
                "speaker_lock_enabled",
                "wake_enabled",
                "wake_auto_start",
                "proactive_speech_enabled",
                "listening_watchdog_enabled",
                "voice_v2_preload_stt",
            ):
                with self.subTest(key=key):
                    self.assertIs(repaired.get(key), False)

    def test_help_hides_retired_audio_commands(self):
        text = help_text()

        retired = (
            "/voice ",
            "/mic ",
            "/listen ",
            "/listening ",
            "/stt ",
            "/wake ",
            "/voiceid ",
            "/interrupt ",
            "/av status",
            "/av auto",
            "/av microphones",
            "/av probe",
            "/av mic ",
            "/av webcam ",
            "/mind speech ",
        )

        for command in retired:
            with self.subTest(command=command):
                self.assertNotIn(command, text)

        self.assertIn("/av cameras", text)
        self.assertIn("/av camera N", text)
        self.assertIn("/warmup", text)
        self.assertIn("modelo local Qwen", text)

    def test_runtime_startups_are_guarded_by_master_switch(self):
        source = (
            ROOT / "jarvis_core" / "cli.py"
        ).read_text(encoding="utf-8")

        required = (
            "if not local_voice_enabled:",
            "settings.speech_enabled = False",
            "settings.wake_enabled = False",
            "settings.wake_auto_start = False",
            "settings.listening_watchdog_enabled = False",
            "settings.speaker_lock_enabled = False",
            "settings.proactive_speech_enabled = False",
            "settings.voice_v2_preload_stt = False",
            "if local_voice_enabled:\n        speech.start()",
            "if local_voice_enabled:\n        listening_watchdog.start()",
            'events.emit("LOCAL_VOICE_DISABLED")',
        )

        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source)

    def test_retired_voice_commands_are_blocked_before_handlers(self):
        source = (
            ROOT / "jarvis_core" / "cli.py"
        ).read_text(encoding="utf-8")

        guard = 'if not local_voice_enabled and local_voice_command:'
        event = '"LOCAL_VOICE_COMMAND_BLOCKED"'
        help_handler = 'if lower == "/help":'
        voice_handler = 'if lower == "/voice status":'

        self.assertIn(guard, source)
        self.assertIn(event, source)
        self.assertIn(help_handler, source)
        self.assertIn(voice_handler, source)

        self.assertLess(source.index(guard), source.index(help_handler))
        self.assertLess(source.index(guard), source.index(voice_handler))


if __name__ == "__main__":
    unittest.main()
