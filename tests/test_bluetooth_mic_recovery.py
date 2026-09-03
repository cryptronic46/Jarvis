import json
import unittest
from pathlib import Path


class BluetoothMicRecoveryTests(unittest.TestCase):
    def test_settings_enable_stream_retry(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(data["mic_stream_retries"], 1)
        self.assertGreater(data["mic_stream_recovery_seconds"], 0)

    def test_zero_signal_is_distinguished_from_normal_timeout(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn('"MIC_STREAM_NO_SIGNAL"', text)
        self.assertIn('"MIC_STREAM_RECOVERY"', text)
        self.assertIn("max_observed_rms", text)

    def test_capture_phrase_retries_dead_stream(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn('result.get("error") != "MIC_STREAM_NO_SIGNAL"', text)
        self.assertIn("stream_recovery_seconds", text)

    def test_enrollment_waits_between_samples(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("sleep(max(0.5, float(settings.mic_stream_recovery_seconds)))", text)


if __name__ == "__main__":
    unittest.main()
