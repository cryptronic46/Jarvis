import unittest
from pathlib import Path


class PersonalCognitionContractTests(unittest.TestCase):
    def test_mind_cli_commands_exist(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for command in (
            "/mind status", "/mind profile", "/mind reflect", "/mind self", "/mind why",
            "/mind learning on", "/mind learning off", "/mind proactive on", "/mind proactive off",
            "/mind speech on", "/mind speech off",
        ):
            self.assertIn(f'lower == "{command}"', cli)

    def test_brain_has_consciousness_boundary(self):
        brain = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("Never claim subjective consciousness", brain)
        self.assertIn("functional self-model", brain)

    def test_proactive_service_lifecycle(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("proactive_service.start()", cli)
        self.assertIn("proactive_service.stop()", cli)

    def test_cognition_tools_registered(self):
        registry = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        for name in (
            "get_personal_cognition_status", "get_personal_model", "get_functional_self_model",
            "reflect_personal_context", "get_last_proactive_reason", "set_personal_cognition_mode",
        ):
            self.assertIn(f'"{name}"', registry)


if __name__ == "__main__":
    unittest.main()
