import unittest
from pathlib import Path


class LearningGoalPermissionContractTests(unittest.TestCase):
    def test_plain_learning_goal_is_local_only_and_does_not_request_web(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

        start = cli.index("def request_external_learning_for_goal(")
        end = cli.index("def execute_owner_authorization(", start)
        block = cli[start:end]

        self.assertIn("record_jarvis_learning_goal", block)
        self.assertIn("Não usei a Internet", block)
        self.assertNotIn("autonomy.request(", block)
        self.assertNotIn("execute_direct_external_learning(", block)
        self.assertNotIn("has_standing_public_web_learning", block)
        self.assertNotIn("cloud_brain.ask(", block)


if __name__ == "__main__":
    unittest.main()
