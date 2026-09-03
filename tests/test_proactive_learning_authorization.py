import unittest
from pathlib import Path


class ProactiveLearningAuthorizationTests(unittest.TestCase):
    def test_proactive_candidates_expose_learning_topic(self):
        text = Path(
            "jarvis_core/services/personal_cognition.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"autonomy_learning_topic"',
            text,
        )

    def test_proactive_callback_requests_permission_before_web(self):
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        start = cli.index(
            "def proactive_callback("
        )
        end = cli.index(
            "proactive_service =",
            start,
        )
        block = cli[start:end]

        request_pos = block.index(
            "autonomy.request("
        )
        self.assertIn(
            'capability="external_learning"',
            block,
        )
        self.assertNotIn(
            "cloud_brain.ask(",
            block[:request_pos],
        )


if __name__ == "__main__":
    unittest.main()
