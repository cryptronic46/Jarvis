import unittest

from jarvis_core.core.conversation_policy import authorized_learning_requested


class AuthorizedLearningScopeTests(unittest.TestCase):
    def test_ordinary_question_about_user_is_not_explicit_stored_learning(self):
        self.assertFalse(
            authorized_learning_requested("O que sabes sobre mim?")
        )

    def test_ordinary_question_about_jarvis_is_not_explicit_stored_learning(self):
        self.assertFalse(
            authorized_learning_requested("O que sabes sobre ti?")
        )

    def test_ordinary_knowledge_question_is_not_explicit_stored_learning(self):
        self.assertFalse(
            authorized_learning_requested("O que sabes sobre Python?")
        )

    def test_singular_saved_summary_is_explicit_stored_learning(self):
        self.assertTrue(
            authorized_learning_requested("Mostra o resumo guardado")
        )

    def test_singular_saved_knowledge_is_explicit_stored_learning(self):
        self.assertTrue(
            authorized_learning_requested("Mostra o conhecimento guardado")
        )

    def test_existing_explicit_learning_signals_remain_recognized(self):
        cases = (
            "O que aprendeste sobre Python?",
            "O que pesquisaste sobre Python?",
            "O que estudaste sobre Python?",
            "Usa a pesquisa autorizada sobre Python",
            "Consulta as pesquisas autorizadas",
            "Mostra as fontes guardadas",
            "Mostra o conhecimento aprendido",
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(
                    authorized_learning_requested(text),
                    text,
                )


if __name__ == "__main__":
    unittest.main()
