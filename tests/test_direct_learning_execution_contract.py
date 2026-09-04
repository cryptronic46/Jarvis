import unittest
from pathlib import Path


class DirectLearningExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

    def test_direct_learning_is_intercepted_before_normal_router(self):
        direct = self.cli.index("parse_direct_external_learning_order(")
        normal = self.cli.rindex("process_request(text)")
        self.assertLess(direct, normal)

    def test_direct_authority_is_logged_not_granted_reusably(self):
        autonomy = Path("jarvis_core/services/autonomy.py").read_text(encoding="utf-8")
        start = autonomy.index("def record_direct_authorization(")
        end = autonomy.index("def authorize(", start)
        block = autonomy[start:end]
        self.assertIn('"reusable": False', block)
        self.assertIn('"remaining_uses": 0', block)
        self.assertNotIn('state["grants"].append', block)

    def test_isolated_url_can_bind_only_to_explicit_recent_learning_goal(self):
        self.assertIn('learning_followup_state = {"topic": "", "created_at": 0.0}', self.cli)
        self.assertIn('learning_followup_state["topic"] = topic', self.cli)
        self.assertIn('<= 300.0', self.cli)
        self.assertIn('"followup_bound": True', self.cli)
        self.assertIn('learning_followup_state["topic"] = ""', self.cli)
    def test_direct_learning_runs_direct_web_local_synthesis_and_stores_result(self):
        start = self.cli.index("def execute_direct_external_learning(")
        end = self.cli.index("def request_external_learning_for_goal(", start)
        block = self.cli[start:end]
        self.assertIn("research_engine.research(", block)
        self.assertIn("authorized_learning().add(", block)
        self.assertIn('source_type="authorized_direct_web_local_model_summary_v2"', block)
        self.assertIn("Esta autorização direta vale apenas para esta execução", block)
        self.assertNotIn("cloud_brain.ask(", block)


if __name__ == "__main__":
    unittest.main()
