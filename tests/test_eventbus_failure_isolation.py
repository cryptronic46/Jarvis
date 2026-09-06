import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.events import EventBus


class EventBusFailureIsolationTests(unittest.TestCase):
    def test_failing_subscriber_does_not_break_emit_or_later_subscribers(self):
        with tempfile.TemporaryDirectory() as td:
            bus = EventBus(log_dir=str(Path(td) / "logs"))
            received = []

            def failing_callback(event):
                raise RuntimeError("subscriber failure")

            def healthy_callback(event):
                received.append(event.name)

            bus.subscribe(failing_callback)
            bus.subscribe(healthy_callback)

            event = bus.emit("TEST_EVENT", value=123)

            self.assertEqual(event.name, "TEST_EVENT")
            self.assertEqual(received, ["TEST_EVENT"])

            persisted = (Path(td) / "logs" / "events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"name": "TEST_EVENT"', persisted)

    def test_subscribe_is_idempotent_for_same_callback(self):
        with tempfile.TemporaryDirectory() as td:
            bus = EventBus(log_dir=str(Path(td) / "logs"))
            received = []

            def callback(event):
                received.append(event.name)

            bus.subscribe(callback)
            bus.subscribe(callback)
            bus.emit("ONCE")

            self.assertEqual(received, ["ONCE"])


if __name__ == "__main__":
    unittest.main()
