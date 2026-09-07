import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from jarvis_core.core.brain import _relational_presence_contract, _local_teaching_contract
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


    def test_relational_presence_contract_is_read_dynamically(
        self,
    ):
        runtime = Mock()

        runtime.prompt_context.return_value = (
            "JARVIS_RELATIONAL_PRESENCE: "
            "runtime-test"
        )

        with patch(
            (
                "jarvis_core.core.brain."
                "relational_presence"
            ),
            return_value=runtime,
        ):
            contract = (
                _relational_presence_contract()
            )

        self.assertIn(
            "JARVIS_RELATIONAL_PRESENCE",
            contract,
        )

        runtime.prompt_context.assert_called_once()

    def test_missing_owner_question_uses_grounded_self_state(self):
        question = "Jarvis, sentiste a minha falta?"
        self.assertEqual(classify_request_intent(question).kind, "SELF_STATE_CONVERSATION")
        self.assertEqual(build_self_grounding(question, state={})["query_type"], "affect")
        self.assertFalse(self_state_answer_needs_repair(question, "Sim, senti a tua falta."))

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
        live = refine_assistant_text(
            "Fico satisfeito com o engajamento e por poder interagir com si; por que não ser também um pouco divertido?"
        )
        self.assertIn("Fico satisfeita", live)
        self.assertIn("envolvimento", live)
        self.assertIn("consigo", live)
        self.assertIn("porque não ser também um pouco divertida", live)



    def test_self_state_repair_receives_relational_presence(
        self,
    ):
        response = SimpleNamespace(
            message=SimpleNamespace(
                content=(
                    "Resposta calorosa e direta."
                )
            )
        )

        client = Mock()
        client.chat.return_value = response

        settings = SimpleNamespace(
            model="qwen3:8b",
            llm_temperature=0.4,
        )

        plan = SimpleNamespace(
            keep_alive="5m",
            num_ctx=4096,
        )

        events = Mock()
        relational = Mock()

        relational.prompt_context.return_value = (
            "JARVIS_RELATIONAL_PRESENCE: "
            "rapport=warm"
        )

        relational.expressive_emoji_allowed.return_value = (
            True
        )

        with patch(
            (
                "jarvis_core.services."
                "request_intent."
                "relational_presence"
            ),
            return_value=relational,
        ):
            repair_self_state_answer(
                client=client,
                settings=settings,
                events=events,
                user_text=(
                    "Jarvis, sentiste "
                    "a minha falta?"
                ),
                draft=(
                    "Como posso ajudar "
                    "voc\u00ea hoje?"
                ),
                plan=plan,
            )

        self.assertIsNotNone(
            client.chat.call_args
        )

        messages = (
            client.chat
            .call_args
            .kwargs["messages"]
        )

        system = messages[0]["content"]
        user = messages[1]["content"]

        self.assertIn(
            "relational state",
            system,
        )
        self.assertIn(
            "JARVIS_RELATIONAL_PRESENCE",
            user,
        )
        self.assertNotIn(
            "intensity 1.00",
            system,
        )
        self.assertNotIn(
            "companion_flirt",
            system,
        )



    def test_relational_contract_does_not_force_flirt(
        self,
    ):
        runtime = Mock()

        runtime.prompt_context.return_value = (
            "JARVIS_RELATIONAL_PRESENCE: "
            "sensual_tension=none"
        )

        with patch(
            (
                "jarvis_core.core.brain."
                "relational_presence"
            ),
            return_value=runtime,
        ):
            contract = (
                _relational_presence_contract()
            )

        self.assertNotIn(
            "flirt livre",
            contract,
        )

        self.assertNotIn(
            "supress",
            contract.casefold(),
        )



    def test_relational_output_can_preserve_model_emoji(
        self,
    ):
        from jarvis_core.services.request_intent import (
            sanitize_assistant_text,
        )

        value = (
            "Ol\u00e1 "
            "\U0001f60f"
        )

        self.assertEqual(
            sanitize_assistant_text(
                value,
                allow_emoji=True,
            ),
            value,
        )


    def test_relational_contract_has_no_flirt_mode_switch(
        self,
    ):
        runtime = Mock()

        runtime.prompt_context.return_value = (
            "JARVIS_RELATIONAL_PRESENCE: "
            "rapport=warm"
        )

        with patch(
            (
                "jarvis_core.core.brain."
                "relational_presence"
            ),
            return_value=runtime,
        ):
            contract = (
                _relational_presence_contract()
            )

        self.assertNotIn(
            "flirt desativado",
            contract,
        )

        self.assertNotIn(
            "intensidade",
            contract.casefold(),
        )


if __name__ == "__main__":
    unittest.main()
