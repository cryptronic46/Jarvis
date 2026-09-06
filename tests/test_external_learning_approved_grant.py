from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.services.external_learning import (
    configure_external_learning_runtime,
    execute_authorized_external_learning,
)


class _Research:
    def __init__(self):
        self.calls = []

    def available(self):
        return True

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
            text="approved stub summary",
            model="stub-local",
            sources=[],
            reason_code=None,
            error=None,
        )

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
            text="approved stub summary",
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


class _Store:
    def __init__(self):
        self.calls = []

    def add(
        self,
        **kwargs,
    ):
        self.calls.append(
            dict(kwargs)
        )

        return {
            "ok": True,
            "stored": True,
        }


class _Guardian:
    def __init__(self):
        self.consume_calls = []

    def consume_authorized_grant(
        self,
        **kwargs,
    ):
        self.consume_calls.append(
            dict(kwargs)
        )

        return {
            "ok": True,
            "allowed": True,
            "authorization": {
                "token":
                    kwargs["token"],
                "capability":
                    kwargs["capability"],
                "payload":
                    dict(kwargs["payload"]),
                "remaining_uses": 0,
            },
        }

    def has_standing_public_web_learning(
        self,
    ):
        return False


class ExternalLearningApprovedGrantTests(
    unittest.TestCase
):
    def test_approved_grant_consumes_exact_token_and_payload_before_research(
        self,
    ):
        research = _Research()
        store = _Store()
        guardian = _Guardian()

        configure_external_learning_runtime(
            research,
            None,
        )

        payload = {
            "topic": "HTTP caching",
            "query": (
                "Research HTTP caching "
                "using public sources."
            ),
            "deep": True,
            "scope":
                "single_research_session",
            "source_url": None,
            "original_query":
                "Explain HTTP caching.",
        }

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
                    topic=payload["topic"],
                    query=payload["query"],
                    source_text="",
                    deep=True,
                    scope=(
                        "single_research_session"
                    ),
                    source_url="",
                    standing_public_web_read_only_grant=False,
                    authority_mode=(
                        "approved_grant"
                    ),
                    authorization_token=(
                        "ABC123"
                    ),
                    authorization_action=(
                        "external_learning_resume_query"
                    ),
                    authorized_payload=payload,
                )
            )

        self.assertTrue(
            result["ok"]
        )

        self.assertEqual(
            len(
                guardian.consume_calls
            ),
            1,
        )

        consumed = (
            guardian.consume_calls[0]
        )

        self.assertEqual(
            consumed["token"],
            "ABC123",
        )

        self.assertEqual(
            consumed["capability"],
            "external_learning",
        )

        self.assertEqual(
            consumed["payload"],
            payload,
        )

        self.assertEqual(
            consumed["action"],
            "external_learning_resume_query",
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
            store.calls[0][
                "authorization_token"
            ],
            "ABC123",
        )

    def test_approved_grant_argument_tamper_fails_before_consumption_and_research(
        self,
    ):
        research = _Research()
        guardian = _Guardian()

        configure_external_learning_runtime(
            research,
            None,
        )

        payload = {
            "topic": "HTTP caching",
            "query": "Research HTTP caching.",
            "deep": False,
            "scope":
                "single_research_session",
        }

        with patch(
            "jarvis_core.services.external_learning.autonomy_guardian",
            return_value=guardian,
        ):
            result = (
                execute_authorized_external_learning(
                    topic=(
                        "credential dumping"
                    ),
                    query=payload["query"],
                    source_text="",
                    deep=False,
                    scope=(
                        "single_research_session"
                    ),
                    source_url="",
                    standing_public_web_read_only_grant=False,
                    authority_mode=(
                        "approved_grant"
                    ),
                    authorization_token=(
                        "ABC123"
                    ),
                    authorization_action=(
                        "external_learning"
                    ),
                    authorized_payload=payload,
                )
            )

        self.assertFalse(
            result["ok"]
        )

        self.assertEqual(
            result["error"],
            "APPROVED_GRANT_ARGUMENT_MISMATCH",
        )

        self.assertEqual(
            guardian.consume_calls,
            [],
        )

        self.assertEqual(
            research.calls,
            [],
        )

    def test_approved_grant_scope_tamper_fails_before_consumption_and_research(
        self,
    ):
        research = _Research()
        guardian = _Guardian()

        configure_external_learning_runtime(
            research,
            None,
        )

        payload = {
            "topic": "HTTP caching",
            "query": "Research HTTP caching.",
            "deep": False,
            "scope":
                "single_research_session",
        }

        with patch(
            "jarvis_core.services.external_learning.autonomy_guardian",
            return_value=guardian,
        ):
            result = (
                execute_authorized_external_learning(
                    topic=payload["topic"],
                    query=payload["query"],
                    source_text="",
                    deep=False,
                    scope="different_scope",
                    source_url="",
                    standing_public_web_read_only_grant=False,
                    authority_mode="approved_grant",
                    authorization_token="ABC123",
                    authorization_action="external_learning",
                    authorized_payload=payload,
                )
            )

        self.assertFalse(
            result["ok"]
        )

        self.assertEqual(
            result["error"],
            "APPROVED_GRANT_ARGUMENT_MISMATCH",
        )

        self.assertEqual(
            guardian.consume_calls,
            [],
        )

        self.assertEqual(
            research.calls,
            [],
        )


    def test_cli_authorization_executor_uses_tool_registry_not_research_engine(
        self,
    ):
        source = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast_parse(
            source
        )

        block = ""

        for node in tree.body:
            pass

        # execute_owner_authorization is nested inside main(),
        # therefore inspect all nested functions.
        import ast

        parsed = ast.parse(
            source
        )

        for node in ast.walk(
            parsed
        ):
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "execute_owner_authorization"
            ):
                block = (
                    ast.get_source_segment(
                        source,
                        node,
                    )
                    or ""
                )
                break

        self.assertTrue(
            block
        )

        self.assertIn(
            '"execute_authorized_external_learning"',
            block,
        )

        self.assertIn(
            "tools.execute(",
            block,
        )

        self.assertIn(
            '"authority_mode":',
            block,
        )

        self.assertIn(
            '"approved_grant"',
            block,
        )

        self.assertNotIn(
            "research_engine.research(",
            block,
        )

        self.assertNotIn(
            "research_engine.research_url(",
            block,
        )

        self.assertNotIn(
            "authorized_learning().add(",
            block,
        )

        self.assertNotIn(
            "queue_external_learning_retry(",
            block,
        )


def ast_parse(
    source,
):
    import ast

    return ast.parse(
        source
    )


if __name__ == "__main__":
    unittest.main()
