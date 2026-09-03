import unittest
from pathlib import Path


class HybridAutonomyContractTests(unittest.TestCase):
    def test_autonomous_web_path_is_gated(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn("def _autonomy_gate", text)
        self.assertIn('capability="web_research"', text)
        self.assertIn('source="local_research_router"', text)

    def test_forced_local_is_local_and_learning_first(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn('"local", "forced_local"', text)
        self.assertIn("def _learning_gap_offer", text)
        self.assertIn('action="external_learning_resume_query"', text)

    def test_external_expert_is_optional_isolated_and_gated(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        for reason in ("forced_web", "forced_research", "explicit_web"):
            self.assertIn(f'"{reason}"', text)
        self.assertIn('capability="cloud_reasoning"', text)
        self.assertIn('action="cloud_reasoning"', text)
        self.assertIn('"isolated": True', text)
        self.assertIn("studied_knowledge_still_insufficient", text)


if __name__ == "__main__":
    unittest.main()
