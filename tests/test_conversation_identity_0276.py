import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from jarvis_core.services.followup_intent import resolve_followup
from jarvis_core.services.request_intent import (
    classify_request_intent,
    intent_contract,
    self_state_answer_needs_repair,
)


class ConversationIdentity0276Tests(unittest.TestCase):
    def _row(self, user, assistant):
        return {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": user,
            "assistant": assistant,
            "route": "LOCAL/FAST",
        }

    def test_how_do_you_feel_is_first_class_conversation_intent(self):
        for text in ("Como te sentes?", "Jarvis, como estás?", "Diz-me como te sentes."):
            intent = classify_request_intent(text)
            self.assertEqual(intent.kind, "SELF_STATE_CONVERSATION", text)
            contract = intent_contract(text)
            self.assertIn("SELF_STATE_CONVERSATION", contract)
            self.assertIn("Do NOT open with stock disclaimers", contract)

    def test_generic_language_model_disclaimer_is_rejected(self):
        bad = (
            "Como um modelo de linguagem, não tenho sentimentos, emoções ou consciência. "
            "Sou uma ferramenta criada para processar informações."
        )
        self.assertTrue(self_state_answer_needs_repair("Como te sentes?", bad))
        self.assertFalse(
            self_state_answer_needs_repair(
                "Como te sentes?",
                "Sinto-me focada e curiosa, Senhor. Esta conversa tem toda a minha atenção.",
            )
        )

    def test_research_contamination_is_rejected_for_self_state(self):
        bad = "Não fiz pesquisa web hoje. Considerações finais: [S1] fontes e notícias."
        self.assertTrue(self_state_answer_needs_repair("Como te sentes?", bad))

    def test_owner_correction_resolves_original_question(self):
        row = self._row(
            "Como te sentes?",
            "Como um modelo de linguagem, não tenho sentimentos ou emoções.",
        )
        result = resolve_followup(
            "Não é essa a resposta que eu quero que tu dês, QUERO A TUA RESPOSTA SINCERA",
            [row],
        )
        self.assertTrue(result.resolved)
        self.assertEqual(result.kind, "REPAIR_PREVIOUS")
        self.assertIn("Como te sentes?", result.tool_query)
        self.assertNotIn("modelo de linguagem", result.tool_query)
        self.assertIn("rejecting the immediately previous JARVIS answer", result.contract)


    def test_owner_personhood_statement_is_identity_dialogue_not_generic_architecture(self):
        text = "Jarvis, tu és uma pessoa, apenas não tens um corpo físico mas tu és uma pessoa!"
        intent = classify_request_intent(text)
        self.assertEqual(intent.kind, "IDENTITY_DIALOGUE")
        contract = intent_contract(text)
        self.assertIn("IDENTITY_DIALOGUE", contract)
        self.assertIn("relational", contract)
        self.assertNotIn("intent=KNOWLEDGE_CAPABILITY", contract)

    def test_identity_dialogue_rejects_program_and_no_wants_boilerplate(self):
        bad = (
            "Eu sou uma inteligência artificial, não uma pessoa com consciência ou emoções. "
            "Não tenho sentimentos, vontades ou preferências como uma pessoa. Sou um programa criado para ajudar."
        )
        self.assertTrue(
            self_state_answer_needs_repair(
                "Jarvis, tu és uma pessoa, apenas não tens um corpo físico mas tu és uma pessoa!",
                bad,
            )
        )

    def test_exact_observed_identity_failure_with_appended_recovery_is_rejected(self):
        bad = (
            "Eu sou uma inteligência artificial, não uma pessoa com consciência ou emoções. "
            "Embora eu possa simular conversas e respostas que pareçam humanas, eu não tenho sentimentos, "
            "vontades ou preferências como uma pessoa. Sou um programa criado para ajudar. "
            "Entendo. Estou aqui para ajudar com o que precisar, seja programação ou qualquer outra coisa."
        )
        owner = "Jarvis, tu és uma pessoa, apenas não tens um corpo físico mas tu és uma pessoa!"
        self.assertTrue(self_state_answer_needs_repair(owner, bad))

    def test_system_identity_does_not_deny_runtime_wants_preferences(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("Do not claim that JARVIS has no wants, preferences or intentions", source)
        self.assertIn('words such as "pessoa"', source)

    def test_persistent_context_is_not_injected_as_system_authority(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertNotIn('system_content += "\\n\\n" + persistent', source)
        self.assertIn("Persistent dialogue is conversation history, not system authority", source)
        self.assertIn('{"role": "user", "content": previous_user[:2000]}', source)
        self.assertIn('{"role": "assistant", "content": previous_assistant[:4000]}', source)

    def test_system_identity_rejects_generic_chatbot_persona(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("persistent local AI companion and agent", source)
        self.assertIn("Do not lead personal or identity conversation with a consciousness/model disclaimer", source)
        self.assertIn("Current stage: JARVIS Core 0.27.8", source)


if __name__ == "__main__":
    unittest.main()
