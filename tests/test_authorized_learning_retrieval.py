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

    def test_topic_weighting_prefers_tcp_over_incidental_nmap_mention(self):
        with tempfile.TemporaryDirectory() as td:
            store = AuthorizedLearningStore(Path(td) / "learning.jsonl")
            store.add(topic="Nmap", query="manual Nmap", summary="O Nmap pode observar portas TCP durante inventários de rede.", model="qwen-test", authorization_token="OWNER", sources=[{"title":"Nmap Book","url":"https://nmap.org/book/"}])
            store.add(topic="TCP", query="protocolo TCP", summary="TCP oferece transporte fiável, ordenado e orientado à ligação.", model="qwen-test", authorization_token="OWNER", sources=[{"title":"RFC 9293 TCP","url":"https://www.rfc-editor.org/rfc/rfc9293.html"}])
            found = store.search("TCP", limit=5)
            self.assertEqual(found["results"][0]["topic"], "TCP")
            self.assertEqual([row["topic"] for row in found["results"]], ["TCP"])

    def test_single_incidental_summary_term_is_not_verified_topic_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            store = AuthorizedLearningStore(Path(td) / "learning.jsonl")
            store.add(topic="Nmap", query="manual Nmap", summary="Uma nota incidental menciona DNS e outros serviços de rede.", model="qwen-test", authorization_token="OWNER", sources=[{"title":"Nmap Book","url":"https://nmap.org/book/"}])
            found = store.search("DNS", limit=5)
            self.assertEqual(found["count"], 0)
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
