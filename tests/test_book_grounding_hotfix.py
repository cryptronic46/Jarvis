import tempfile
import unittest
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.services.book_library import BookLibrary
from jarvis_core.services.performance import PerformancePlan
from jarvis_core.services.response_completion import (
    continuation_is_meta,
    strip_internal_continuation,
)


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class BookGroundingHotfixTests(unittest.TestCase):
    def test_exact_failed_question_requires_book_library(self):
        question = (
            "Jarvis, segundo os meus livros, como se formam "
            "os adjetivos masculinos?"
        )
        self.assertTrue(JarvisBrain._book_library_requested(question))
        self.assertFalse(
            JarvisBrain._book_library_requested(
                "Como se formam os adjetivos masculinos?"
            )
        )

    def test_book_context_is_retrieved_without_model_tool_choice(self):
        class _Library:
            def __init__(self):
                self.query = ""

            def search(self, query, limit=5):
                self.query = query
                return {
                    "ok": True,
                    "results": [{
                        "title": "Guia de Gramática Portuguesa",
                        "path": "gramatica.pdf",
                        "page": 37,
                        "citation": "Guia de Gramática Portuguesa, p. 37",
                        "excerpt": "As regras são explicadas nas páginas 9, 10 e 11.",
                    }],
                }

            def referenced_pages(self, rows, limit=6):
                return [{
                    "title": "Guia de Gramática Portuguesa",
                    "path": "gramatica.pdf",
                    "page": 9,
                    "citation": "Guia de Gramática Portuguesa, p. 9",
                    "excerpt": "Regra de formação do masculino.",
                    "referenced_by_match": True,
                }]

        library = _Library()
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.events = _Events()
        question = (
            "Jarvis, segundo os meus livros, como se formam "
            "os adjetivos masculinos?"
        )
        with patch("jarvis_core.core.brain.book_library", return_value=library):
            result = brain._book_library_context(question)

        self.assertEqual(library.query, "os adjetivos masculinos")
        self.assertTrue(result["requested"])
        self.assertEqual(result["results"], 1)
        self.assertIn("RAG local e obrigatório", result["context"])
        self.assertIn("Guia de Gramática Portuguesa, p. 37", result["context"])
        self.assertIn("Guia de Gramática Portuguesa, p. 9", result["context"])
        self.assertTrue(
            any(name == "BOOK_LIBRARY_RETRIEVED" for name, _ in brain.events.rows)
        )

    def test_referenced_pages_are_loaded_from_the_same_book(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library = BookLibrary(root / "books", root / "library.sqlite3")
            library._replace_book(
                relative_path="gramatica.pdf",
                digest="abc",
                title="Guia",
                page_count=3,
                pages=[
                    (1, "Adjetivos masculinos: consultar páginas 2 e 3."),
                    (2, "Primeira regra do masculino."),
                    (3, "Segunda regra do masculino."),
                ],
                status="indexed",
            )
            found = library.search("adjetivos masculinos", limit=3)
            expanded = library.referenced_pages(found["results"])
            self.assertEqual(
                [row["page"] for row in expanded],
                [2, 3],
            )
            self.assertTrue(all(row["referenced_by_match"] for row in expanded))

    def test_grounding_appends_real_citations_when_model_omits_them(self):
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.events = _Events()
        result = brain._ground_book_answer(
            "A regra indicada no excerto é esta.",
            {
                "requested": True,
                "citations": ["Guia de Gramática Portuguesa, p. 37"],
            },
        )
        self.assertIn("Fontes consultadas", result)
        self.assertIn("Guia de Gramática Portuguesa, p. 37", result)

    def test_navigation_only_source_refuses_to_fill_the_gap_with_general_knowledge(self):
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.events = _Events()
        result = brain._ground_book_answer(
            "Uma regra geral não confirmada.",
            {
                "requested": True,
                "citations": ["Guia de Gramática Portuguesa, p. 37"],
                "navigation_only": True,
                "reference_citations": ["Guia de Gramática Portuguesa, p. 9"],
            },
        )
        self.assertIn("não vou completar essa lacuna", result)
        self.assertIn("Guia de Gramática Portuguesa, p. 37", result)
        self.assertIn("Guia de Gramática Portuguesa, p. 9", result)
        self.assertNotIn("Uma regra geral", result)
    def test_grounding_refuses_to_invent_when_library_has_no_match(self):
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.events = _Events()
        result = brain._ground_book_answer(
            "Vou responder com conhecimento geral.",
            {"requested": True, "citations": []},
        )
        self.assertIn("Não encontrei", result)
        self.assertNotIn("conhecimento geral", result)

    def test_exact_leaked_continuation_instruction_is_rejected_and_stripped(self):
        leaked = (
            "do ponto onde parou, sem reiniciar, sem repetir conteúdo e sem "
            "comentar este pedido de continuação. Conclui a resposta naturalmente."
        )
        self.assertTrue(continuation_is_meta(leaked))
        combined = (
            "A primeira frase está completa. Exemplo: importante (mas "
            + leaked
        )
        self.assertEqual(
            strip_internal_continuation(combined),
            "A primeira frase está completa.",
        )

    def test_runtime_rejects_the_exact_leaked_continuation_segment(self):
        class _Client:
            def chat(self, **kwargs):
                return SimpleNamespace(
                    done_reason="stop",
                    eval_count=34,
                    message=SimpleNamespace(
                        content=(
                            "do ponto onde parou, sem reiniciar, sem repetir "
                            "conteúdo e sem comentar este pedido de continuação. "
                            "Conclui a resposta naturalmente."
                        ),
                        tool_calls=[],
                    ),
                )

        brain = JarvisBrain.__new__(JarvisBrain)
        brain.settings = SimpleNamespace(
            model="qwen-test",
            llm_auto_continue_truncated=True,
            llm_max_continuations=3,
            llm_continuation_num_predict=360,
            llm_temperature=0.2,
        )
        brain.events = _Events()
        brain.client = _Client()
        brain.messages = [
            {"role": "system", "content": "You are JARVIS."},
            {"role": "user", "content": "Explica."},
        ]
        brain._lock = RLock()
        brain._loaded_models = set()
        brain._model_loaded = False
        plan = PerformancePlan(
            profile="fast",
            reason="test",
            pressure="normal",
            think=False,
            num_ctx=4096,
            num_predict=96,
            max_tool_rounds=1,
            history_messages=4,
            max_tools=0,
            keep_alive="5m",
        )
        result = brain._complete_truncated_response(
            initial_response=SimpleNamespace(done_reason="length", eval_count=96),
            initial_content=(
                "A primeira frase está completa. Exemplo: importante (mas"
            ),
            plan=plan,
            cyber_context="",
            learning_context="",
            request_contract="intent=GENERAL",
            requested_predict=96,
        )
        self.assertEqual(result, "A primeira frase está completa.")
        self.assertTrue(
            any(
                name == "RESPONSE_CONTINUATION_META_REJECTED"
                for name, _ in brain.events.rows
            )
        )

    def test_book_retrieval_precedes_model_and_gets_larger_budget(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        retrieval = source.index(
            "book_retrieval = self._book_library_context(effective_query)"
        )
        model_request = source.index("response = self.client.chat(**kwargs)")
        self.assertLess(retrieval, model_request)
        self.assertIn(
            'if book_retrieval.get("requested"):\n'
            "            model_num_predict = max(model_num_predict, 320)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
