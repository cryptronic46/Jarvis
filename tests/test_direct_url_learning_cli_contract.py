import unittest

from jarvis_core.cli import local_pdf_library_learning_requested
from pathlib import Path


class DirectUrlLearningCliContractTests(unittest.TestCase):
    def test_all_local_pdfs_are_not_misrouted_to_external_learning(self):
        self.assertTrue(
            local_pdf_library_learning_requested(
                "Jarvis, aprende todos os documentos PDF"
            )
        )
        self.assertFalse(
            local_pdf_library_learning_requested(
                "Jarvis, aprende Python através da Internet"
            )
        )

    @classmethod
    def setUpClass(cls):
        cls.text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")

    def test_local_pdf_sync_has_no_pre_semantic_execution_bypass(self):
        self.assertNotIn(
            'read_tool("sync_book_library"',
            self.text,
        )

        self.assertNotIn(
            "if local_pdf_library_learning_requested(text):",
            self.text,
        )

        self.assertIn(
            "route_runtime_request(",
            self.text,
        )

        self.assertIn(
            "resolve_semantic_request(",
            self.text,
        )

    def test_local_pdf_sync_resolves_to_authoritative_tool(self):
        from jarvis_core.services.semantic_intent import (
            resolve_semantic_request,
        )

        cases = (
            "Jarvis, aprende todos os PDFs da biblioteca.",
            "Estuda todos os documentos PDF.",
            "Indexa todos os PDFs.",
        )

        for text in cases:
            with self.subTest(text=text):
                request = resolve_semantic_request(
                    text
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
                    "SYSTEM",
                )

                self.assertEqual(
                    request.action,
                    "sync_library",
                )

                self.assertEqual(
                    request.target,
                    "local_pdf_library",
                )

                self.assertTrue(
                    request.requires_tool
                )

                self.assertEqual(
                    request.preferred_tool,
                    "sync_book_library",
                )

                self.assertEqual(
                    request.tool_arguments,
                    {
                        "force": False,
                    },
                )

                self.assertEqual(
                    request.confidence,
                    0.99,
                )

    def test_learning_followup_context_expires_after_300_seconds(self):
        from jarvis_core.services.learning_followup import (
            clear_learning_followup_context,
            get_learning_followup_context,
            set_learning_followup_context,
        )

        clear_learning_followup_context()

        try:
            set_learning_followup_context(
                "HTTP caching",
                now=100.0,
            )

            at_limit = (
                get_learning_followup_context(
                    now=400.0,
                )
            )

            self.assertIsNotNone(
                at_limit
            )

            expired = (
                get_learning_followup_context(
                    now=400.001,
                )
            )

            self.assertIsNone(
                expired
            )

        finally:
            clear_learning_followup_context()

    def test_followup_url_resolves_to_bounded_authoritative_tool(self):
        from jarvis_core.services.learning_followup import (
            clear_learning_followup_context,
            get_learning_followup_context,
            set_learning_followup_context,
        )
        from jarvis_core.services.semantic_intent import (
            resolve_semantic_request,
        )

        clear_learning_followup_context()

        try:
            set_learning_followup_context(
                "HTTP caching",
                now=100.0,
            )

            snapshot = (
                get_learning_followup_context(
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

            args = dict(
                request.tool_arguments
            )

            self.assertEqual(
                request.intent,
                "RESEARCH",
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
                args["authority_mode"],
                "followup_url",
            )

            self.assertEqual(
                args["scope"],
                "single_research_session",
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

        finally:
            clear_learning_followup_context()
if __name__ == "__main__":
    unittest.main()
