import json
import unittest
from pathlib import Path


class SpeedContractTests(unittest.TestCase):
    def test_optimized_defaults(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["think_mode"], "adaptive")


    def test_llm_keep_alive_and_adaptive_thinking(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        perf = Path("jarvis_core/services/performance.py").read_text(encoding="utf-8")
        self.assertIn("ollama_keep_alive", text)
        self.assertIn("PerformancePlan", text)
        self.assertIn('"think": bool(plan.think)', text)
        self.assertIn("def plan(", perf)
        self.assertIn('profile="fast"', perf)
        self.assertIn('profile="deep"', perf)

    def test_background_warmup(self):
        text = Path("jarvis_core/cli.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("brain.warmup()", text)
        self.assertIn('name="jarvis-warmup"', text)
        self.assertNotIn(
            "microphone.preload_stt()",
            text,
        )



if __name__ == "__main__":
    unittest.main()
