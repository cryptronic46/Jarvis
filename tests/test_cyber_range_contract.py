import unittest
from pathlib import Path


class CyberRangeContractTests(unittest.TestCase):
    def test_model_has_no_scope_mutation_tool(self):
        registry = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.assertIn('"get_cyber_range_status"', registry)
        self.assertIn('"classify_cyber_target"', registry)
        self.assertIn('"probe_cyber_lab_target"', registry)
        for forbidden in (
            '"add_cyber_lab_scope"',
            '"authorize_cyber_target"',
            '"remove_cyber_lab_scope"',
        ):
            self.assertNotIn(forbidden, registry)

    def test_scope_mutation_is_owner_cli_path(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('lower.startswith("/cyber lab add ")', cli)
        self.assertIn("cyber_range.add_lab_scope(", cli)
        self.assertIn('lower.startswith("/cyber lab remove ")', cli)
        self.assertIn("cyber_range.remove_lab_scope(", cli)

    def test_brain_uses_scope_before_lab_testing(self):
        brain = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("CYBER RANGE AUTHORITY", brain)
        self.assertIn("LAB = explicitly OWNER-authorized", brain)
        self.assertIn("probe_cyber_lab_target", brain)
        self.assertIn("cannot add/remove LAB scopes", brain)

    def test_service_contains_no_shell_execution(self):
        service = Path("jarvis_core/services/cyber_range.py").read_text(encoding="utf-8")
        for forbidden in ("subprocess", "os.system", "shell=True", "powershell", "cmd.exe"):
            self.assertNotIn(forbidden, service)


if __name__ == "__main__":
    unittest.main()
