import unittest
from pathlib import Path


class CyberKnowledgeCliTests(unittest.TestCase):
    def test_commands_exist(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for command in (
            "/cyber knowledge status",
            "/cyber knowledge sync",
            "/cyber knowledge sync full",
        ):
            self.assertIn(f'lower == "{command}"', cli)
        self.assertIn(
            'lower.startswith("/cyber knowledge search ")',
            cli,
        )
        self.assertIn(
            'lower.startswith("/cyber knowledge ingest ")',
            cli,
        )

    def test_background_updater_lifecycle(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("cyber_knowledge_service.start()", cli)
        self.assertIn("cyber_knowledge_service.stop()", cli)


if __name__ == "__main__":
    unittest.main()
