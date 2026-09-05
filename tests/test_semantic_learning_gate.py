from __future__ import annotations

import unittest

from jarvis_core.core.hybrid_brain import (
    HybridAnswer,
    HybridBrain,
)
from jarvis_core.services.semantic_request import StructuredRequest


class _Settings:
    model = "qwen3:8b"
    external_ai_complexity_threshold = 4
    epistemic_learning_enabled = True
    autonomy_proactive_learning_enabled = True


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _EmptyLocalBrain:
    def ask(self, text, *, request=None):
        return ""


class _ProbeHybridBrain(HybridBrain):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.learning_gap_calls = 0

    def _learning_gap_offer(self, decision, local_text):
        self.learning_gap_calls += 1

        return (
            HybridAnswer(
                text="learning offer",
                route="LEARNING",
                model=None,
                elapsed_ms=0,
                reason="test_learning_gap",
            ),
            object(),
        )


class SemanticLearningGateTests(unittest.TestCase):
    def _hybrid(self):
        return _ProbeHybridBrain(
            settings=_Settings(),
            events=_Events(),
            local_brain=_EmptyLocalBrain(),
        )

    def test_social_request_cannot_trigger_learning_gap(self):
        hybrid = self._hybrid()

        request = StructuredRequest(
            raw_text="provoca-me",
            effective_text="provoca-me",
            intent="SOCIAL_INTERACTION",
            domain="conversation",
            subject="JARVIS",
            action="provoke",
            target="OWNER",
            requires_tool=False,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        answer = hybrid.ask(
            "provoca-me",
            request=request,
        )

        self.assertEqual(hybrid.learning_gap_calls, 0)
        self.assertEqual(answer.route, "LOCAL")
        self.assertNotEqual(answer.text, "learning offer")

    def test_greeting_cannot_trigger_learning_gap(self):
        hybrid = self._hybrid()

        request = StructuredRequest(
            raw_text="ola",
            effective_text="ola",
            intent="GENERAL_CONVERSATION",
            domain="conversation",
            subject="JARVIS",
            action="greet",
            target="JARVIS",
            requires_tool=False,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        hybrid.ask(
            "ola",
            request=request,
        )

        self.assertEqual(hybrid.learning_gap_calls, 0)

    def test_learning_eligible_request_can_trigger_gap(self):
        hybrid = self._hybrid()

        request = StructuredRequest(
            raw_text="Sabes usar Nmap?",
            effective_text="Sabes usar Nmap?",
            intent="KNOWLEDGE_CAPABILITY",
            domain="knowledge",
            subject="JARVIS",
            action="answer_knowledge",
            requires_tool=False,
            epistemic_learning_eligible=True,
            confidence=0.95,
        )

        answer = hybrid.ask(
            "Sabes usar Nmap?",
            request=request,
        )

        self.assertEqual(hybrid.learning_gap_calls, 1)
        self.assertEqual(answer.text, "learning offer")
        self.assertEqual(answer.route, "LEARNING")

    def test_legacy_call_preserves_learning_behavior(self):
        hybrid = self._hybrid()

        answer = hybrid.ask(
            "legacy knowledge request"
        )

        self.assertEqual(hybrid.learning_gap_calls, 1)
        self.assertEqual(answer.text, "learning offer")


if __name__ == "__main__":
    unittest.main()
