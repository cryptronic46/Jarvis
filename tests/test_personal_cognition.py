import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.personal_cognition import PersonalCognitionStore


class PersonalCognitionTests(unittest.TestCase):
    def make_store(self):
        tmp = tempfile.TemporaryDirectory()
        store = PersonalCognitionStore(Path(tmp.name) / "memory")
        return tmp, store

    def test_learns_explicit_goal_and_preference(self):
        tmp, store = self.make_store()
        try:
            result = store.observe_interaction(
                "Quero aprender segurança informática. Prefiro explicações práticas.",
                "OK",
                "LOCAL",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(store.model()["owner_learning_goals"])
            self.assertFalse(store.model()["goals"])
            self.assertTrue(store.model()["preferences"])
        finally:
            tmp.cleanup()

    def test_redacts_secret(self):
        tmp, store = self.make_store()
        try:
            result = store.observe_interaction(
                "A minha API key: sk-abcdefghijklmnopqrstuv e quero testar a app.",
                "OK",
                "LOCAL",
            )
            self.assertTrue(result["secret_redacted"])
            raw = store.observations_path.read_text(encoding="utf-8") if store.observations_path.exists() else ""
            self.assertNotIn("sk-abcdefghijklmnopqrstuv", raw)
        finally:
            tmp.cleanup()

    def test_sensitive_inference_is_skipped(self):
        tmp, store = self.make_store()
        try:
            result = store.observe_interaction(
                "Quero falar do meu diagnóstico e medicação.",
                "OK",
                "LOCAL",
            )
            self.assertTrue(result["sensitive_inference_skipped"])
            self.assertFalse(store.model()["goals"])
        finally:
            tmp.cleanup()

    def test_self_model_does_not_claim_subjective_consciousness(self):
        tmp, store = self.make_store()
        try:
            model = store.self_model()
            self.assertFalse(model["subjective_consciousness"])
            self.assertEqual(model["subjective_consciousness_status"], "not_established")
            self.assertIn("não está estabelecida", model["consciousness_statement"])
            self.assertIn("drives, preferências e intenções", model["consciousness_statement"])
        finally:
            tmp.cleanup()

    def test_modes_persist_independently(self):
        tmp, store = self.make_store()
        try:
            store.set_mode(learning_enabled=False, proactive_enabled=True, proactive_speech_enabled=False)
            state = store.state()
            self.assertFalse(state["learning_enabled"])
            self.assertTrue(state["proactive_enabled"])
            self.assertFalse(state["proactive_speech_enabled"])
        finally:
            tmp.cleanup()

    def test_learns_explicit_day_period_boundaries(self):
        tmp, store = self.make_store()
        try:
            morning = store.observe_interaction(
                "A manhã começa às 06:00 am",
                "Entendido.",
                "FAST/time_boundary_learning",
            )
            night = store.observe_interaction(
                "A noite começa às 20:00",
                "Entendido.",
                "FAST/time_boundary_learning",
            )
            self.assertIn(
                {"category": "time_boundary", "statement": "morning=06:00"},
                morning["learned"],
            )
            self.assertIn(
                {"category": "time_boundary", "statement": "night=20:00"},
                night["learned"],
            )
            self.assertEqual(store.time_boundaries()["morning"], "06:00")
            self.assertEqual(store.time_boundaries()["night"], "20:00")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
