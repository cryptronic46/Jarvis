from __future__ import annotations

import unittest

from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.services.semantic_request import StructuredRequest


class _Settings:
    model = "qwen3:8b"
    external_ai_complexity_threshold = 4
    epistemic_learning_enabled = False
    autonomy_proactive_learning_enabled = False


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _RequestAwareLocalBrain:
    def __init__(self):
        self.received_text = None
        self.received_request = None

    def ask(self, text, *, request=None):
        self.received_text = text
        self.received_request = request
        return "resposta local"


class StructuredRequestTransportTests(unittest.TestCase):
    def test_hybrid_forwards_same_request_object_to_local_brain(self):
        local = _RequestAwareLocalBrain()

        hybrid = HybridBrain(
            settings=_Settings(),
            events=_Events(),
            local_brain=local,
        )

        request = StructuredRequest(
            raw_text="Ol?",
            effective_text="Ol?",
            intent="UNKNOWN",
            domain="unknown",
            subject="UNKNOWN",
            confidence=0.0,
        )

        answer = hybrid.ask(
            "Ol?",
            request=request,
        )

        self.assertEqual(answer.text, "resposta local")
        self.assertEqual(local.received_text, "Ol?")
        self.assertIs(local.received_request, request)

    def test_legacy_local_brain_remains_compatible_without_request(self):
        class LegacyLocalBrain:
            def ask(self, text):
                return "legacy ok"

        hybrid = HybridBrain(
            settings=_Settings(),
            events=_Events(),
            local_brain=LegacyLocalBrain(),
        )

        answer = hybrid.ask("teste")

        self.assertEqual(answer.text, "legacy ok")


if __name__ == "__main__":
    unittest.main()
