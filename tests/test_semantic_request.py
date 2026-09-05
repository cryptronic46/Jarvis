from __future__ import annotations

import unittest

from jarvis_core.services.semantic_request import StructuredRequest


class StructuredRequestTests(unittest.TestCase):
    def test_social_request_is_conversational_and_not_epistemic(self):
        request = StructuredRequest(
            raw_text="Jarvis, provoca-me",
            effective_text="Jarvis, provoca-me",
            intent="SOCIAL_INTERACTION",
            domain="conversation",
            subject="JARVIS",
            action="provoke",
            target="OWNER",
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.96,
        )

        self.assertTrue(request.conversational)
        self.assertFalse(request.operational)
        self.assertFalse(request.research_requested)
        self.assertFalse(request.epistemic_learning_eligible)
        self.assertFalse(request.requires_tool)

    def test_greeting_can_be_plain_conversation_without_tool(self):
        request = StructuredRequest(
            raw_text="Ol?",
            effective_text="Ol?",
            intent="GENERAL_CONVERSATION",
            domain="conversation",
            subject="JARVIS",
            requires_tool=False,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        self.assertTrue(request.conversational)
        self.assertFalse(request.requires_tool)
        self.assertFalse(request.epistemic_learning_eligible)

    def test_knowledge_request_can_allow_epistemic_learning(self):
        request = StructuredRequest(
            raw_text="Explica-me CVE-2026-1234",
            effective_text="Explica-me CVE-2026-1234",
            intent="KNOWLEDGE_CAPABILITY",
            domain="knowledge",
            subject="EXTERNAL",
            epistemic_learning_eligible=True,
            confidence=0.91,
        )

        self.assertFalse(request.conversational)
        self.assertTrue(request.epistemic_learning_eligible)

    def test_operational_request_can_require_tool(self):
        request = StructuredRequest(
            raw_text="Abre o Spotify",
            effective_text="Abre o Spotify",
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="open",
            target="spotify",
            requires_tool=True,
            preferred_tool="open_application",
            tool_arguments={"app_name": "spotify"},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        self.assertTrue(request.operational)
        self.assertTrue(request.requires_tool)
        self.assertEqual(
            request.preferred_tool,
            "open_application",
        )
        self.assertEqual(
            request.tool_arguments,
            {"app_name": "spotify"},
        )

        data = request.as_dict()

        self.assertEqual(
            data["preferred_tool"],
            "open_application",
        )
        self.assertEqual(
            data["tool_arguments"],
            {"app_name": "spotify"},
        )

    def test_tool_arguments_are_deeply_immutable(self):
        request = StructuredRequest(
            raw_text="Abre o Spotify",
            effective_text="Abre o Spotify",
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="open",
            target="spotify",
            requires_tool=True,
            preferred_tool="open_application",
            tool_arguments={
                "app_name": "spotify",
                "options": {
                    "flags": ["safe"],
                },
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        with self.assertRaises(TypeError):
            request.tool_arguments[
                "app_name"
            ] = "notepad"

        with self.assertRaises(TypeError):
            request.tool_arguments[
                "options"
            ]["flags"] = ("unsafe",)

        data = request.as_dict()

        data["tool_arguments"][
            "app_name"
        ] = "notepad"

        data["tool_arguments"][
            "options"
        ]["flags"].append("changed")

        self.assertEqual(
            request.tool_arguments["app_name"],
            "spotify",
        )
        self.assertEqual(
            tuple(
                request.tool_arguments[
                    "options"
                ]["flags"]
            ),
            ("safe",),
        )

    def test_tool_arguments_require_preferred_tool(self):
        with self.assertRaises(ValueError):
            StructuredRequest(
                raw_text="teste",
                effective_text="teste",
                intent="OPERATIONAL_ACTION",
                domain="desktop",
                subject="SYSTEM",
                requires_tool=True,
                tool_arguments={"app_name": "spotify"},
                confidence=0.99,
            )

    def test_invalid_closed_schema_value_is_rejected(self):
        with self.assertRaises(ValueError):
            StructuredRequest(
                raw_text="teste",
                effective_text="teste",
                intent="MADE_UP_INTENT",
                domain="conversation",
                subject="JARVIS",
                confidence=0.5,
            )

    def test_confidence_must_be_bounded(self):
        with self.assertRaises(ValueError):
            StructuredRequest(
                raw_text="teste",
                effective_text="teste",
                intent="UNKNOWN",
                domain="unknown",
                subject="UNKNOWN",
                confidence=1.2,
            )

    def test_as_dict_preserves_semantic_contract(self):
        request = StructuredRequest(
            raw_text="Como te sentes?",
            effective_text="Como te sentes?",
            intent="SELF_STATE",
            domain="jarvis_self",
            subject="JARVIS",
            action="read_state",
            requires_tool=True,
            preferred_tool="get_synthetic_self_state",
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        data = request.as_dict()

        self.assertEqual(data["intent"], "SELF_STATE")
        self.assertEqual(data["subject"], "JARVIS")
        self.assertEqual(
            data["preferred_tool"],
            "get_synthetic_self_state",
        )
        self.assertFalse(data["epistemic_learning_eligible"])


if __name__ == "__main__":
    unittest.main()
