import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.personal_cognition import (
    PersonalCognitionStore,
    _looks_like_style_preference,
)


class StylePreferenceClassificationTests(unittest.TestCase):
    def test_human_response_request_is_style_preference(self):
        self.assertTrue(
            _looks_like_style_preference(
                "que respondas de forma humana"
            )
        )

    def test_real_goal_is_not_style_preference(self):
        self.assertFalse(
            _looks_like_style_preference(
                "aprender Python"
            )
        )

    def test_new_style_request_is_preference_not_goal(self):
        with tempfile.TemporaryDirectory() as td:
            store = PersonalCognitionStore(td)
            result = store.observe_interaction(
                "Quero que respondas de forma humana."
            )
            self.assertTrue(
                any(
                    row["category"] == "preference"
                    for row in result["learned"]
                )
            )
            self.assertFalse(
                any(
                    row.get("statement")
                    == "que respondas de forma humana"
                    for row in store.model()["goals"]
                )
            )

    def test_existing_bad_goal_is_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "personal_model.json").write_text(
                json.dumps({
                    "interaction_count": 1,
                    "preferences": [],
                    "goals": [{
                        "statement": "que respondas de forma humana",
                        "confidence": 1.0,
                        "source": "explicit-user-statement",
                    }],
                    "constraints": [],
                    "projects": [],
                    "topic_counts": {},
                    "recent_topics": [],
                    "last_updated": None,
                }),
                encoding="utf-8",
            )
            (root / "cognition_state.json").write_text(
                json.dumps({
                    "learning_enabled": True,
                    "proactive_enabled": True,
                    "proactive_speech_enabled": True,
                    "pending_insights": [{
                        "type": "new_personal_knowledge",
                        "category": "goal",
                        "statement": "que respondas de forma humana",
                    }],
                }),
                encoding="utf-8",
            )

            store = PersonalCognitionStore(root)
            self.assertEqual(
                store.model()["goals"],
                [],
            )
            self.assertEqual(
                store.state()["pending_insights"][0]["category"],
                "preference",
            )


if __name__ == "__main__":
    unittest.main()
