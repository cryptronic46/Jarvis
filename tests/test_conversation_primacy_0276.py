import unittest
from pathlib import Path

from jarvis_core.core.conversation_policy import authorized_learning_requested
from jarvis_core.core.fast_router import FastCommandRouter


class _Events:
    def emit(self, *args, **kwargs):
        return None


class _Tools:
    def __init__(self):
        self.request_started_at = 0
        self.calls = []

    def execute(self, name, args=None):
        self.calls.append((name, args or {}))
        return '{"ok": true}'


class _Apps:
    def list_apps(self):
        return []


class ConversationPrimacy0276Tests(unittest.TestCase):
    def test_ordinary_dialogue_does_not_request_authorized_learning(self):
        casual = (
            "Hoje tive um dia estranho e queria conversar contigo sobre isso.",
            "A minha companheira disse-me uma coisa e fiquei a pensar.",
            "Como estás? Quero simplesmente falar contigo um bocado.",
            "Acho que às vezes penso demasiado nas coisas.",
        )
        for text in casual:
            self.assertFalse(
                authorized_learning_requested(text),
                text,
            )

    def test_explicit_prior_learning_queries_can_request_learning(self):
        queries = (
            "O que aprendeste sobre comportamento humano?",
            "O que pesquisaste sobre inteligência artificial?",
            "Consulta a pesquisa autorizada sobre redes.",
            "Mostra o resumo guardado da pesquisa que fizeste.",
        )
        for text in queries:
            self.assertTrue(
                authorized_learning_requested(text),
                text,
            )

    def test_social_turns_are_not_canned_fast_path(self):
        router = FastCommandRouter(_Events(), _Tools(), _Apps())
        for text in ("Obrigado", "Muito bem Jarvis", "Tchau", "Até logo"):
            result = router.dispatch(text, voice_origin=True)
            self.assertFalse(result.handled, text)

    def test_runtime_status_question_can_remain_fast(self):
        router = FastCommandRouter(_Events(), _Tools(), _Apps())
        result = router.dispatch("Estás a ouvir-me?", voice_origin=True)
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "social_listening")

    def test_relationship_words_alone_do_not_select_memory_tools(self):
        source = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertNotIn('"minha companheira",\n            "meu marido"', source)
        self.assertIn('"o que sabes da minha companheira"', source)

    def test_system_prompt_contains_conversation_primacy_contract(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("CONVERSATION PRIMACY", source)
        self.assertIn("Never mention the stored-research disclaimer in unrelated conversation", source)
        self.assertIn("AUTHORIZED_LEARNING_SKIPPED", source)


if __name__ == "__main__":
    unittest.main()
