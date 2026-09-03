from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

import numpy as np

from jarvis_core.services.wake_verifier import NumpyWakeVerifier


class WakeVerifierNumpyTests(unittest.TestCase):
    def test_binary_logistic_score_matches_expected(self):
        verifier = NumpyWakeVerifier(
            mean=np.array([1.0, 2.0]),
            scale=np.array([2.0, 4.0]),
            coef=np.array([[1.5, -0.5]]),
            intercept=np.array([0.2]),
            model_key='hey_jarvis',
        )
        x = np.array([[3.0, 6.0]])
        z = np.array([1.0, 1.0])
        logit = float(np.array([1.5, -0.5]) @ z + 0.2)
        expected = 1.0 / (1.0 + np.exp(-logit))
        self.assertAlmostEqual(verifier.score(x), expected, places=8)

    def test_roundtrip_npz(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'verifier.npz'
            np.savez_compressed(
                path,
                mean=np.array([0.0, 0.0]),
                scale=np.array([1.0, 1.0]),
                coef=np.array([[1.0, 1.0]]),
                intercept=np.array([0.0]),
                model_key=np.asarray(['hey_jarvis_v0.1']),
            )
            v = NumpyWakeVerifier.load(path)
            self.assertEqual(v.model_key, 'hey_jarvis_v0.1')
            self.assertGreater(v.score(np.array([2.0, 2.0])), 0.9)


if __name__ == '__main__':
    unittest.main()
