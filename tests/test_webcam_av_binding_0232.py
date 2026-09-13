import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.services.av_devices import webcam_audio_score
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



if __name__ == "__main__":
    unittest.main()
