import json
import unittest
from pathlib import Path


class MicCalibrationContractTests(unittest.TestCase):
    def test_safer_defaults(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["mic_threshold_multiplier"], 2.0)
        self.assertEqual(data["mic_threshold_floor"], 0.006)

    def test_robust_noise_is_used(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn("robust_noise_floor(noise_values)", text)
        self.assertIn("ceiling: float = 0.030", text)

    def test_calibration_event_exposes_debug_values(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("raw_noise_mean", text)
        self.assertIn("threshold", text)


if __name__ == "__main__":
    unittest.main()
