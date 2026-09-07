import unittest
from pathlib import Path


class CompanionBrainPlannerContractTests(
    unittest.TestCase
):
    def setUp(self):
        text = Path(
            "jarvis_core/core/brain.py"
        ).read_text(
            encoding="utf-8"
        )

        start = text.index(
            "    def plan_companion_initiative("
        )

        end = text.find(
            "\n    def ",
            start + 8,
        )

        self.method = (
            text[start:]
            if end < 0
            else text[start:end]
        )

    def test_planner_is_local_tool_free_and_allows_silence(
        self,
    ):
        self.assertIn(
            "Silence is valid",
            self.method,
        )
        self.assertIn(
            "relational_presence_state",
            self.method,
        )
        self.assertIn(
            "synthetic_self_state",
            self.method,
        )
        self.assertIn(
            "self.client.chat",
            self.method,
        )
        self.assertNotIn(
            "tools=",
            self.method,
        )
        self.assertNotIn(
            "self.tools.execute",
            self.method,
        )

    def test_planner_has_no_flirt_mode_or_intensity_switch(
        self,
    ):
        self.assertNotIn(
            "flirt_enabled",
            self.method,
        )
        self.assertNotIn(
            "flirt_intensity",
            self.method,
        )
        self.assertNotIn(
            'tone == "flirty"',
            self.method,
        )
        self.assertIn(
            "never a mode or preset",
            self.method,
        )


if __name__ == "__main__":
    unittest.main()
