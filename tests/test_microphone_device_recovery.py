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


class MicrophoneDeviceRecoveryTests(unittest.TestCase):
    def make_service(self):
        events = DummyEvents()
        service = MicrophoneService(
            events,
            ListeningConfig(
                device=47,
                stream_retries=2,
                stream_recovery_seconds=0.0,
                preferred_device_name="JBL WAVE BEAM",
            ),
        )
        return service, events

    def test_invalid_device_is_recognized_as_recoverable(self):
        service, _ = self.make_service()
        exc = RuntimeError(
            "Error opening RawInputStream: "
            "Invalid device [PaErrorCode -9996]"
        )
        self.assertTrue(service._is_invalid_device_error(exc))

    def test_invalid_index_is_cleared_and_capture_retried(self):
        service, events = self.make_service()

        calls = {"count": 0}

        def fake_capture():
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError(
                    "Error opening RawInputStream: "
                    "Invalid device [PaErrorCode -9996]"
                )
            return {
                "ok": True,
                "wav_path": "dummy.wav",
                "device": 61,
            }

        with patch.object(
            service,
            "_capture_phrase",
            side_effect=fake_capture,
        ), patch.object(
            service,
            "_preferred_device",
            return_value=(
                61,
                {
                    "name": (
                        "Capacete Hands-Free "
                        "(JBL WAVE BEAM)"
                    )
                },
            ),
        ):
            result = service.capture_phrase()

        self.assertTrue(result["ok"])
        self.assertEqual(calls["count"], 2)
        self.assertIsNone(service.config.device)

        recovery_events = [
            data
            for name, data in events.rows
            if name == "MIC_DEVICE_RECOVERY"
        ]
        self.assertEqual(len(recovery_events), 1)
        self.assertEqual(
            recovery_events[0]["stale_device"],
            47,
        )
        self.assertEqual(
            recovery_events[0]["preferred_device"],
            61,
        )

    def test_non_device_errors_are_not_retried_as_hotplug(self):
        service, events = self.make_service()

        with patch.object(
            service,
            "_capture_phrase",
            side_effect=RuntimeError("unrelated failure"),
        ):
            result = service.capture_phrase()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "RuntimeError")
        self.assertEqual(service.config.device, 47)
        self.assertFalse(
            any(
                name == "MIC_DEVICE_RECOVERY"
                for name, _ in events.rows
            )
        )


if __name__ == "__main__":
    unittest.main()
