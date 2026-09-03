import unittest
from pathlib import Path


class SttFallbackContractTests(unittest.TestCase):
    def test_runtime_cuda_fallback_exists(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn("STT_RUNTIME_FALLBACK", text)
        self.assertIn('device="cpu"', text)
        self.assertIn('compute_type="int8"', text)
        self.assertIn("_looks_like_cuda_runtime_error", text)

    def test_cli_shows_runtime_fallback_event(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('"STT_RUNTIME_FALLBACK":"STT"', text)


if __name__ == "__main__":
    unittest.main()
