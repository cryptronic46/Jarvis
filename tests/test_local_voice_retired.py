import json
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.cli import help_text, help_text_full


ROOT = Path(__file__).resolve().parents[1]


class LocalVoiceRetiredTests(unittest.TestCase):
    def test_master_switch_defaults_to_off(self):
        settings = Settings()
        self.assertFalse(settings.local_voice_enabled)


    def test_persisted_local_audio_is_off_but_vision_remains_on(self):
        data = json.loads(
            (ROOT / "settings.json").read_text(encoding="utf-8")
        )

        self.assertIs(data.get("local_voice_enabled"), False)

        retired_prefixes = (
            "voice_v2_",
            "listening_watchdog_",
            "wake_",
            "stt_",
            "mic_",
            "speech_",
            "speaker_",
            "interrupt_",
        )

        for key in data:
            with self.subTest(key=key):
                self.assertFalse(
                    key == "voice_input_backend"
                    or key.startswith(retired_prefixes)
                )

        self.assertIs(data.get("vision_enabled"), True)
        self.assertIs(data.get("vision_camera_enabled"), True)


    def test_schema_normalization_cannot_resurrect_local_voice(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"

            data = json.loads(
                (ROOT / "settings.json").read_text(
                    encoding="utf-8"
                )
            )

            legacy = {
                "speech_enabled": True,
                "speaker_lock_enabled": True,
                "wake_enabled": True,
                "wake_auto_start": True,
                "listening_watchdog_enabled": True,
                "voice_v2_preload_stt": True,
                "mic_device": 23,
                "stt_device": "cpu",
            }

            data.update(legacy)
            data["local_voice_enabled"] = True

            path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
                encoding="utf-8",
            )

            Settings.ensure_file_schema(path)

            repaired = json.loads(
                path.read_text(encoding="utf-8")
            )

            self.assertIs(
                repaired.get("local_voice_enabled"),
                False,
            )

            for key in legacy:
                with self.subTest(key=key):
                    self.assertNotIn(key, repaired)

    def test_cli_import_does_not_load_real_voice_stack(self):
        import subprocess
        import sys

        code = r"""
import sys
import jarvis_core.cli

forbidden = (
    "jarvis_core.services.speech",
    "jarvis_core.services.listening",
    "jarvis_core.services.av_devices",
    "jarvis_core.services.speaker_verification",
    "jarvis_core.services.wakeword",
    "jarvis_core.services.voice_engine_v2",
    "jarvis_core.services.voice_pipeline",
    "jarvis_core.services.listening_watchdog",
)

loaded = [
    name
    for name in forbidden
    if name in sys.modules
]

if loaded:
    raise SystemExit(
        "real voice modules loaded: " + ", ".join(loaded)
    )
"""

        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=result.stdout + result.stderr,
        )

    def test_help_hides_retired_audio_commands(self):
        compact = help_text()
        full = help_text_full()

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
                self.assertNotIn(command, compact)
                self.assertNotIn(command, full)

        self.assertIn("/help all", compact)
        self.assertNotIn("/av cameras", compact)

        self.assertIn("/av cameras", full)
        self.assertIn("/av camera N", full)
        self.assertIn("/warmup", full)
        self.assertIn("modelo local Qwen", full)


    def test_retired_voice_runtime_shell_is_physically_removed(self):
        source = (
            ROOT / "jarvis_core" / "cli.py"
        ).read_text(encoding="utf-8")

        forbidden = (
            "from jarvis_core.services.disabled_voice import",
            "DisabledSpeechService",
            "DisabledMicrophoneService",
            "DisabledSpeakerVerifier",
            "DisabledWakeService",
            "DisabledListeningWatchdog",
            "local_voice_enabled",
            "speech.start()",
            "speech.say(",
            "speech.stop(",
            "speech.shutdown()",
            "microphone.preload_stt()",
            "microphone.release_stt()",
            "speaker.ensure_ready()",
            "speaker.set_enabled(False)",
            "wake.start()",
            "wake.stop()",
            "listening_watchdog.start()",
            "listening_watchdog.stop()",
            "voice_engine_state",
        )

        for fragment in forbidden:
            with self.subTest(fragment=fragment):
                self.assertNotIn(
                    fragment,
                    source,
                )

        self.assertIn(
            'if lower == "/warmup":',
            source,
        )
        self.assertIn(
            '"llm": brain.warmup()',
            source,
        )
        self.assertIn(
            "silence_latch.latch(",
            source,
        )

    def test_retired_voice_command_surface_is_physically_removed(self):
        source = (
            ROOT / "jarvis_core" / "cli.py"
        ).read_text(encoding="utf-8")

        forbidden_handlers = (
            'if lower == "/voice status":',
            'if lower == "/voice test":',
            'if lower == "/stt test":',
            'if lower == "/mic status":',
            'if lower == "/listening status":',
            'if lower == "/wake status":',
            'if lower == "/wake on":',
            'if lower == "/voiceid status":',
            'if lower == "/interrupt enroll":',
            'if lower in {"/listen", "/ptt"}:',
            'if lower == "/mind speech on":',
        )

        for fragment in forbidden_handlers:
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

        self.assertNotIn(
            "local_voice_command",
            source,
        )

        self.assertNotIn(
            "LOCAL_VOICE_COMMAND_BLOCKED",
            source,
        )

        self.assertIn(
            'if lower == "/av cameras":',
            source,
        )

        self.assertIn(
            'if lower.startswith("/av camera "):',
            source,
        )

if __name__ == "__main__":
    unittest.main()
