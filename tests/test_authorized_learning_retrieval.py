import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.autonomy import AuthorizedLearningStore


class AuthorizedLearningRetrievalTests(unittest.TestCase):
    def test_search_matches_humano_and_humanos_without_generic_stopwords(self):
        with tempfile.TemporaryDirectory() as td:
            store = AuthorizedLearningStore(Path(td) / "learning.jsonl")
            store.add(
                topic="comportamento humano",
                query="aprender sobre comportamento humano",
                summary="A cooperação e o contexto social influenciam o comportamento humano.",
                model="qwen-test",
                authorization_token="ABC123",
            )
            found = store.search("O que sabes sobre humanos?")
            self.assertEqual(found["count"], 1)
            self.assertEqual(found["results"][0]["topic"], "comportamento humano")
            unrelated = store.search("O que sabes sobre impressoras?")
            self.assertEqual(unrelated["count"], 0)

    def test_brain_contract_injects_learning_request_scoped(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("def _authorized_learning_context(", text)
        self.assertIn("search_authorized_learning(", text)
        self.assertIn("learning_context = self._authorized_learning_context(effective_query)", text)
        self.assertIn("learning_context: str = \"\"", text)
        self.assertIn('"role": "system",', text)
        self.assertIn("AUTHORIZED_LEARNING_RETRIEVED", text)
        self.assertIn("responde concretamente", text)


if __name__ == "__main__":
    unittest.main()
