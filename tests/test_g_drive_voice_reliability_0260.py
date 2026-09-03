from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.core.config import Settings
from jarvis_core.services.desktop_integration import DesktopIntegrationService
from jarvis_core.services.listening import _windows_hostapi_score
from jarvis_core.services.speech import SpeechConfig, SpeechService
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config
from jarvis_core.services.wakeword import _windows_capture_hostapi_score


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class FakeModel:
    last_kwargs = None

    def __init__(self, **kwargs):
        FakeModel.last_kwargs = dict(kwargs)
        self.models = {}
        self.model_inputs = {}
        self.prediction_buffer = {}


class FakeVad:
    def __init__(self, n_threads=1):
        self.n_threads = n_threads


class GDriveVoiceReliability0260Tests(unittest.TestCase):
    def test_voice_v2_forces_onnx_even_when_model_signature_is_wrapped(self):
        events = DummyEvents()
        svc = VoiceEngineV2(
            events,
            VoiceV2Config(wake_vad_threshold=0.57),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": False},
        )
        fake_pa = types.ModuleType("pyaudiowpatch")
        with patch.dict(sys.modules, {"pyaudiowpatch": fake_pa}), patch(
            "jarvis_core.services.voice_engine_v2.openwakeword_runtime_classes",
            return_value=(FakeModel, FakeVad),
        ):
            svc._load_runtime()
        self.assertEqual("onnx", FakeModel.last_kwargs["inference_framework"])
        self.assertEqual(["hey_jarvis"], FakeModel.last_kwargs["wakeword_models"])
        self.assertAlmostEqual(0.0, FakeModel.last_kwargs["vad_threshold"])
        self.assertTrue(any(name == "VOICE_V2_RUNTIME_READY" for name, _ in events.rows))

    def test_bargein_waits_until_mci_playback_is_ready(self):
        events = DummyEvents()
        svc = SpeechService(events, SpeechConfig(cache_enabled=False))
        svc._speaking = True
        svc._active_alias = "jarvis_test"
        calls = []

        def fake_mci(command, return_chars=0):
            calls.append(command)
            if command.startswith("status "):
                return "playing"
            return ""

        svc._mci = fake_mci
        self.assertFalse(svc.pause_for_bargein())
        self.assertEqual([], calls)
        svc._playback_ready.set()
        self.assertTrue(svc.pause_for_bargein())
        self.assertIn("status jarvis_test mode", calls)
        self.assertIn("pause jarvis_test", calls)

    def test_legacy_capture_strongly_deprioritizes_wdm_ks(self):
        self.assertGreater(_windows_hostapi_score("Windows WASAPI"), 0)
        self.assertLessEqual(_windows_hostapi_score("Windows WDM-KS"), -1000)
        self.assertGreater(_windows_capture_hostapi_score("Windows WASAPI"), 0)
        self.assertLessEqual(_windows_capture_hostapi_score("Windows WDM-KS"), -1000)

    def test_wallpaper_default_is_sibling_of_core(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            core = base / "JARVIS"
            core.mkdir()
            svc = DesktopIntegrationService(
                DummyEvents(),
                core_root=core,
                wallpaper_root="",
                bridge_auto_start=False,
                wallpaper_engine_auto_start=False,
            )
            self.assertEqual((base / "JARVIS-Wallpaper").resolve(), svc.wallpaper_root.resolve())

    def test_settings_migrate_old_storage_and_add_v2_keys(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "desktop_wallpaper_root": r"C:\JARVIS-Wallpaper",
                        "voice_v2_wake_threshold": 0.55,
                        "wake_match_floor": 0.62,
                        "wake_candidate_min_avg_logprob": -0.80,
                        "wake_candidate_max_no_speech_prob": 0.35,
                    }
                ),
                encoding="utf-8",
            )
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("", data["desktop_wallpaper_root"])
            self.assertGreaterEqual(data["voice_v2_wake_threshold"], 0.40)
            for key in (
                "voice_v2_wake_strong_threshold",
                "voice_v2_wake_confirm_frames",
                "voice_v2_wake_confirm_window_seconds",
                "voice_v2_verifier_path",
                "voice_v2_verifier_threshold",
            ):
                self.assertIn(key, data)
            self.assertIn("desktop_wallpaper_root", result["storage_migrated"])

    def test_g_migration_does_not_copy_old_venv(self):
        text = Path("migrate_to_g.ps1").read_text(encoding="utf-8")
        self.assertIn('Destination = "G:\\JARVIS"', text)
        self.assertIn('WallpaperDestination = "G:\\JARVIS-Wallpaper"', text)
        self.assertIn("Old .venv intentionally not copied", text)
        self.assertNotIn(r"'\.venv'", text.split("foreach ($name in @(", 1)[1].split("))", 1)[0])

    def test_app_control_doctor_uses_existing_auditor(self):
        text = Path("diagnose_app_control.ps1").read_text(encoding="utf-8")
        self.assertIn("windows_block_audit", text)
        self.assertNotIn("app_control_policy", text)

    def test_voice_learning_auto_mode_uses_existing_block_auditor(self):
        text = Path("setup_voice_learning.ps1").read_text(encoding="utf-8")
        self.assertIn("windows_block_audit", text)
        self.assertNotIn("app_control_policy", text)

    def test_bundled_wallpaper_defaults_to_g_drive(self):
        install = Path("JARVIS_Live_Wallpaper_0.1.0/install.ps1").read_text(encoding="utf-8")
        start = Path("JARVIS_Live_Wallpaper_0.1.0/start_bridge.ps1").read_text(encoding="utf-8")
        bridge = Path("JARVIS_Live_Wallpaper_0.1.0/bridge/jarvis_bridge.py").read_text(encoding="utf-8")
        self.assertIn(r"G:\JARVIS-Wallpaper", install)
        self.assertIn(r"G:\JARVIS", start)
        self.assertIn(r"G:\JARVIS", bridge)

    def test_faster_whisper_cache_is_local(self):
        config = Settings()
        self.assertEqual("models/faster-whisper", config.stt_download_root)
        listening = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn('kwargs["download_root"] = download_root', listening)
        setup = Path("setup_voice_reset.ps1").read_text(encoding="utf-8")
        self.assertIn("models/faster-whisper", setup)


if __name__ == "__main__":
    unittest.main()
