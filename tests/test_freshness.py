import unittest
from jarvis_core.core.freshness import requires_current_gpu, requires_current_system

class FreshnessTests(unittest.TestCase):
    def test_current_gpu(self):
        self.assertTrue(requires_current_gpu("Qual é a temperatura atual da RTX 5070?"))

    def test_old_gpu_question_does_not_force(self):
        self.assertFalse(requires_current_gpu("Qual era a temperatura da GPU?"))

    def test_current_pc(self):
        self.assertTrue(requires_current_system("Como está o meu PC agora?"))

    def test_legacy_freshness_fallback_allows_current_pc(self):
        from jarvis_core.core.freshness import (
            allows_freshness_fallback,
        )

        self.assertTrue(
            allows_freshness_fallback(
                "Como esta o meu PC agora?",
                semantic_request_present=False,
            )
        )

    def test_structured_request_disables_freshness_fallback(self):
        import inspect

        from jarvis_core.core.brain import (
            JarvisBrain,
        )
        from jarvis_core.core.freshness import (
            allows_freshness_fallback,
        )

        self.assertFalse(
            allows_freshness_fallback(
                "Como esta o meu PC agora?",
                semantic_request_present=True,
            )
        )

        source = inspect.getsource(
            JarvisBrain._ask_locked
        )

        compact = "".join(
            source.split()
        )

        self.assertIn(
            "allows_freshness_fallback(",
            source,
        )

        self.assertIn(
            "semantic_request_present=(requestisnotNone)",
            compact,
        )


if __name__ == "__main__":
    unittest.main()
