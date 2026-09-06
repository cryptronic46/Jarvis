import unittest
from pathlib import Path


class DirectLearningExecutionContractTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

    def test_direct_learning_is_resolved_by_semantic_authority(self):
        from jarvis_core.services.semantic_intent import (
            resolve_semantic_request,
        )

        text = (
            "Jarvis, pesquisa na Internet "
            "e aprende sobre HTTP caching"
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

        self.assertEqual(
            request.confidence,
            0.99,
        )

    def test_direct_authority_is_logged_not_granted_reusably(self):
        autonomy = Path("jarvis_core/services/autonomy.py").read_text(encoding="utf-8")
        start = autonomy.index("def record_direct_authorization(")
        end = autonomy.index("def authorize(", start)
        block = autonomy[start:end]
        self.assertIn('"reusable": False', block)
        self.assertIn('"remaining_uses": 0', block)
        self.assertNotIn('state["grants"].append', block)

    def test_isolated_url_binds_only_to_live_explicit_learning_context(self):
        from jarvis_core.services.learning_followup import (
            clear_learning_followup_context,
            get_learning_followup_context,
            set_learning_followup_context,
        )
        from jarvis_core.services.semantic_intent import (
            resolve_semantic_request,
        )

        url = "https://example.com/docs"

        clear_learning_followup_context()

        try:
            without_context = (
                resolve_semantic_request(
                    url,
                    recent_turns=[],
                    app_aliases={},
                    learning_followup=None,
                )
            )

            self.assertNotEqual(
                without_context.preferred_tool,
                "execute_authorized_external_learning",
            )

            set_learning_followup_context(
                "HTTP caching",
                now=100.0,
            )

            live = (
                get_learning_followup_context(
                    now=120.0,
                )
            )

            self.assertIsNotNone(
                live
            )

            request = (
                resolve_semantic_request(
                    url,
                    recent_turns=[],
                    app_aliases={},
                    learning_followup=live,
                )
            )

            args = dict(
                request.tool_arguments
            )

            self.assertEqual(
                request.preferred_tool,
                "execute_authorized_external_learning",
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
                args["source_url"],
                url,
            )

            expired = (
                get_learning_followup_context(
                    now=401.0,
                )
            )

            self.assertIsNone(
                expired
            )

        finally:
            clear_learning_followup_context()
    def test_direct_learning_uses_authoritative_external_service_contract(self):
        external = Path(
            "jarvis_core/services/external_learning.py"
        ).read_text(
            encoding="utf-8"
        )

        start = external.index(
            "def execute_authorized_external_learning("
        )

        block = external[
            start:
        ]

        current_turn = block.index(
            'if mode == "current_turn":'
        )

        revalidation = block.index(
            "parse_direct_external_learning_order(",
            current_turn,
        )

        network_candidates = [
            position
            for position in (
                block.find(
                    "_RESEARCH_ENGINE.research_url(",
                    revalidation,
                ),
                block.find(
                    "_RESEARCH_ENGINE.research(",
                    revalidation,
                ),
            )
            if position >= 0
        ]

        self.assertTrue(
            network_candidates
        )

        network = min(
            network_candidates
        )

        store = block.index(
            "authorized_learning().add(",
            network,
        )

        self.assertLess(
            current_turn,
            revalidation,
        )

        self.assertLess(
            revalidation,
            network,
        )

        self.assertLess(
            network,
            store,
        )

        self.assertIn(
            "authorized_direct_web_local_model_summary_v2",
            block,
        )

        self.assertNotIn(
            "cloud_brain.ask(",
            block,
        )


if __name__ == "__main__":
    unittest.main()
