import unittest
import numpy as np
from pathlib import Path

from jarvis_core.services.wakeword import (
    WakeWordConfig,
    acoustic_features,
    feature_similarity,
)


class WakeAcousticEngineTests(unittest.TestCase):
    def test_acoustic_engine_has_no_whisper_dependency(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8").lower()

        # Transcribe callback exists for the command stage, but the acoustic
        # matcher itself is NumPy-only and does not import faster_whisper.
        self.assertNotIn("from faster_whisper", text)
        self.assertNotIn("import faster_whisper", text)
        self.assertIn("acoustic_features", text)
        self.assertIn("feature_similarity", text)

    def test_same_synthetic_pattern_scores_higher_than_different_pattern(self):
        cfg = WakeWordConfig()
        sr = 16000
        t = np.arange(int(sr * 0.7), dtype=np.float32) / sr

        a = (
            0.6 * np.sin(2 * np.pi * 330 * t)
            + 0.3 * np.sin(2 * np.pi * 760 * t)
        ).astype(np.float32)
        b = (
            0.6 * np.sin(2 * np.pi * 330 * t + 0.1)
            + 0.3 * np.sin(2 * np.pi * 760 * t + 0.05)
        ).astype(np.float32)
        c = (
            0.7 * np.sin(2 * np.pi * 1500 * t)
            + 0.2 * np.sin(2 * np.pi * 2600 * t)
        ).astype(np.float32)

        fa = acoustic_features(a, sr, cfg, trim=False)
        fb = acoustic_features(b, sr, cfg, trim=False)
        fc = acoustic_features(c, sr, cfg, trim=False)

        same = feature_similarity(fa, fb)
        different = feature_similarity(fa, fc)
        self.assertGreater(same, different)

    def test_status_contract_says_no_whisper_while_idle(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"whisper_while_idle": False', text)
        self.assertIn('"wake_engine_uses_whisper": False', text)


if __name__ == "__main__":
    unittest.main()
