import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.core.events import EventBus
from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class WebcamWakeBinding0236Tests(unittest.TestCase):
    def test_command_normalizer_repairs_observed_avie_slip(self):
        text, changed = MicrophoneService._normalize_command_text("Jarvis, avie o Brave.")
        self.assertTrue(changed)
        self.assertEqual(text, "Jarvis, abre o Brave.")
        untouched, changed2 = MicrophoneService._normalize_command_text("Ontem aviei uma encomenda.")
        self.assertFalse(changed2)
        self.assertEqual(untouched, "Ontem aviei uma encomenda.")

    def test_probe_rejects_microscopic_nonzero_noise(self):
        class FakeStream:
            def __init__(self, callback=None, **kwargs): self.callback = callback
            def __enter__(self):
                import numpy as np
                raw = (np.ones(4410, dtype=np.int16)).tobytes()  # RMS ~3.05e-05
                for _ in range(5): self.callback(raw, 4410, None, None)
                return self
            def __exit__(self, *args): return False
        fake_sd = types.SimpleNamespace(
            query_devices=lambda: [{"name":"Webcam Mic","max_input_channels":1,"default_samplerate":44100,"hostapi":0}],
            RawInputStream=FakeStream,
        )
        svc = MicrophoneService(EventBus(), ListeningConfig(probe_min_signal_rms=0.001))
        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            result = svc.probe_device_signal(0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["signal_class"], "near_silence")

    def test_recent_success_can_disambiguate_short_passive_probe(self):
        class FakeStream:
            def __init__(self, callback=None, **kwargs): self.callback = callback
            def __enter__(self):
                import numpy as np
                raw = np.zeros(4800, dtype=np.int16).tobytes()
                for _ in range(5): self.callback(raw, 4800, None, None)
                return self
            def __exit__(self, *args): return False
        fake_sd = types.SimpleNamespace(
            query_devices=lambda: [{"name":"GENERAL WEBCAM","max_input_channels":1,"default_samplerate":48000,"hostapi":0}],
            RawInputStream=FakeStream,
        )
        svc = MicrophoneService(EventBus(), ListeningConfig(probe_min_signal_rms=0.001))
        svc._mark_verified_signal(0, 0.10)
        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            result = svc.probe_device_signal(0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verified_recent"])
        self.assertEqual(result["signal_class"], "recently_verified")

    def test_wake_resolver_honors_owner_selected_index(self):
        devices = [
            {"name":"GENERAL WEBCAM","max_input_channels":1,"default_samplerate":44100,"hostapi":0},
            {"name":"GENERAL WEBCAM","max_input_channels":1,"default_samplerate":48000,"hostapi":1},
        ]
        hostapis = [{"name":"Windows DirectSound"},{"name":"Windows WASAPI"}]
        fake_sd = types.SimpleNamespace(query_devices=lambda *args: devices if not args else devices[int(args[0])], query_hostapis=lambda: hostapis, default=types.SimpleNamespace(device=(0,0)))
        service = WakeWordService(EventBus(), WakeWordConfig(preferred_device_index=0, webcam_name_hint="GENERAL WEBCAM"), lambda command: None, lambda path: {"ok": True, "text": ""})
        with patch.dict(sys.modules, {"sounddevice": fake_sd}):
            idx, dev = service._resolve_device()
        self.assertEqual(idx, 0)
        self.assertEqual(dev["_hostapi_name"], "Windows DirectSound")

    def test_zero_calibration_is_noise_gate_tolerant(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        self.assertIn("WAKE_ZERO_NOISE_FLOOR", text)
        self.assertNotIn("calibration_max_rms <= 1e-7:\n                    self._silent_device_until", text)


if __name__ == "__main__":
    unittest.main()
