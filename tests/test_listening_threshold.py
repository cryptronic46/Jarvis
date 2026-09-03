import unittest
from jarvis_core.services.listening import adaptive_threshold, robust_noise_floor


class ListeningThresholdTests(unittest.TestCase):
    def test_floor_applies_to_quiet_room(self):
        self.assertEqual(adaptive_threshold(0.0), 0.006)

    def test_noise_multiplier_applies(self):
        self.assertAlmostEqual(
            adaptive_threshold(0.01, multiplier=2.0),
            0.02,
            places=5,
        )

    def test_threshold_is_capped_for_noisy_calibration(self):
        self.assertEqual(adaptive_threshold(0.08), 0.03)

    def test_robust_noise_ignores_loud_blocks(self):
        values = [0.008, 0.009, 0.010, 0.011, 0.070, 0.080, 0.090, 0.100]
        self.assertLess(robust_noise_floor(values), 0.012)

    def test_robust_noise_empty(self):
        self.assertEqual(robust_noise_floor([]), 0.0)


if __name__ == "__main__":
    unittest.main()
