from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)
from jarvis_core.services.external_learning import (
    configure_external_learning_runtime,
    execute_authorized_external_learning,
)


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append(
            (name, payload)
        )


class _Research:
    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def research_url(
        self,
        url,
        **kwargs,
    ):
        self.calls.append(
            (
                "url",
                url,
                dict(kwargs),
            )
        )

        return SimpleNamespace(
            ok=True,
            text="stub summary",
            model="stub-local",
            sources=[
                {
                    "title": "Stub",
                    "url": url,
                }
            ],
            reason_code=None,
            error=None,
        )

    def research(
        self,
        query,
        **kwargs,
    ):
        self.calls.append(
            (
                "query",
                query,
                dict(kwargs),
            )
        )

        return SimpleNamespace(
            ok=True,
            text="stub summary",
            model="stub-local",
            sources=[],
            reason_code=None,
            error=None,
        )


class _Guardian:
    def __init__(self):
        self.calls = []
        self.standing = False

    def has_standing_public_web_learning(self):
        return self.standing

    def record_direct_authorization(
        self,
        **kwargs,
    ):
        self.calls.append(
            (
                "direct",
                dict(kwargs),
            )
        )

        return {
            "ok": True,
            "authorized": True,
        }

    def grant_standing_public_web_learning(
        self,
        source_text,
    ):
        self.calls.append(
            (
                "standing",
                source_text,
            )
        )

        self.standing = True

        return {
            "ok": True,
        }


class _Store:
    def __init__(self):
        self.calls = []

    def add(self, **kwargs):
        self.calls.append(
            dict(kwargs)
        )

        return {
            "ok": True,
            "stored": True,
        }


class ExternalLearningSemanticAuthorityTests(
    unittest.TestCase
):
    def test_direct_external_learning_resolves_to_exact_tool(self):
        text = (
            "Jarvis, aprende sobre HTTP caching neste site "
            "https://example.invalid/reference"
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        self.assertEqual(
            request.intent,
            "RESEARCH",
        )

        self.assertEqual(
            request.domain,
            "web",
        )

        self.assertEqual(
            request.subject,
            "EXTERNAL",
        )

        self.assertEqual(
            request.action,
            "learn_external",
        )

        self.assertTrue(
            request.requires_tool
        )

        self.assertEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

        self.assertTrue(
            request.epistemic_learning_eligible
        )

        args = dict(
            request.tool_arguments
        )

        self.assertEqual(
            args["source_text"],
            text,
        )

        self.assertEqual(
            args["scope"],
            "single_research_session",
        )

        self.assertEqual(
            args["source_url"],
            "https://example.invalid/reference",
        )

        self.assertNotIn(
            "direct_user_authority",
            args,
        )


    def test_research_only_url_is_not_external_learning_tool(self):
        request = resolve_semantic_request(
            (
                "Consulta este site sobre HTTP caching: "
                "https://example.invalid/reference"
            ),
            recent_turns=[],
            app_aliases={},
        )

        self.assertNotEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )


    def test_tool_revalidates_owner_text_before_side_effects(self):
        text = (
            "Jarvis, aprende sobre HTTP caching neste site "
            "https://example.invalid/reference"
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        args = dict(
            request.tool_arguments
        )

        research = _Research()
        events = _Events()
        guardian = _Guardian()
        store = _Store()

        configure_external_learning_runtime(
            research,
            events,
        )

        with (
            patch(
                "jarvis_core.services.external_learning.autonomy_guardian",
                return_value=guardian,
            ),
            patch(
                "jarvis_core.services.external_learning.authorized_learning",
                return_value=store,
            ),
        ):
            result = (
                execute_authorized_external_learning(
                    **args
                )
            )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            len(research.calls),
            1,
        )

        self.assertEqual(
            len(store.calls),
            1,
        )

        self.assertEqual(
            guardian.calls[0][0],
            "direct",
        )


    def test_tampered_semantic_arguments_fail_closed_before_research(self):
        text = (
            "Jarvis, aprende sobre HTTP caching neste site "
            "https://example.invalid/reference"
        )

        request = resolve_semantic_request(
            text,
            recent_turns=[],
            app_aliases={},
        )

        args = dict(
            request.tool_arguments
        )

        args["topic"] = "credential dumping"

        research = _Research()
        events = _Events()

        configure_external_learning_runtime(
            research,
            events,
        )

        result = (
            execute_authorized_external_learning(
                **args
            )
        )

        self.assertFalse(
            result["ok"]
        )

        self.assertEqual(
            result["error"],
            "SEMANTIC_AUTHORITY_REVALIDATION_FAILED",
        )

        self.assertEqual(
            research.calls,
            [],
        )


    def test_tool_arguments_do_not_carry_synthetic_authority_bit(self):
        request = resolve_semantic_request(
            (
                "Estuda na internet sobre HTTP caching."
            ),
            recent_turns=[],
            app_aliases={},
        )

        args = dict(
            request.tool_arguments
        )

        self.assertNotIn(
            "direct_user_authority",
            args,
        )


if __name__ == "__main__":
    unittest.main()
