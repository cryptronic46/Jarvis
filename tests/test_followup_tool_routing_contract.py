import unittest
from datetime import datetime
from pathlib import Path

from jarvis_core.services.followup_intent import resolve_followup


class FollowupToolRoutingContractTests(unittest.TestCase):
    def test_brain_resolves_followup_before_tool_selection(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("followup = resolve_followup(", text)
        self.assertIn("effective_query = followup.tool_query", text)
        self.assertIn(
            "self.tools.schemas_for_query(",
            text,
        )
        self.assertIn(
            "effective_query,",
            text,
        )

        followup_pos = text.index(
            "followup = resolve_followup("
        )
        effective_pos = text.index(
            "effective_query = "
        )
        tool_selection_pos = text.index(
            "self.tools.schemas_for_query("
        )

        self.assertLess(
            followup_pos,
            effective_pos,
        )
        self.assertLess(
            effective_pos,
            tool_selection_pos,
        )
        self.assertIn('"FOLLOWUP_RESOLVED"', text)

    def test_followup_service_never_searches_older_than_latest_row(self):
        text = Path("jarvis_core/services/followup_intent.py").read_text(encoding="utf-8")
        self.assertIn("latest = rows[-1]", text)
        self.assertNotIn("rows[-2]", text)

    def test_reported_case_routes_toward_memory_not_old_kali_topic(self):
        row = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "user": "Memoriza o nome e a data de nascimento da minha mulher.",
            "assistant": (
                "Posso armazenar o nome Ana Isa Guimarães Lopes e a data 27 de Fevereiro de 1987. "
                "Se quiser, posso também criar um perfil pessoal. Deseja que eu faça isso?"
            ),
        }
        resolved = resolve_followup("Sim, faz isso!", [row])
        self.assertTrue(resolved.resolved)
        self.assertIn("minha mulher", resolved.tool_query.lower())
        self.assertIn("perfil pessoal", resolved.tool_query.lower())
        self.assertNotIn("kali", resolved.tool_query.lower())

        selector = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertIn('"memoriza"', selector)
        self.assertNotIn('"minha mulher", "minha esposa", "minha companheira"', selector)
        self.assertIn('"remember_user_fact"', selector)


if __name__ == "__main__":
    unittest.main()
