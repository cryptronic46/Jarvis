import unittest
from pathlib import Path


class TelemetryGpuThrottleTests(unittest.TestCase):
    def test_gpu_has_independent_sampling_interval(self):
        text = Path(
            "jarvis_core/services/telemetry.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "gpu_interval_seconds",
            text,
        )
        self.assertIn(
            "self._last_gpu",
            text,
        )
        self.assertIn(
            "now_mono - self._last_gpu_monotonic >= self.gpu_interval",
            text,
        )
        self.assertIn(
            "gpu=list(self._last_gpu)",
            text,
        )


if __name__ == "__main__":
    unittest.main()
