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

    def test_local_pdf_sync_no_longer_bypasses_semantic_routing(self):
        loop = self.text.index("while True:")
        direct = self.text.index(
            "parse_direct_external_learning_order(",
            loop,
        )
        generic = self.text.index(
            "process_request(",
            direct,
        )

        pre_pipeline = self.text[
            loop:generic
        ]

        self.assertNotIn(
            'read_tool("sync_book_library"',
            pre_pipeline,
        )

        self.assertNotIn(
            "if local_pdf_library_learning_requested(text):",
            pre_pipeline,
        )

        self.assertLess(
            direct,
            generic,
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

    def test_learning_followup_clock_uses_imported_monotonic(self):
        self.assertNotIn('learning_followup_state["created_at"] = time()', self.text)
        self.assertIn('learning_followup_state["created_at"] = monotonic()', self.text)

    def test_direct_url_uses_bounded_research_url_path(self):
        start = self.text.index("def execute_direct_external_learning(")
        end = self.text.index("def request_external_learning_for_goal(", start)
        block = self.text[start:end]
        self.assertIn("source_url", block)
        self.assertIn("research_engine.research_url(", block)
        self.assertIn("Não executo downloads arbitrários, comandos", block)


if __name__ == "__main__":
    unittest.main()
