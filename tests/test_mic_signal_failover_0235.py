import unittest
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class MicSignalFailover0235Tests(unittest.TestCase):
    def test_capture_skips_open_endpoint_that_returns_digital_silence(self):
        events = DummyEvents()
        service = MicrophoneService(events, ListeningConfig(device=None))
        candidates = [
            (5, {"name": "Webcam Mic", "_hostapi_name": "Windows WDM-KS"}),
            (7, {"name": "Webcam Mic", "_hostapi_name": "Windows WASAPI"}),
        ]
        calls = []

        def fake_capture(idx, info):
            calls.append(idx)
            if idx == 5:
                return {
                    "ok": False,
                    "error": "MIC_STREAM_NO_SIGNAL",
                    "max_rms": 0.0,
                    "threshold": 0.006,
                }
            return {"ok": True, "wav_path": "ok.wav", "device": idx}

        with patch.object(service, "_input_device_candidates", return_value=candidates), patch.object(
            service, "_capture_phrase_on_device", side_effect=fake_capture
        ):
            result = service._capture_phrase()

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [5, 7])
        self.assertEqual(service.config.device, 7)
        self.assertEqual(result["device_fallback_position"], 2)
        self.assertTrue(any(name == "MIC_DEVICE_CANDIDATE_SILENT" for name, _ in events.rows))

    def test_wasapi_duplicate_ranks_above_wdmks(self):
        service = MicrophoneService(
            DummyEvents(),
            ListeningConfig(
                device=None,
                preferred_device_name="",
                prefer_webcam_audio=True,
                webcam_name_hint="Webcam Mic",
            ),
        )
        devices = [
            {"name": "Webcam Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 0},
            {"name": "Webcam Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 1},
        ]
        hostapis = [{"name": "Windows WDM-KS"}, {"name": "Windows WASAPI"}]
        fake_sd = type(
            "FakeSD",
            (),
            {
                "query_devices": staticmethod(lambda: devices),
                "query_hostapis": staticmethod(lambda: hostapis),
                "default": type("D", (), {"device": (0, 0)})(),
            },
        )
        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            rows = service._input_device_candidates()
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][1]["_hostapi_name"], "Windows WASAPI")

    def test_wake_resolver_skips_quarantined_silent_duplicate(self):
        events = DummyEvents()
        service = WakeWordService(
            events,
            WakeWordConfig(
                preferred_device_name="",
                prefer_webcam_audio=True,
                webcam_name_hint="Webcam Mic",
            ),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": True, "text": ""},
        )
        service._silent_device_until[1] = monotonic() + 60.0
        devices = [
            {"name": "Webcam Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 0},
            {"name": "Webcam Mic", "max_input_channels": 1, "default_samplerate": 48000, "hostapi": 1},
        ]
        hostapis = [{"name": "Windows WASAPI"}, {"name": "Windows WASAPI"}]
        fake_sd = type(
            "FakeSD",
            (),
            {
                "query_devices": staticmethod(lambda *args: devices if not args else devices[int(args[0])]),
                "query_hostapis": staticmethod(lambda: hostapis),
                "default": type("D", (), {"device": (0, 0)})(),
            },
        )
        with patch.dict("sys.modules", {"sounddevice": fake_sd}):
            idx, dev = service._resolve_device()
        self.assertEqual(idx, 0)
        self.assertEqual(dev["name"], "Webcam Mic")

    def test_cli_exposes_signal_probe_and_auto_uses_it(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('lower == "/av probe"', text)
        self.assertIn("microphone.probe_devices(limit=12)", text)
        self.assertIn('"NO_LIVE_MIC_INPUT"', text)


if __name__ == "__main__":
    unittest.main()
