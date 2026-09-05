from __future__ import annotations

import unittest

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class SemanticIntentResolverTests(unittest.TestCase):
    def test_greeting_is_general_conversation(self):
        request = resolve_semantic_request("Ol\u00e1")

        self.assertEqual(
            request.intent,
            "GENERAL_CONVERSATION",
        )
        self.assertEqual(request.domain, "conversation")
        self.assertEqual(request.subject, "JARVIS")
        self.assertFalse(request.requires_tool)
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_jarvis_vocative_does_not_change_greeting(self):
        request = resolve_semantic_request(
            "Ol\u00e1 Jarvis"
        )

        self.assertEqual(
            request.intent,
            "GENERAL_CONVERSATION",
        )

    def test_explicit_provocation_is_social(self):
        request = resolve_semantic_request(
            "Jarvis, provoca-me"
        )

        self.assertEqual(
            request.intent,
            "SOCIAL_INTERACTION",
        )
        self.assertEqual(request.action, "provoke")
        self.assertEqual(request.target, "OWNER")
        self.assertFalse(request.requires_tool)
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_self_state_maps_to_jarvis_self(self):
        request = resolve_semantic_request(
            "Como te sentes?"
        )

        self.assertEqual(request.intent, "SELF_STATE")
        self.assertEqual(request.subject, "JARVIS")
        self.assertEqual(
            request.preferred_tool,
            "get_synthetic_self_state",
        )
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_identity_dialogue_is_not_epistemic_learning(self):
        request = resolve_semantic_request(
            "Quem \u00e9s tu?"
        )

        self.assertEqual(
            request.intent,
            "IDENTITY_DIALOGUE",
        )
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_conversation_recall_maps_to_owner_memory(self):
        request = resolve_semantic_request(
            "Recordas-te da nossa conversa?"
        )

        self.assertEqual(
            request.intent,
            "CONVERSATION_RECALL",
        )
        self.assertEqual(
            request.domain,
            "owner_memory",
        )

    def test_capability_question_can_be_learning_eligible(self):
        request = resolve_semantic_request(
            "Sabes usar Nmap?"
        )

        self.assertEqual(
            request.intent,
            "KNOWLEDGE_CAPABILITY",
        )
        self.assertTrue(
            request.epistemic_learning_eligible
        )

    def test_explicit_web_request_is_research(self):
        request = resolve_semantic_request(
            "Pesquisa na web a vers\u00e3o atual do Python"
        )

        self.assertEqual(request.intent, "RESEARCH")
        self.assertEqual(request.domain, "web")
        self.assertTrue(request.requires_tool)
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_open_app_is_operational(self):
        request = resolve_semantic_request(
            "Abre o Spotify"
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )
        self.assertEqual(request.domain, "desktop")
        self.assertEqual(request.action, "open")
        self.assertEqual(request.target, "spotify")
        self.assertEqual(
            request.preferred_tool,
            "open_application",
        )
        self.assertEqual(
            request.preferred_tool,
            "open_application",
        )
        self.assertTrue(request.requires_tool)
        self.assertFalse(
            request.epistemic_learning_eligible
        )

    def test_ambiguous_language_remains_unknown(self):
        request = resolve_semantic_request(
            "Talvez aquilo de antes"
        )

        self.assertEqual(request.intent, "UNKNOWN")
        self.assertEqual(request.domain, "unknown")
        self.assertFalse(
            request.epistemic_learning_eligible
        )
        self.assertLess(request.confidence, 0.5)

    def test_empty_text_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_semantic_request("   ")


if __name__ == "__main__":
    unittest.main()
