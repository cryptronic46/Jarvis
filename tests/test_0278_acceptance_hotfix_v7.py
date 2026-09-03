import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis_core.services.autonomy import AuthorizedLearningStore
from jarvis_core.services.local_research import LocalResearchEngine, ResearchSource


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


class AcceptanceHotfixV7Tests(unittest.TestCase):
    def test_version_hint_prefers_highest_stable_exact_topic_version(self):
        source = ResearchSource(
            title="Download Python",
            url="https://www.python.org/downloads/",
            text=(
                "Active Python releases: Python 3.15 pre-release. "
                "Looking for a specific release? Python 3.14.7 Aug 5 2026. "
                "Python 3.14.6 June 10 2026. Python 3.13.15 Aug 5 2026. "
                "Python 3.12.14 Aug 12 2026. Python 3.11.4 June 6 2023."
            ),
            provider="direct_url",
        )
        hint = LocalResearchEngine._version_candidates_from_sources(
            "Qual é a versão atual do Python?",
            "a versão atual do Python",
            [source],
        )
        self.assertTrue(hint["applicable"])
        self.assertEqual(hint["candidate"], "3.14.7")

    def test_grounding_rejects_unsupported_model_version_claim(self):
        source = ResearchSource(
            title="Download Python",
            url="https://www.python.org/downloads/",
            text="Python 3.14.7 Aug 5 2026. Python 3.13.15 Aug 5 2026.",
            provider="direct_url",
        )
        check = LocalResearchEngine._validate_synthesis_grounding(
            "A versão atual é Python 3.99.1 [S1].",
            query="Qual é a versão atual do Python?",
            topic="a versão atual do Python",
            sources=[source],
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["reason"], "UNSUPPORTED_VERSION_CLAIM")

    def test_grounding_rejects_stale_but_sourced_version_when_newer_candidate_exists(self):
        source = ResearchSource(
            title="Download Python",
            url="https://www.python.org/downloads/",
            text="Python 3.14.7 Aug 5 2026. Python 3.11.4 June 6 2023.",
            provider="direct_url",
        )
        check = LocalResearchEngine._validate_synthesis_grounding(
            "A versão atual é Python 3.11.4 [S1].",
            query="Qual é a versão atual do Python?",
            topic="a versão atual do Python",
            sources=[source],
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["reason"], "FRESHNESS_VERSION_MISMATCH")
        self.assertEqual(check["expected_source_candidate"], "3.14.7")

    def test_grounding_rejects_fake_external_source_claim(self):
        source = ResearchSource(
            title="Download Python",
            url="https://www.python.org/downloads/",
            text="Python 3.14.7 Aug 5 2026.",
            provider="direct_url",
        )
        check = LocalResearchEngine._validate_synthesis_grounding(
            "Com base em informações externas confiáveis, Python 3.14.7 é a versão atual.",
            query="Qual é a versão atual do Python?",
            topic="a versão atual do Python",
            sources=[source],
        )
        self.assertFalse(check["ok"])
        self.assertEqual(check["reason"], "UNSUPPORTED_EXTERNAL_SOURCE_CLAIM")

    def test_direct_url_rejects_stale_local_synthesis_instead_of_storing_it(self):
        settings = SimpleNamespace(
            local_research_enabled=True,
            local_research_fetch_max_bytes=300000,
            local_research_timeout_seconds=2.0,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=1,
            model="qwen-test",
        )
        local = Mock()
        local.synthesize_research.return_value = "A versão atual é Python 3.11.4 [S1]."
        engine = LocalResearchEngine(settings, _Events(), local)
        engine._validate_public_url = lambda url: url
        engine._get = lambda url, *, max_bytes, timeout: (
            (
                "<html><title>Download Python</title><body>"
                "Python 3.14.7 Aug 5 2026. Python 3.11.4 June 6 2023."
                "</body></html>"
            ).encode("utf-8"),
            "text/html",
            "https://www.python.org/downloads/",
        )
        result = engine.research_url(
            "https://www.python.org/downloads/",
            query="Estuda o URL e diz-me qual é a versão atual do Python.",
            topic="a versão atual do Python",
            deep=False,
        )
        # v10 fails closed on the stale model answer but can still answer from
        # deterministic source extraction when the current version is literal
        # in the fetched page. The stale 3.11.4 claim must never escape.
        self.assertTrue(result.ok)
        self.assertEqual(result.model, "deterministic-source-extractor")
        self.assertIn("3.14.7", result.text)
        self.assertNotIn("3.11.4", result.text)

    def test_legacy_freshness_learning_is_quarantined_not_retrieved(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            bad = {
                "timestamp": "2026-09-01T15:00:00+01:00",
                "learned_at": "2026-09-01T15:00:00+01:00",
                "topic": "a versão atual do Python",
                "query": "qual é a versão atual do Python",
                "summary": "A versão atual estável do Python é 3.11.4.",
                "source_type": "authorized_direct_web_local_model_summary",
                "authority": "explicit_owner_authorization",
                "sources": [{"url": "https://www.python.org/downloads/"}],
            }
            path.write_text(json.dumps(bad, ensure_ascii=False) + "\n", encoding="utf-8")
            store = AuthorizedLearningStore(path)
            self.assertEqual(store.last_repair["quarantined"], 1)
            self.assertEqual(store.search("versão atual do Python")["count"], 0)
            quarantine = path.with_name("authorized_learning_quarantine.jsonl").read_text(encoding="utf-8")
            self.assertIn("legacy_freshness_learning_unverified", quarantine)
            self.assertIn("3.11.4", quarantine)

    def test_new_grounded_freshness_learning_remains_active(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authorized_learning.jsonl"
            store = AuthorizedLearningStore(path)
            added = store.add(
                topic="a versão atual do Python",
                query="qual é a versão atual do Python",
                summary="A versão atual estável do Python é 3.14.7.",
                model="qwen-test",
                authorization_token="STANDING",
                sources=[{"title": "Download Python", "url": "https://www.python.org/downloads/", "provider": "direct_url"}],
                source_type="authorized_direct_web_local_model_summary_v2",
            )
            self.assertTrue(added["stored"])
            found = store.search("versão atual do Python")
            self.assertEqual(found["count"], 1)
            self.assertEqual(found["results"][0]["grounding_schema"], "source_claim_v2")

    def test_cli_writes_grounded_direct_web_source_type(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertNotIn('source_type="authorized_direct_web_local_model_summary"', text)
        self.assertGreaterEqual(text.count('source_type="authorized_direct_web_local_model_summary_v2"'), 2)

    def test_brain_research_prompt_forbids_internal_freshness_guessing(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("não uses memória interna nem conhecimento prévio", text)
        self.assertIn("Não introduzas números de versão", text)
        self.assertIn("remaining_source_chars = 12000", text)


if __name__ == "__main__":
    unittest.main()
