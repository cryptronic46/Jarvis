import unittest
from pathlib import Path


class SystemCyberAuditorContractTests(unittest.TestCase):
    def test_cli_commands_exist(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for command in (
            "/cyber analyze system",
            "/cyber analyze system full",
            "/cyber analyze system raw",
        ):
            self.assertIn(f'lower == "{command}"', cli)

    def test_tool_is_read_only_registered(self):
        registry = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"analyze_system_cybersecurity"',
            registry,
        )
        pos = registry.index(
            '"analyze_system_cybersecurity"'
        )
        block = registry[pos:pos+1700]
        self.assertIn("RiskLevel.READ_ONLY", block)

    def test_brain_prefers_dedicated_auditor(self):
        brain = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "For a complete security analysis of this PC, use "
            "analyze_system_cybersecurity",
            brain,
        )

    def test_fast_router_has_natural_command(self):
        fast = Path(
            "jarvis_core/core/fast_router.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "analisa a seguranca do meu sistema",
            fast,
        )
        self.assertIn(
            '"analyze_system_cybersecurity"',
            fast,
        )


if __name__ == "__main__":
    unittest.main()
