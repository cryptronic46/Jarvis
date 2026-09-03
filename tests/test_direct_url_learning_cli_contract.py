import unittest
from pathlib import Path


class DirectUrlLearningCliContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

    def test_direct_url_intent_is_intercepted_before_normal_model_routing(self):
        loop = self.text.index("while True:")
        direct = self.text.index("parse_direct_external_learning_order(", loop)
        generic = self.text.index("process_request(", direct)
        self.assertLess(direct, generic)

    def test_direct_url_uses_bounded_research_url_path(self):
        start = self.text.index("def execute_direct_external_learning(")
        end = self.text.index("def request_external_learning_for_goal(", start)
        block = self.text[start:end]
        self.assertIn("source_url", block)
        self.assertIn("research_engine.research_url(", block)
        self.assertIn("não executo downloads nem comandos", block)


if __name__ == "__main__":
    unittest.main()
