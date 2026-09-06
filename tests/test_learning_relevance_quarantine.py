import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.autonomy import AuthorizedLearningStore


class LearningRelevanceQuarantineTests(unittest.TestCase):
    def test_store_rejects_new_topic_summary_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuthorizedLearningStore(Path(tmp) / "authorized_learning.jsonl")
            result = store.add(
                topic="cybersegurança",
                query="aprende cybersegurança",
                summary="Kosovo fica nos Balcãs e Pristina é a capital.",
                model="qwen3:8b",
                authorization_token="DIRECT",
                sources=[],
                source_type="authorized_direct_web_local_model_summary",
            )
            self.assertFalse(result["ok"])
            self.assertFalse(result["stored"])
            self.assertEqual(result["error"], "LEARNING_TOPIC_MISMATCH")
            self.assertEqual(store.rows(), [])

    def test_existing_bad_direct_web_learning_is_quarantined_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "authorized_learning.jsonl"
            bad = {
                "timestamp": "2026-08-30T14:00:00+01:00",
                "topic": "cybersegurança",
                "query": "usa a internet para aprenderes mais sobre cybersegurança",
                "summary": "Kosovo é uma república nos Balcãs. A capital é Pristina e existem avisos de viagem.",
                "model": "qwen3:8b",
                "authorization_token": "DIRECT",
                "source_type": "authorized_direct_web_local_model_summary",
                "sources": [{"title": "Kosovo", "url": "https://example.org/kosovo", "provider": "bing_rss"}],
                "authority": "explicit_owner_authorization",
            }
            good = {
                "timestamp": "2026-08-30T14:01:00+01:00",
                "topic": "comportamento humano",
                "query": "aprende comportamento humano",
                "summary": "O comportamento humano resulta da interação entre cognição, emoção, ambiente e relações sociais.",
                "model": "qwen3:8b",
                "authorization_token": "DIRECT",
                "source_type": "authorized_direct_web_local_model_summary",
                "sources": [],
                "authority": "explicit_owner_authorization",
            }
            path.write_text(
                json.dumps(bad, ensure_ascii=False) + "\n" + json.dumps(good, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            store = AuthorizedLearningStore(path)
            active = store.rows()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["topic"], "comportamento humano")
            self.assertEqual(store.last_repair["quarantined"], 1)

            quarantine = store.quarantine_path
            self.assertTrue(quarantine.exists())
            rows = [json.loads(line) for line in quarantine.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["quarantine_reason"], "topic_summary_mismatch")
            self.assertEqual(rows[0]["original"]["topic"], "cybersegurança")

    def test_relevant_cybersecurity_summary_is_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuthorizedLearningStore(Path(tmp) / "authorized_learning.jsonl")
            result = store.add(
                topic="cybersegurança",
                query="aprende cybersegurança",
                summary="Cybersecurity protects systems, networks and data against digital attacks and unauthorized access.",
                model="qwen3:8b",
                authorization_token="DIRECT",
                sources=[],
                source_type="authorized_direct_web_local_model_summary",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["stored"])
            self.assertEqual(len(store.rows()), 1)

    def test_external_service_never_emits_success_before_store_acceptance(self):
        text = Path(
            "jarvis_core/services/external_learning.py"
        ).read_text(
            encoding="utf-8"
        )

        start = text.index(
            "def execute_authorized_external_learning("
        )

        block = text[
            start:
        ]

        store = block.index(
            "stored = authorized_learning().add("
        )

        reject_ok = block.index(
            'not stored.get("ok")',
            store,
        )

        reject_stored = block.index(
            'not stored.get("stored")',
            reject_ok,
        )

        success_event = block.index(
            "if _EVENTS is not None:",
            reject_stored,
        )

        self.assertLess(
            store,
            reject_ok,
        )

        self.assertLess(
            reject_ok,
            reject_stored,
        )

        self.assertLess(
            reject_stored,
            success_event,
        )

        self.assertIn(
            "LEARNING_STORE_REJECTED",
            text,
        )

        self.assertIn(
            "SEARCH_RESULTS_IRRELEVANT",
            text,
        )

        self.assertIn(
            "FETCHED_SOURCES_IRRELEVANT",
            text,
        )


if __name__ == "__main__":
    unittest.main()
