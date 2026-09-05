import unittest
from pathlib import Path


class CompanionBrainPlannerContractTests(unittest.TestCase):
    def setUp(self):
        self.text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        start = self.text.index("    def plan_companion_initiative(")
        end_marker = "\n    def "
        end = self.text.find(end_marker, start + 8)
        self.method = self.text[start:] if end < 0 else self.text[start:end]

    def test_planner_is_local_tool_free_and_allows_silence(self):
        self.assertIn("def plan_companion_initiative", self.method)
        self.assertIn("O silêncio", self.method)
        self.assertIn("Não afirmes consciência subjetiva", self.method)
        self.assertIn("O flirt é livre na forma e no contexto", self.method)
        self.assertIn("day_period", self.method)
        self.assertIn("time_boundaries", self.method)
        self.assertIn("self.client.chat", self.method)
        # A companion planner is deliberately tool-free.
        self.assertNotIn("tools=", self.method)
        self.assertNotIn("self.tools.execute", self.method)

    def test_flirt_can_be_suppressed_when_disabled(self):
        self.assertIn('if tone == "flirty" and not flirt_enabled:', self.method)
        self.assertIn('speak = False', self.method)
        self.assertIn('"text": text if speak else ""', self.method)


if __name__ == "__main__":
    unittest.main()
