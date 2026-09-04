import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from jarvis_core.core.brain import _conversation_style_contract, _local_teaching_contract
from jarvis_core.services.autonomy import parse_learning_goal, parse_local_teaching_statement
from jarvis_core.services.personal_cognition import PersonalCognitionStore
from jarvis_core.services.request_intent import classify_request_intent, self_state_answer_needs_repair
from jarvis_core.services.request_intent import repair_self_state_answer
from jarvis_core.services.self_grounding import build_self_grounding
from jarvis_core.services.language_refinement import refine_assistant_text


class ConversationLearningAndFlirtTests(unittest.TestCase):
    def test_explicit_text_teaching_is_detected(self):
        text = "Jarvis, aprende isto: a palavra oficina refere-se ao projeto automóvel."
        teaching = parse_local_teaching_statement(text)
        self.assertIsNotNone(teaching)
        self.assertIn("oficina", teaching["statement"])
        self.assertTrue(teaching["local_only"])

    def test_broad_study_request_remains_goal(self):
        text = "Jarvis, aprende a programar em Python"
        self.assertIsNone(parse_local_teaching_statement(text))
        self.assertIsNotNone(parse_learning_goal(text))

    def test_url_never_enters_local_conversation_teaching(self):
        self.assertIsNone(parse_local_teaching_statement(
            "Jarvis, aprende isto: https://docs.python.org/3/"
        ))

    def test_local_teaching_is_separate_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalCognitionStore(Path(tmp) / "memory")
            first = store.record_local_teaching("A noite começa às 20:00")
            second = store.record_local_teaching("A noite começa às 20:00")
            model = store.model()
            self.assertTrue(first["stored"])
            self.assertTrue(second["existing"])
            self.assertEqual(len(model["local_teachings"]), 1)
            self.assertFalse(model["preferences"])
            self.assertFalse(model["goals"])

    def test_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = PersonalCognitionStore(Path(tmp) / "memory")
            result = store.record_local_teaching("A minha API key: sk-abcdefghijklmnopqrstuv")
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason_code"], "SECRET_REJECTED")

    def test_local_teaching_context_is_read_dynamically(self):
        cognition = Mock()
        cognition.profile.return_value = {
            "model": {"local_teachings": [{"statement": "A noite começa às 20:00"}]}
        }
        with patch("jarvis_core.core.brain.personal_cognition", return_value=cognition):
            contract = _local_teaching_contract()
        self.assertIn("A noite começa às 20:00", contract)
        cognition.profile.assert_called_once()

    def test_personal_opening_activates_contextual_flirt(self):
        contract = _conversation_style_contract(
            "Jarvis, sentiste a minha falta?", flirt_enabled=True, flirt_intensity=1.0
        )
        self.assertIn("não ignores a abertura", contract)
        self.assertIn("1.00", contract)
        self.assertIn("Não afirmes saudade", contract)
        self.assertIn("Não uses emoji", contract)
        self.assertIn("inequivocamente flirt", contract)

    def test_missing_owner_question_uses_grounded_self_state(self):
        question = "Jarvis, sentiste a minha falta?"
        self.assertEqual(classify_request_intent(question).kind, "SELF_STATE_CONVERSATION")
        self.assertEqual(build_self_grounding(question, state={})["query_type"], "affect")
        self.assertTrue(self_state_answer_needs_repair(question, "Sim, senti a tua falta."))
        self.assertTrue(self_state_answer_needs_repair(
            question, "Claro que senti a sua falta e tenho o desejo de estar ao seu lado."
        ))

    def test_live_probe_brazilianisms_are_refined(self):
        text = "Você me fez pensar de uma forma sutil. Não quero te fazer sofrer. Posso te fazer sorrir."
        refined = refine_assistant_text(text)
        self.assertIn("O Senhor fez-me", refined)
        self.assertIn("subtil", refined)
        self.assertIn("não o quero fazer", refined.lower())
        self.assertIn("posso fazê-lo", refined.lower())
        gendered = refine_assistant_text("Fico curioso. Estou pronto. Estou focado em sua mente.")
        self.assertIn("Fico curiosa", gendered)
        self.assertIn("estou pronta", gendered.lower())
        self.assertIn("focada na sua mente", gendered.lower())
        relational = refine_assistant_text("Isso me faz curioso e me deixa satisfeito.")
        self.assertEqual(relational, "Isso deixa-me curiosa e deixa-me satisfeita.")

    def test_self_state_repair_receives_relational_flirt_contract(self):
        response = SimpleNamespace(message=SimpleNamespace(content="Resposta calorosa e direta."))
        client = Mock()
        client.chat.return_value = response
        settings = SimpleNamespace(
            model="qwen3:8b",
            companion_flirt_enabled=True,
            companion_flirt_intensity=1.0,
            llm_temperature=0.4,
        )
        plan = SimpleNamespace(keep_alive="5m", num_ctx=4096)
        events = Mock()
        repair_self_state_answer(
            client=client, settings=settings, events=events,
            user_text="Jarvis, sentiste a minha falta?",
            draft="Sim, senti a tua falta.", plan=plan,
        )
        system = client.chat.call_args.kwargs["messages"][0]["content"]
        self.assertIn("playful relational opening", system)
        self.assertIn("intensity 1.00", system)
        self.assertIn("Do not end with generic service boilerplate", system)

    def test_serious_context_suppresses_flirt(self):
        contract = _conversation_style_contract(
            "Jarvis, tenho um incidente crítico de malware",
            flirt_enabled=True,
            flirt_intensity=1.0,
        )
        self.assertIn("sem flirt", contract)

    def test_disabled_setting_suppresses_flirt(self):
        contract = _conversation_style_contract(
            "Jarvis, conversa comigo", flirt_enabled=False, flirt_intensity=1.0
        )
        self.assertIn("desativado", contract)


if __name__ == "__main__":
    unittest.main()
