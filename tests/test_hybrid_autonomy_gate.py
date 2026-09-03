import unittest
from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridRoutePolicy


class HybridAutonomyGateTests(unittest.TestCase):
    def setUp(self):
        self.policy = HybridRoutePolicy(Settings())

    def test_explicit_web_order_is_direct_research(self):
        decision = self.policy.decide("Pesquisa na Internet as notícias de hoje", cloud_available=True)
        self.assertEqual(decision.reason, "explicit_web")
        self.assertEqual(decision.route, "research")
        self.assertTrue(decision.use_web)

    def test_current_info_without_web_instruction_is_autonomous_web(self):
        decision = self.policy.decide("Quais são as notícias de hoje?", cloud_available=True)
        self.assertEqual(decision.reason, "web_required")
        self.assertEqual(decision.route, "research")
        self.assertTrue(decision.use_web)

    def test_explicit_cloud_request_is_hard_blocked(self):
        decision = self.policy.decide("Usa a cloud para analisar isto", cloud_available=True)
        self.assertEqual(decision.reason, "external_ai_hard_block")
        self.assertEqual(decision.route, "external_ai_blocked")
        self.assertFalse(decision.use_web)


if __name__ == "__main__":
    unittest.main()
