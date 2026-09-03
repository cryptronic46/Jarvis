import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.autonomy import (
    AuthorizedLearningStore,
    parse_direct_external_learning_order,
    parse_learning_goal,
)
from jarvis_core.services.personal_cognition import PersonalCognitionStore


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _Apps:
    def list_apps(self):
        return []


class _LearningTools:
    def __init__(self, rows=None):
        self.request_started_at = 0
        self.calls = []
        self.rows = list(rows or [])

    def execute(self, name, args=None):
        self.calls.append((name, args or {}))
        if name == "search_authorized_learning":
            return json.dumps({"ok": True, "results": self.rows, "count": len(self.rows)})
        return json.dumps({"ok": True})


class LearningConsentGrounding0278Tests(unittest.TestCase):
    def test_plain_learning_goal_never_becomes_web_authority(self):
        text = (
            "Não, eu quero que tu aprendas sobre comportamento humano e sobre programação. "
            "Não significa que tenho uma paixão sobre comportamento humano ou programação."
        )
        self.assertIsNone(parse_direct_external_learning_order(text))
        goal = parse_learning_goal(text)
        self.assertIsNotNone(goal)
        self.assertEqual(goal["topic"], "comportamento humano e programação")
        self.assertTrue(goal["local_only"])
        self.assertFalse(goal["web_requested"])
        self.assertNotIn("query", goal)

    def test_personal_cognition_does_not_turn_jarvis_learning_into_owner_trait(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalCognitionStore(Path(tmp) / "memory")
            result = store.observe_interaction(
                "Quero que tu aprendas sobre comportamento humano e programação.",
                "OK",
                "LOCAL",
            )
            self.assertTrue(result["ok"])
            model = store.model()
            self.assertEqual(model.get("goals") or [], [])
            self.assertEqual(model.get("preferences") or [], [])
            self.assertEqual(model.get("topic_counts") or {}, {})

            saved = store.record_jarvis_learning_goal(
                "comportamento humano e programação",
                source_text="Quero que tu aprendas sobre comportamento humano e programação.",
            )
            self.assertTrue(saved["ok"])
            self.assertEqual(
                store.model()["jarvis_learning_goals"][-1]["topic"],
                "comportamento humano e programação",
            )

    def test_migrates_old_misclassified_owner_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = Path(tmp) / "memory"
            memory.mkdir(parents=True)
            (memory / "personal_model.json").write_text(
                json.dumps({
                    "interaction_count": 1,
                    "preferences": [],
                    "goals": [{
                        "statement": "que tu aprendas sobre comportamento humano",
                        "confidence": 1.0,
                        "source": "explicit-user-statement",
                    }],
                    "constraints": [],
                    "projects": [],
                    "topic_counts": {},
                    "recent_topics": [],
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            store = PersonalCognitionStore(memory)
            model = store.model()
            self.assertEqual(model.get("goals") or [], [])
            self.assertEqual(
                model.get("jarvis_learning_goals", [])[-1]["topic"],
                "comportamento humano",
            )

    def test_generic_learning_search_returns_recent_verified_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AuthorizedLearningStore(Path(tmp) / "authorized_learning.jsonl")
            store.add(
                topic="redes TCP/IP",
                query="pesquisa redes",
                summary="Resumo verificado sobre redes.",
                model="local",
                authorization_token="DIRECT",
                sources=[],
                source_type="authorized_web_research_model_summary",
            )
            result = store.search("o que aprendeste jarvis?", limit=3)
            self.assertEqual(result["mode"], "recent_verified_learning")
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["results"][0]["topic"], "redes TCP/IP")

    def test_fast_recall_uses_only_learning_journal(self):
        tools = _LearningTools([{
            "topic": "comportamento humano",
            "summary": "Síntese guardada e verificada.",
        }])
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("O que aprendeste Jarvis?")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "verified_learning_recall")
        self.assertEqual(result.tool, "search_authorized_learning")
        self.assertIn("aprendizagem verificada", result.response)
        self.assertEqual(tools.calls[0][0], "search_authorized_learning")
        self.assertEqual(tools.calls[0][1]["query"], "")

    def test_fast_recall_with_no_record_does_not_invent_learning(self):
        tools = _LearningTools([])
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("O que aprendeste Jarvis? eu não te dei permissão")
        self.assertTrue(result.handled)
        self.assertIn("Não tenho uma aprendizagem Web verificada", result.response)
        self.assertIn("não conta como algo que aprendi", result.response)


if __name__ == "__main__":
    unittest.main()
