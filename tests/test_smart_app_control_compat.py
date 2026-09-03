import unittest
from pathlib import Path


class SmartAppControlCompatibilityTests(unittest.TestCase):
    def test_no_new_native_kws_runtime(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(
            encoding="utf-8"
        ).lower()
        for term in (
            "sherpa_onnx",
            "_sherpa_onnx",
            "scipy",
            "_ckdtree",
            "openwakeword",
        ):
            self.assertNotIn(term, text)

    def test_wake_requirements_are_empty(self):
        lines = [
            line.strip()
            for line in Path("requirements-wakeword.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertEqual(lines, [])

    def test_no_wake_model_installer(self):
        self.assertFalse(
            Path("jarvis_core/setup_wakeword_model.py").exists()
        )


if __name__ == "__main__":
    unittest.main()
