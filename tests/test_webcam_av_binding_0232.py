import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.services.av_devices import webcam_audio_score
from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService
from jarvis_core.skills.builtin.vision import VisionService


class Events:
    def emit(self, *args, **kwargs):
        pass


class WebcamAVBindingTests(unittest.TestCase):
    def fake_sd(self, devices, default_input=0):
        return type(
            "FakeSD",
            (),
            {
                "query_devices": staticmethod(lambda *args, **kwargs: devices if not args else devices[int(args[0])]),
                "query_hostapis": staticmethod(lambda: [{"name": "WASAPI"}]),
                "default": type("D", (), {"device": (default_input, 0)})(),
            },
        )

    def test_webcam_audio_score_prefers_camera_mic(self):
        self.assertGreater(webcam_audio_score("Microphone (HD Pro Webcam C920)"), 1200)
        self.assertLess(webcam_audio_score("Hands-Free (JBL WAVE BEAM)"), 1200)

    def test_microphone_webcam_outranks_legacy_configured_jbl(self):
        devices = [
            {"name": "Hands-Free (JBL WAVE BEAM)", "max_input_channels": 1, "default_samplerate": 16000, "hostapi": 0},
            {"name": "Microphone (HD Pro Webcam C920)", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 0},
        ]
        service = MicrophoneService(
            Events(),
            ListeningConfig(
                device=0,
                preferred_device_name="JBL WAVE BEAM",
                prefer_webcam_audio=True,
            ),
        )
        with patch.dict(sys.modules, {"sounddevice": self.fake_sd(devices)}):
            rows = service._input_device_candidates()
        self.assertEqual(rows[0][0], 1)

    def test_microphone_falls_back_to_jbl_when_webcam_missing(self):
        devices = [
            {"name": "Hands-Free (JBL WAVE BEAM)", "max_input_channels": 1, "default_samplerate": 16000, "hostapi": 0},
            {"name": "Other Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 0},
        ]
        service = MicrophoneService(
            Events(),
            ListeningConfig(preferred_device_name="JBL WAVE BEAM", prefer_webcam_audio=True),
        )
        with patch.dict(sys.modules, {"sounddevice": self.fake_sd(devices)}):
            rows = service._input_device_candidates()
        self.assertEqual(rows[0][0], 0)

    def test_wake_resolver_uses_same_webcam_preference(self):
        devices = [
            {"name": "Hands-Free (JBL WAVE BEAM)", "max_input_channels": 1, "default_samplerate": 16000},
            {"name": "Microphone (USB Webcam)", "max_input_channels": 1, "default_samplerate": 48000},
        ]
        fake_sd = self.fake_sd(devices)
        service = WakeWordService(
            Events(),
            WakeWordConfig(preferred_device_name="JBL WAVE BEAM", prefer_webcam_audio=True),
            on_wake=lambda *args: None,
            transcribe_callback=lambda *args: {},
            cleanup_callback=lambda *args: None,
        )
        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            idx, dev = service._resolve_device()
        self.assertEqual(idx, 1)
        self.assertIn("Webcam", dev["name"])

    def test_vision_camera_candidates_recover_index(self):
        with tempfile.TemporaryDirectory() as td:
            settings = SimpleNamespace(
                vision_model="qwen2.5vl:7b",
                vision_enabled=True,
                vision_camera_enabled=True,
                vision_camera_index=2,
                vision_camera_auto_detect=True,
                vision_camera_probe_limit=4,
                vision_capture_dir=str(Path(td) / "vision"),
            )
            context = SimpleNamespace(settings=settings, services={}, events=Events(), brain=None)
            service = VisionService(context)
            self.assertEqual(service._camera_candidates(), [2, 0, 1, 3])
            service.set_camera_index(1)
            self.assertEqual(service._camera_candidates(), [1, 0, 2, 3])

    def test_cli_contains_owner_av_commands(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for command in ("/av status", "/av auto", "/av microphones", "/av cameras", "/av mic ", "/av camera "):
            self.assertIn(command, text)


if __name__ == "__main__":
    unittest.main()
