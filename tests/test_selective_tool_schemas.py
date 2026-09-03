import unittest
from pathlib import Path


class SelectiveToolSchemaTests(unittest.TestCase):
    def setUp(self):
        self.text = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(encoding="utf-8")

    def test_selector_exists(self):
        self.assertIn(
            "def schemas_for_query",
            self.text,
        )

    def test_generic_conversation_can_use_zero_tools(self):
        self.assertIn(
            "Generic conversation therefore needs zero tool schemas",
            self.text,
        )

    def test_selector_has_cyber_and_system_groups(self):
        for tool in (
            "inspect_network_deep",
            "analyze_system_cybersecurity",
            "get_pre_request_telemetry",
            "get_system_status",
        ):
            self.assertIn(
                f'"{tool}"',
                self.text,
            )


    def test_explicit_relationship_memory_questions_can_recall_local_memory(self):
        for marker in (
            "o que sabes da minha mulher",
            "o que sabes da minha esposa",
            "o que sabes da minha companheira",
            "o que sabes da minha familia",
        ):
            self.assertIn(f'"{marker}"', self.text)
        # Mere relationship mentions belong to ordinary conversation and must
        # not by themselves activate the personal-memory tool bundle.
        self.assertNotIn('"minha companheira",\n            "meu marido"', self.text)
        self.assertIn('"recall_user_memory"', self.text)

    def test_brain_uses_selector_not_full_catalogue(self):
        brain = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "self.tools.schemas_for_query(",
            brain,
        )
        self.assertNotIn(
            "tools=self.tools.schemas",
            brain,
        )


if __name__ == "__main__":
    unittest.main()
