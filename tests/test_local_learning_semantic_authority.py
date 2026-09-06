from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis_core.services.personal_cognition as cognition_module
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class _Store:
    def __init__(self):
        self.calls = []

    def record_jarvis_learning_goal(
        self,
        topic,
        *,
        source_text="",
    ):
        self.calls.append(
            ("goal", topic, source_text)
        )
        return {
            "ok": True,
            "stored": True,
            "topic": topic,
        }

    def record_local_teaching(
        self,
        statement,
        *,
        source_text="",
    ):
        self.calls.append(
            ("teaching", statement, source_text)
        )
        return {
            "ok": True,
            "stored": True,
            "statement": statement,
        }


class LocalLearningSemanticAuthorityTests(
    unittest.TestCase
):
    def test_learning_goal_uses_exact_local_tool(self):
        text = (
            "Jarvis, quero que aprendas a programar em C"
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )
        self.assertEqual(
            request.domain,
            "knowledge",
        )
        self.assertEqual(
            request.subject,
            "JARVIS",
        )
        self.assertEqual(
            request.action,
            "record_learning_goal",
        )
        self.assertTrue(
            request.requires_tool
        )
        self.assertEqual(
            request.preferred_tool,
            "record_jarvis_learning_goal",
        )

        args = dict(
            request.tool_arguments
        )

        self.assertEqual(
            args["source_text"],
            text,
        )
        self.assertNotIn(
            "direct_user_authority",
            args,
        )

    def test_local_teaching_uses_exact_local_tool(self):
        text = (
            "Jarvis, aprende que HTTP 304 "
            "significa Not Modified."
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.action,
            "record_local_teaching",
        )
        self.assertEqual(
            request.preferred_tool,
            "record_local_teaching",
        )

        args = dict(
            request.tool_arguments
        )

        self.assertIn(
            "HTTP 304",
            args["statement"],
        )
        self.assertEqual(
            args["source_text"],
            text,
        )

    def test_external_learning_has_priority(self):
        request = resolve_semantic_request(
            "Jarvis, estuda na internet sobre HTTP caching.",
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.action,
            "learn_external",
        )
        self.assertEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

    def test_local_pdf_sync_has_priority(self):
        request = resolve_semantic_request(
            "Jarvis, aprende todos os documentos PDF.",
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.action,
            "sync_library",
        )
        self.assertEqual(
            request.preferred_tool,
            "sync_book_library",
        )

    def test_goal_wrapper_calls_cognition_store(self):
        fake = _Store()

        with patch.object(
            cognition_module,
            "personal_cognition",
            return_value=fake,
        ):
            result = (
                cognition_module.record_jarvis_learning_goal(
                    "programar em C",
                    source_text=(
                        "Jarvis, aprende a programar em C"
                    ),
                )
            )

        self.assertTrue(
            result["ok"]
        )
        self.assertEqual(
            fake.calls[0][0],
            "goal",
        )

    def test_teaching_wrapper_calls_cognition_store(self):
        fake = _Store()

        with patch.object(
            cognition_module,
            "personal_cognition",
            return_value=fake,
        ):
            result = (
                cognition_module.record_local_teaching(
                    "HTTP caching usa validadores",
                    source_text=(
                        "Jarvis, aprende que HTTP caching usa validadores"
                    ),
                )
            )

        self.assertTrue(
            result["ok"]
        )
        self.assertEqual(
            fake.calls[0][0],
            "teaching",
        )

    def test_cli_has_no_learning_semantic_interception(self):
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "parse_learning_goal(",
            "parse_local_teaching_statement(",
            "request_external_learning_for_goal(",
            "learning_followup_state",
        ):
            self.assertNotIn(
                forbidden,
                cli,
            )

    def test_registry_contains_local_write_tools(self):
        registry = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"record_jarvis_learning_goal"',
            registry,
        )
        self.assertIn(
            '"record_local_teaching"',
            registry,
        )


if __name__ == "__main__":
    unittest.main()
