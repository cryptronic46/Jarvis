import json
import unittest
from pathlib import Path


class WakeWordContractTests(unittest.TestCase):
    def test_settings_have_acoustic_profile(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["wake_template_path"], "voice_profiles/wake_jarvis.npz")
        self.assertEqual(data["wake_enrollment_samples"], 5)
        self.assertEqual(data["wake_feature_sample_rate"], 16000)

    def test_no_blocked_wake_backend(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8").lower()
        for term in (
            "sherpa_onnx",
            "pvporcupine",
            "picovoice",
            "openwakeword",
            "scipy",
        ):
            self.assertNotIn(term, text)

    def test_wake_uses_numpy_only_for_acoustic_features(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertIn("import numpy as np", text)
        self.assertIn("np.fft.rfft", text)
        self.assertIn("acoustic_features", text)

    def test_command_still_uses_existing_higher_accuracy_transcriber(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn(
            "transcribe_callback=microphone.transcribe_command_file",
            cli,
        )


if __name__ == "__main__":
    unittest.main()
