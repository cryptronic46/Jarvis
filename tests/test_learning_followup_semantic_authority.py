from __future__ import annotations

import unittest
from unittest.mock import patch

import jarvis_core.services.external_learning as external_module
import jarvis_core.services.learning_followup as followup_module

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class _ResearchResult:
    ok = True
    text = "local synthesized test summary"
    model = "stub-local-model"
    sources = [
        {
            "url": "https://example.com/docs",
        }
    ]
    reason_code = ""
    error = ""


class _ResearchEngine:
    def __init__(self):
        self.url_calls = []
        self.search_calls = []

    def available(self):
        return True

    def research_url(
        self,
        url,
        *,
        query,
        topic,
        deep,
    ):
        if (
            followup_module.get_learning_followup_context()
            is not None
        ):
            raise AssertionError(
                "followup context must be consumed "
                "before network research"
            )

        self.url_calls.append(
            {
                "url": url,
                "query": query,
                "topic": topic,
                "deep": deep,
            }
        )

        return _ResearchResult()

    def research(
        self,
        *args,
        **kwargs,
    ):
        self.search_calls.append(
            (
                args,
                kwargs,
            )
        )

        raise AssertionError(
            "followup URL must not use search provider"
        )


class _LearningStore:
    def __init__(self):
        self.calls = []

    def add(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return {
            "ok": True,
            "stored": True,
        }


class LearningFollowupSemanticAuthorityTests(
    unittest.TestCase
):
    def setUp(self):
        followup_module.clear_learning_followup_context()

    def tearDown(self):
        followup_module.clear_learning_followup_context()

    def test_snapshot_contains_referent_not_authority(
        self,
    ):
        followup_module.set_learning_followup_context(
            "HTTP caching",
            now=100.0,
        )

        snapshot = (
            followup_module.get_learning_followup_context(
                now=120.0,
            )
        )

        self.assertEqual(
            set(snapshot),
            {
                "topic",
                "created_at",
            },
        )

        self.assertEqual(
            snapshot["topic"],
            "HTTP caching",
        )

        self.assertNotIn(
            "authority",
            snapshot,
        )

        self.assertNotIn(
            "token",
            snapshot,
        )

    def test_recent_goal_plus_url_resolves_followup_mode(
        self,
    ):
        followup_module.set_learning_followup_context(
            "HTTP caching",
            now=100.0,
        )

        snapshot = (
            followup_module.get_learning_followup_context(
                now=120.0,
            )
        )

        url = "https://example.com/docs"

        request = resolve_semantic_request(
            url,
            recent_turns=[],
            app_aliases={},
            learning_followup=snapshot,
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

        self.assertEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

        args = dict(
            request.tool_arguments
        )

        self.assertEqual(
            args["authority_mode"],
            "followup_url",
        )

        self.assertEqual(
            args["topic"],
            "HTTP caching",
        )

        self.assertEqual(
            args["query"],
            "HTTP caching",
        )

        self.assertEqual(
            args["source_url"],
            url,
        )

        self.assertFalse(
            args[
                "standing_public_web_read_only_grant"
            ]
        )

        self.assertNotIn(
            "direct_user_authority",
            args,
        )

        self.assertNotIn(
            "authorization_token",
            args,
        )

        self.assertNotIn(
            "authorized_payload",
            args,
        )

    def test_expired_context_does_not_bind_url(
        self,
    ):
        followup_module.set_learning_followup_context(
            "HTTP caching",
            now=100.0,
        )

        snapshot = (
            followup_module.get_learning_followup_context(
                now=401.0,
            )
        )

        self.assertIsNone(
            snapshot
        )

        request = resolve_semantic_request(
            "https://example.com/docs",
            recent_turns=[],
            app_aliases={},
            learning_followup=snapshot,
        )

        self.assertNotEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

    def test_private_url_does_not_bind(
        self,
    ):
        followup_module.set_learning_followup_context(
            "internal topic",
            now=100.0,
        )

        snapshot = (
            followup_module.get_learning_followup_context(
                now=120.0,
            )
        )

        request = resolve_semantic_request(
            "http://127.0.0.1/admin",
            recent_turns=[],
            app_aliases={},
            learning_followup=snapshot,
        )

        self.assertNotEqual(
            request.preferred_tool,
            "execute_authorized_external_learning",
        )

    def test_failed_goal_write_creates_no_context(
        self,
    ):
        with patch.object(
            followup_module,
            "_record_jarvis_learning_goal",
            return_value={
                "ok": False,
                "error": "TEST_FAILURE",
            },
        ):
            result = (
                followup_module.record_jarvis_learning_goal(
                    "HTTP caching",
                    source_text=(
                        "Jarvis, aprende HTTP caching"
                    ),
                )
            )

        self.assertFalse(
            result["ok"]
        )

        self.assertIsNone(
            followup_module.get_learning_followup_context()
        )

    def test_successful_goal_write_creates_context(
        self,
    ):
        with patch.object(
            followup_module,
            "_record_jarvis_learning_goal",
            return_value={
                "ok": True,
                "stored": True,
                "topic": "HTTP caching",
            },
        ):
            result = (
                followup_module.record_jarvis_learning_goal(
                    "HTTP caching",
                    source_text=(
                        "Jarvis, aprende HTTP caching"
                    ),
                )
            )

        self.assertTrue(
            result["ok"]
        )

        self.assertTrue(
            result[
                "followup_context_created"
            ]
        )

        snapshot = (
            followup_module.get_learning_followup_context()
        )

        self.assertEqual(
            snapshot["topic"],
            "HTTP caching",
        )

    def test_consumes_context_before_research_and_blocks_replay(
        self,
    ):
        topic = "HTTP caching"
        url = "https://example.com/docs"

        followup_module.set_learning_followup_context(
            topic
        )

        engine = _ResearchEngine()
        store = _LearningStore()

        old_engine = (
            external_module._RESEARCH_ENGINE
        )

        try:
            external_module._RESEARCH_ENGINE = engine

            with (
                patch.object(
                    external_module,
                    "authorized_learning",
                    return_value=store,
                ),
                patch.object(
                    external_module,
                    "autonomy_guardian",
                    side_effect=AssertionError(
                        "followup mode must not create "
                        "or consume an autonomy grant"
                    ),
                ),
            ):
                first = (
                    external_module.execute_authorized_external_learning(
                        topic=topic,
                        query=topic,
                        source_text=url,
                        deep=True,
                        scope="single_research_session",
                        source_url=url,
                        standing_public_web_read_only_grant=False,
                        authority_mode="followup_url",
                    )
                )

                call_count_after_first = len(
                    engine.url_calls
                )

                second = (
                    external_module.execute_authorized_external_learning(
                        topic=topic,
                        query=topic,
                        source_text=url,
                        deep=True,
                        scope="single_research_session",
                        source_url=url,
                        standing_public_web_read_only_grant=False,
                        authority_mode="followup_url",
                    )
                )

        finally:
            external_module._RESEARCH_ENGINE = (
                old_engine
            )

        self.assertTrue(
            first["ok"]
        )

        self.assertEqual(
            first["authority_mode"],
            "followup_url",
        )

        self.assertEqual(
            first["authorization"],
            "followup_context",
        )

        self.assertEqual(
            call_count_after_first,
            1,
        )

        self.assertFalse(
            second["ok"]
        )

        self.assertEqual(
            len(
                engine.url_calls
            ),
            1,
        )

        self.assertIsNone(
            followup_module.get_learning_followup_context()
        )

    def test_topic_tamper_fails_before_research(
        self,
    ):
        followup_module.set_learning_followup_context(
            "HTTP caching"
        )

        engine = _ResearchEngine()

        old_engine = (
            external_module._RESEARCH_ENGINE
        )

        try:
            external_module._RESEARCH_ENGINE = engine

            result = (
                external_module.execute_authorized_external_learning(
                    topic="credential dumping",
                    query="credential dumping",
                    source_text=(
                        "https://example.com/docs"
                    ),
                    deep=True,
                    scope="single_research_session",
                    source_url=(
                        "https://example.com/docs"
                    ),
                    standing_public_web_read_only_grant=False,
                    authority_mode="followup_url",
                )
            )

        finally:
            external_module._RESEARCH_ENGINE = (
                old_engine
            )

        self.assertFalse(
            result["ok"]
        )

        self.assertEqual(
            engine.url_calls,
            [],
        )

        snapshot = (
            followup_module.get_learning_followup_context()
        )

        self.assertEqual(
            snapshot["topic"],
            "HTTP caching",
        )


if __name__ == "__main__":
    unittest.main()
