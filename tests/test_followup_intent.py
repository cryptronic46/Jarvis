import unittest
from datetime import datetime

from jarvis_core.services.followup_intent import resolve_followup


class FollowupIntentTests(unittest.TestCase):
    def _row(self, user, assistant):
        return {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": user,
            "assistant": assistant,
            "route": "LOCAL/FAST",
        }

    def test_exact_reported_memory_followup_is_resolved(self):
        row = self._row(
            "Memoriza o nome e data de nascimento da minha mulher.",
            "Posso armazenar o nome Ana Isa Guimarães Lopes e a data 27 de Fevereiro de 1987. "
            "Se quiser, posso também criar um perfil pessoal com essas informações. Deseja que eu faça isso?",
        )
        result = resolve_followup("Sim, faz isso!", [row])
        self.assertTrue(result.resolved)
        self.assertEqual(result.kind, "ACCEPT_PREVIOUS")
        self.assertIn("Ana Isa Guimarães Lopes", result.tool_query)
        self.assertIn("perfil pessoal", result.tool_query)
        self.assertIn("perform the action now", result.contract)
        self.assertIn("Do not jump to an older topic", result.contract)

    def test_provenance_questions_are_never_accept_previous(self):
        row = self._row("O que aprendeste sobre TCP?", "Aprendi TCP a partir do RFC 9293.")
        for text in ("de onde aprendeste isso?", "de onde aprendeste isso?~", "qual era a fonte?", "onde viste isso?"):
            with self.subTest(text=text):
                result = resolve_followup(text, [row])
                self.assertTrue(result.resolved)
                self.assertEqual(result.kind, "PROVENANCE_PREVIOUS")
                self.assertNotEqual(result.kind, "ACCEPT_PREVIOUS")
    def test_plain_yes_resolves_only_against_immediate_offer(self):
        row = self._row("Queres detalhes?", "Posso mostrar os detalhes. Queres que eu continue?")
        result = resolve_followup("Sim", [row])
        self.assertTrue(result.resolved)
        self.assertEqual(result.kind, "ACCEPT_PREVIOUS")

    def test_unrelated_long_request_is_not_rewritten(self):
        row = self._row("Queres detalhes?", "Posso mostrar os detalhes. Queres que eu continue?")
        result = resolve_followup(
            "Agora quero que analises o desempenho do meu computador durante jogos.",
            [row],
        )
        self.assertFalse(result.resolved)

    def test_rejection_stays_on_immediate_topic(self):
        row = self._row("Queres que eu crie?", "Posso criar isso agora. Deseja que eu faça isso?")
        result = resolve_followup("Não, deixa estar", [row])
        self.assertTrue(result.resolved)
        self.assertEqual(result.kind, "REJECT_PREVIOUS")
        self.assertIn("do not perform", result.contract)

    def test_no_previous_turn_means_no_resolution(self):
        result = resolve_followup("Sim, faz isso", [])
        self.assertFalse(result.resolved)


if __name__ == "__main__":
    unittest.main()
