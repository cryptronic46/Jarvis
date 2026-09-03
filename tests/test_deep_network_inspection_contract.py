import unittest
from pathlib import Path


class DeepNetworkInspectionContractTests(unittest.TestCase):
    def test_cli_commands_exist(self):
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        for command in (
            "/cyber inspect network",
            "/cyber inspect network full",
            "/cyber inspect network raw",
            "/cyber inspect listeners",
            "/cyber inspect connections",
        ):
            self.assertIn(
                f'lower == "{command}"',
                cli,
            )

    def test_read_only_tool_registered(self):
        registry = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(encoding="utf-8")
        pos = registry.index(
            '"inspect_network_deep"'
        )
        block = registry[pos:pos+1600]
        self.assertIn(
            "RiskLevel.READ_ONLY",
            block,
        )

    def test_brain_knows_when_to_use_deep_inspection(self):
        brain = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Use inspect_network_deep",
            brain,
        )

    def test_fast_router_supports_natural_request(self):
        fast = Path(
            "jarvis_core/core/fast_router.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "investiga os listeners",
            fast,
        )
        self.assertIn(
            '"inspect_network_deep"',
            fast,
        )


if __name__ == "__main__":
    unittest.main()
