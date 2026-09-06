import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis_core.core.local_vision import NativeVisionClient


class _OldIdleTimer:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class _Runtime:
    def __init__(self, old_timer):
        self.old_timer = old_timer
        self.base_url = "http://127.0.0.1:19999"
        self.ensure_started_calls = 0
        self.shutdown_calls = []

    def ensure_started(self):
        self.ensure_started_calls += 1
        if not self.old_timer.cancelled:
            raise AssertionError(
                "previous idle timer was not cancelled before vision startup"
            )
        return SimpleNamespace(running=True)

    def shutdown(self, reason="shutdown"):
        self.shutdown_calls.append(reason)
        return {"ok": True, "released": True, "reason": reason}


class VisionIdleTimerRaceTests(unittest.TestCase):
    def test_analyze_cancels_previous_idle_timer_before_runtime_start(self):
        settings = SimpleNamespace(
            vision_native_max_tokens=100,
            vision_native_request_timeout_seconds=5,
            vision_keep_alive="2m",
        )

        client = NativeVisionClient(settings)

        old_timer = _OldIdleTimer()
        client._idle_timer = old_timer
        client.runtime = _Runtime(old_timer)

        client._schedule_idle_shutdown = Mock()
        client._json = Mock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "imagem analisada"
                        }
                    }
                ]
            }
        )

        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "image.bin"
            image.write_bytes(b"vision-test")

            result = client.analyze(
                image,
                prompt="descreve",
                system="sistema",
            )

        self.assertEqual(result, "imagem analisada")
        self.assertTrue(old_timer.cancelled)
        self.assertEqual(client.runtime.ensure_started_calls, 1)
        client._schedule_idle_shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
