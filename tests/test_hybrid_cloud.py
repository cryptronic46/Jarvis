import json
import unittest
from pathlib import Path
from jarvis_core.core.hybrid_brain import HybridRoutePolicy


class Settings:
    hybrid_mode = "local"


class LocalFirstRoutingTests(unittest.TestCase):
    def setUp(self):
        self.policy = HybridRoutePolicy(Settings())

    def test_simple_question_stays_local(self):
        result = self.policy.decide("Quanto é 2 mais 2?", True)
        self.assertEqual(result.route, "local")

    def test_web_query_routes_direct_research(self):
        result = self.policy.decide("Pesquisa na Internet as notícias mais recentes sobre tecnologia", True)
        self.assertEqual(result.route, "research")
        self.assertTrue(result.use_web)

    def test_complex_query_stays_local(self):
        result = self.policy.decide("Analisa esta arquitetura e propõe uma estratégia melhor.", True)
        self.assertEqual(result.route, "local")

    def test_web_research_does_not_depend_on_cloud_configuration(self):
        result = self.policy.decide("Quais são as notícias de hoje?", False)
        self.assertEqual(result.route, "research")

    def test_explicit_cloud_prefix_is_hard_blocked(self):
        result = self.policy.decide("/cloud explica isto", False)
        self.assertEqual(result.route, "external_ai_blocked")
        self.assertEqual(result.reason, "external_ai_hard_block")

    def test_local_first_settings(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertFalse(data["external_ai_enabled"])
        self.assertFalse(data["cloud_enabled"])
        self.assertEqual(data["hybrid_mode"], "local")
        self.assertTrue(data["local_research_enabled"])
        self.assertFalse(data["performance_cloud_offload_under_pressure"])

    def test_external_ai_is_never_a_runtime_route(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn("learning-first", text)
        self.assertIn("complexity_score", text)
        self.assertIn("external_ai_blocked", text)
        self.assertNotIn("should_offload_to_cloud(decision.text)", text)


if __name__ == "__main__":
    unittest.main()
