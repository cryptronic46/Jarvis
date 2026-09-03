import unittest

from jarvis_core.core.config import Settings


class PerformanceSettingsTests(unittest.TestCase):
    def test_defaults_are_resource_aware(self):
        settings = Settings()

        self.assertTrue(
            settings.performance_enabled
        )
        self.assertEqual(
            settings.performance_mode,
            "auto",
        )
        self.assertGreater(
            settings.performance_gpu_sample_interval_seconds,
            settings.telemetry_interval_seconds,
        )
        self.assertLess(
            settings.performance_fast_ctx,
            settings.performance_deep_ctx,
        )
        self.assertLess(
            settings.performance_eco_predict,
            settings.performance_balanced_predict,
        )


if __name__ == "__main__":
    unittest.main()
