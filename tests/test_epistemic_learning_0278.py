import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.services.learning_gap import (
    assess_learning_gap,
    assess_studied_coverage,
    contains_secret_hints,
    deterministic_confidence_from_sources,
    extract_learning_topic,
    knowledge_state,
)


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append((name, payload))


class _Local:
    def __init__(self, text):
        self.text = text

    def ask(self, _query):
        return self.text

    def clear_history(self):
        return None


class _Research:
    def available(self):
        return True


class _Autonomy:
    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "pending": True,
            "allowed": False,
            "token": "ABC123",
            "message": "Senhor, autorização necessária: /authorize ABC123.",
        }

    def has_standing_public_web_research(self):
        return False


class _Cloud:
    def __init__(self, available=False):
        self._available = available

    def available(self):
        return self._available

    def consult(self, text, deep=True):
        raise AssertionError("consult must not run before authorization")

    def clear_history(self):
        return None


class _Store:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def rows(self):
        return list(self._rows)


class EpistemicLearning0278Tests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(
            model="qwen-local",
            autonomy_enabled=True,
            autonomy_proactive_learning_enabled=True,
            epistemic_learning_enabled=True,
            epistemic_learning_stale_days=120,
            expert_escalation_enabled=True,
            external_ai_complexity_threshold=4,
        )

    def test_topic_extraction(self):
        self.assertEqual(extract_learning_topic("O que é OpenWakeWord?"), "OpenWakeWord")

    def test_explicit_local_gap_without_study_requests_learning(self):
        assessment = assess_learning_gap(
            "O que é OpenWakeWord?",
            "Não sei responder com confiança.",
            _Store(),
        )
        self.assertTrue(assessment.needs_learning)
        self.assertFalse(assessment.studied)
        self.assertEqual(assessment.topic, "OpenWakeWord")

    def test_existing_strong_study_prevents_relearning(self):
        store = _Store([{
            "timestamp": "2026-08-31T12:00:00+01:00",
            "topic": "OpenWakeWord",
            "summary": "Resumo técnico",
        }])
        coverage = assess_studied_coverage(store, "OpenWakeWord", stale_days=120)
        self.assertTrue(coverage["studied"])
        self.assertFalse(coverage["stale"])

    def test_knowledge_state_reports_known_stale_unknown(self):
        current = _Store([{
            "timestamp": "2026-08-31T12:00:00+01:00",
            "topic": "OpenWakeWord",
            "summary": "Resumo técnico",
            "confidence": 0.9,
            "source_count": 3,
        }])
        self.assertEqual(knowledge_state(current, "OpenWakeWord", stale_days=120)["state"], "KNOWN")
        self.assertEqual(knowledge_state(_Store(), "OpenWakeWord", stale_days=120)["state"], "UNKNOWN")

    def test_learning_confidence_tracks_source_count(self):
        self.assertGreater(
            deterministic_confidence_from_sources([
                {"url": "https://a.example"},
                {"url": "https://b.example"},
                {"url": "https://c.example"},
            ]),
            deterministic_confidence_from_sources([{"url": "https://a.example"}]),
        )

    def test_hybrid_gap_asks_before_web_and_does_not_call_cloud(self):
        autonomy = _Autonomy()
        hybrid = HybridBrain(
            self.settings(),
            _Events(),
            local_brain=_Local("Não sei responder com confiança."),
            cloud_brain=_Cloud(available=True),
            autonomy=autonomy,
            research_engine=_Research(),
        )
        with patch("jarvis_core.core.hybrid_brain.authorized_learning", return_value=_Store()):
            result = hybrid.ask("O que é OpenWakeWord?")
        self.assertEqual(result.route, "AUTH/LEARNING")
        self.assertEqual(autonomy.calls[-1]["capability"], "external_learning")
        self.assertEqual(autonomy.calls[-1]["action"], "external_learning_resume_query")
        self.assertIn("original_query", autonomy.calls[-1]["payload"])

    def test_after_existing_study_insufficient_answer_never_offers_external_ai(self):
        autonomy = _Autonomy()
        cloud = _Cloud(available=True)
        hybrid = HybridBrain(
            self.settings(),
            _Events(),
            local_brain=_Local("Não sei responder com confiança."),
            cloud_brain=cloud,
            autonomy=autonomy,
            research_engine=_Research(),
        )
        store = _Store([{
            "timestamp": "2026-08-31T12:00:00+01:00",
            "topic": "OpenWakeWord",
            "summary": "Resumo técnico",
        }])
        with patch("jarvis_core.core.hybrid_brain.authorized_learning", return_value=store):
            result = hybrid.ask("O que é OpenWakeWord?")
        self.assertNotEqual(result.route, "AUTH/PENDING")
        self.assertFalse(any(x.get("capability") == "cloud_reasoning" for x in autonomy.calls))

    def test_secret_hint_blocks_automatic_external_expert_offer(self):
        self.assertTrue(contains_secret_hints("A minha API key é sk-abcdefghijklmnopqrstuvwxyz"))


if __name__ == "__main__":
    unittest.main()
