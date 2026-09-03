import unittest
from pathlib import Path


class WakeBluetoothStreamTests(unittest.TestCase):
    def setUp(self):
        self.text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")

    def test_uses_raw_input_stream_callback(self):
        self.assertIn("sd.RawInputStream(", self.text)
        self.assertIn("callback=callback", self.text)

    def test_never_uses_blocking_stream_read(self):
        self.assertNotIn("stream.read(", self.text)

    def test_uses_queue_like_working_listen_path(self):
        self.assertIn("Queue[bytes]", self.text)
        self.assertIn("audio_queue.get(", self.text)
        self.assertIn("audio_queue.put_nowait(", self.text)

    def test_uses_int16_like_working_listen_path(self):
        self.assertIn('dtype="int16"', self.text)
        self.assertIn("_int16_to_float", self.text)

    def test_uses_endpoint_native_samplerate(self):
        self.assertIn(
            'device.get("default_samplerate", 0)',
            self.text,
        )
        self.assertNotIn(
            "samplerate = int(self.config.preferred_samplerate)",
            self.text,
        )

    def test_doctor_is_passive_and_does_not_open_second_stream(self):
        start = self.text.index("    def doctor(")
        end = self.text.index(
            "    def _listen_persistent_stream(",
            start,
        )
        doctor = self.text[start:end]
        self.assertNotIn("RawInputStream(", doctor)
        self.assertIn("self.status()", doctor)
        self.assertIn('"wake_engine_uses_whisper": False', doctor)

    def test_error_event_is_visible_with_message(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('elif event.name == "WAKE_ERROR":', cli)
        self.assertIn("event.data.get('error')", cli)


if __name__ == "__main__":
    unittest.main()
