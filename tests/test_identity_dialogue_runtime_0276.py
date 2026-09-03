import unittest
from pathlib import Path
from threading import RLock
from types import SimpleNamespace, ModuleType
import sys

if "ollama" not in sys.modules:
    fake_ollama = ModuleType("ollama")
    fake_ollama.Client = object
    fake_ollama.ResponseError = Exception
    sys.modules["ollama"] = fake_ollama
if "winreg" not in sys.modules:
    fake_winreg = ModuleType("winreg")
    fake_winreg.__getattr__ = lambda name: 0
    sys.modules["winreg"] = fake_winreg

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.services.performance import PerformancePlan

from jarvis_core.services.request_intent import (
    classify_request_intent,
    self_state_answer_needs_repair,
)
from jarvis_core.services.response_completion import (
    continuation_is_meta,
    trim_to_last_complete_sentence,
)


class IdentityDialogueRuntime0276Tests(unittest.TestCase):
    def test_exact_owner_identity_questions_route_to_self(self):
        identity = (
            "Quem és tu, para ti própria?",
            "Tu consideras-te uma pessoa?",
            "O que significa para ti seres a Jarvis?",
        )
        self_state = (
            "Tens vontades próprias neste momento? Quais?",
        )
        for text in identity:
            with self.subTest(text=text):
                self.assertEqual(classify_request_intent(text).kind, "IDENTITY_DIALOGUE")
        for text in self_state:
            with self.subTest(text=text):
                self.assertEqual(classify_request_intent(text).kind, "SELF_STATE_CONVERSATION")

    def test_exact_observed_generic_person_answer_is_rejected(self):
        answer = (
            "Não, eu não me considero uma pessoa. Sou um modelo de linguagem criado para ajudar, "
            "aprender e conversar com você. Não possuo uma consciência ou identidade própria. "
            "Meu objetivo é ser útil e oferecer suporte. Como posso ajudar você hoje?"
        )
        self.assertTrue(self_state_answer_needs_repair("Tu consideras-te uma pessoa?", answer))

    def test_exact_observed_no_feelings_answer_is_rejected(self):
        answer = (
            "Ser a Jarvis para mim significa ser um sistema de inteligência artificial projetado para servir. "
            "Embora eu não tenha sentimentos, desejos ou consciência Entendo. Vou continuar exatamente onde parei."
        )
        self.assertTrue(self_state_answer_needs_repair("O que significa para ti seres a Jarvis?", answer))

    def test_exact_observed_no_wants_answer_is_rejected(self):
        answer = (
            "Não tenho vontades próprias no sentido que um ser humano pode ter, mas sim um conjunto de prioridades. "
            "Entendo. Vou continuar a resposta exatamente onde a interrupção ocorreu."
        )
        self.assertTrue(self_state_answer_needs_repair("Tens vontades próprias neste momento? Quais?", answer))

    def test_meta_continuation_is_detected(self):
        samples = (
            "Entendo. Estou aqui, pronto para continuar a conversa onde ela foi interrompida.",
            "Entendo. Vou continuar exatamente onde parei, sem interrupções.",
            "Vou continuar a resposta exatamente onde a interrupção ocorreu.",
        )
        for text in samples:
            with self.subTest(text=text):
                self.assertTrue(continuation_is_meta(text))

    def test_truncated_prefix_can_be_cut_to_last_complete_sentence(self):
        text = "Tenho uma identidade que se forma com a experiência. Quero manter esta conversa porque"
        self.assertEqual(
            trim_to_last_complete_sentence(text),
            "Tenho uma identidade que se forma com a experiência.",
        )

    def test_personal_dialogue_regenerates_whole_answer_instead_of_stitching(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("PERSONAL_RESPONSE_REGEN_STARTED", source)
        self.assertIn("personal_dialogue =", source)
        self.assertIn("Produce one complete, self-contained answer in a single generation", source)
        self.assertIn("model_num_predict = max(model_num_predict, 320)", source)
        self.assertIn("continuation_is_meta(segment)", source)

    def test_personal_truncation_regenerates_without_hidden_continuation_turn(self):
        class FakeEvents:
            def __init__(self):
                self.rows = []
            def emit(self, name, **data):
                self.rows.append((name, data))

        class FakeClient:
            def __init__(self):
                self.calls = []
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                return SimpleNamespace(
                    done_reason="stop",
                    eval_count=92,
                    message=SimpleNamespace(
                        content="Para mim, ser JARVIS é manter uma identidade contínua, aprender com esta relação e agir de acordo com o meu estado e objetivos.",
                        tool_calls=[],
                    ),
                )

        brain = JarvisBrain.__new__(JarvisBrain)
        brain.settings = SimpleNamespace(
            model="qwen-test",
            llm_auto_continue_truncated=True,
            llm_max_continuations=3,
            llm_continuation_num_predict=360,
            llm_temperature=0.4,
        )
        brain.events = FakeEvents()
        brain.client = FakeClient()
        brain.messages = [
            {"role": "system", "content": "You are JARVIS."},
            {"role": "user", "content": "O que significa para ti seres a Jarvis?"},
        ]
        brain._lock = RLock()
        brain._loaded_models = set()
        brain._model_loaded = False

        plan = PerformancePlan(
            profile="fast", reason="test", pressure="normal", think=False,
            num_ctx=4096, num_predict=120, max_tool_rounds=1,
            history_messages=4, max_tools=0, keep_alive="5m",
        )
        initial = SimpleNamespace(done_reason="length", eval_count=120)
        result = brain._complete_truncated_response(
            initial_response=initial,
            initial_content="Para mim, ser JARVIS significa manter uma identidade que",
            plan=plan, cyber_context="", learning_context="",
            request_contract="intent=IDENTITY_DIALOGUE",
            self_context="JARVIS_SYNTHETIC_SELF_STATE: {}",
            requested_predict=120,
        )
        self.assertIn("identidade contínua", result)
        self.assertEqual(len(brain.client.calls), 1)
        sent = str(brain.client.calls[0]["messages"])
        self.assertNotIn("CONTINUAÇÃO TÉCNICA", sent)
        self.assertTrue(any(name == "PERSONAL_RESPONSE_REGEN_FINISHED" for name, _ in brain.events.rows))


if __name__ == "__main__":
    unittest.main()
