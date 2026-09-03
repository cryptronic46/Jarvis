import unittest
from unittest.mock import patch

from jarvis_core.services.listening import (
    ListeningConfig,
    MicrophoneService,
)


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class MicrophoneCandidateFallbackTests(unittest.TestCase):
    def make_service(self):
        return MicrophoneService(
            DummyEvents(),
            ListeningConfig(
                device=47,
                preferred_device_name="JBL WAVE BEAM",
                preferred_handsfree=True,
                preferred_samplerate=16000,
            ),
        )

    def test_capture_tries_next_jbl_when_first_endpoint_is_invalid(self):
        service = self.make_service()
        candidates = [
            (
                47,
                {
                    "name": "Hands-Free (JBL WAVE BEAM)",
                    "default_samplerate": 16000,
                    "max_input_channels": 1,
                    "_hostapi_name": "Windows WDM-KS",
                },
            ),
            (
                61,
                {
                    "name": "Hands-Free (JBL WAVE BEAM)",
                    "default_samplerate": 16000,
                    "max_input_channels": 1,
                    "_hostapi_name": "Windows WASAPI",
                },
            ),
        ]

        calls = []

        def fake_capture(idx, info):
            calls.append(idx)
            if idx == 47:
                raise RuntimeError(
                    "Error opening RawInputStream: "
                    "Invalid device [PaErrorCode -9996]"
                )
            return {"ok": True, "wav_path": "ok.wav", "device": idx}

        with patch.object(
            service,
            "_input_device_candidates",
            return_value=candidates,
        ), patch.object(
            service,
            "_capture_phrase_on_device",
            side_effect=fake_capture,
        ):
            result = service._capture_phrase()

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [47, 61])
        self.assertEqual(service.config.device, 61)
        self.assertEqual(result["device_fallback_position"], 2)

    def test_non_open_error_is_not_hidden_by_switching_devices(self):
        service = self.make_service()
        candidates = [
            (
                47,
                {
                    "name": "Hands-Free (JBL WAVE BEAM)",
                    "default_samplerate": 16000,
                    "max_input_channels": 1,
                    "_hostapi_name": "Windows WDM-KS",
                },
            ),
            (
                61,
                {
                    "name": "Hands-Free (JBL WAVE BEAM)",
                    "default_samplerate": 16000,
                    "max_input_channels": 1,
                    "_hostapi_name": "Windows WASAPI",
                },
            ),
        ]

        with patch.object(
            service,
            "_input_device_candidates",
            return_value=candidates,
        ), patch.object(
            service,
            "_capture_phrase_on_device",
            side_effect=RuntimeError("disk write failed"),
        ) as mocked:
            with self.assertRaisesRegex(RuntimeError, "disk write failed"):
                service._capture_phrase()

        self.assertEqual(mocked.call_count, 1)

    def test_candidate_order_contains_all_matching_jbl_inputs(self):
        service = self.make_service()

        devices = [
            {
                "name": "Other Mic",
                "max_input_channels": 1,
                "default_samplerate": 48000,
                "hostapi": 0,
            },
            {
                "name": "Hands-Free (JBL WAVE BEAM)",
                "max_input_channels": 1,
                "default_samplerate": 16000,
                "hostapi": 1,
            },
            {
                "name": "Hands-Free (JBL WAVE BEAM)",
                "max_input_channels": 1,
                "default_samplerate": 16000,
                "hostapi": 2,
            },
        ]
        hostapis = [
            {"name": "MME"},
            {"name": "WDM-KS"},
            {"name": "WASAPI"},
        ]

        fake_sd = type(
            "FakeSD",
            (),
            {
                "query_devices": staticmethod(lambda: devices),
                "query_hostapis": staticmethod(lambda: hostapis),
                "default": type("D", (), {"device": (0, 0)})(),
            },
        )

        with patch.dict(
            "sys.modules",
            {"sounddevice": fake_sd},
        ):
            service.config.device = None
            rows = service._input_device_candidates()

        jbl_indexes = [
            idx
            for idx, dev in rows
            if "jbl wave beam" in dev["name"].lower()
        ]
        self.assertEqual(set(jbl_indexes), {1, 2})
        self.assertEqual(len(jbl_indexes), 2)


if __name__ == "__main__":
    unittest.main()
