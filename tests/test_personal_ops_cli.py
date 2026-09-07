import unittest
from pathlib import Path


class PersonalOpsCliTests(unittest.TestCase):
    def test_core_commands_exist(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        for command in (
            "/profile status",
            "/watch status",
            "/pc checkup",
            "/routine list",
            "/files index",
            "/agenda today",
            "/lock",
            "/research status",
            "/integrations",
            "/dashboard data",
        ):
            self.assertIn(
                command,
                text,
            )

    def test_retired_privacy_and_research_test_commands_are_absent(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "/privacy status",
            text,
        )
        self.assertNotIn(
            "/privacy on",
            text,
        )
        self.assertNotIn(
            "/privacy off",
            text,
        )
        self.assertNotIn(
            'lower == "/research test"',
            text,
        )
        self.assertNotIn(
            "research_engine.test()",
            text,
        )


if __name__ == "__main__":
    unittest.main()
