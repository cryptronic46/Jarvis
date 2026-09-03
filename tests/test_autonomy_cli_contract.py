import unittest
from pathlib import Path


class AutonomyCliContractTests(unittest.TestCase):
    def test_commands_exist(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        for command in (
            "/autonomy status",
            "/autonomy pending",
            "/autonomy history",
            "/autonomy revoke",
            "/authorize ",
            "/deny ",
        ):
            self.assertIn(
                command,
                text,
            )

    def test_startup_declares_owner_authority(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Authority : OWNER/STRICT",
            text,
        )

    def test_security_confirm_and_autonomy_authorize_remain_separate(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'lower.startswith("/confirm ")',
            text,
        )
        self.assertIn(
            'lower.startswith("/authorize ")',
            text,
        )
        self.assertIn(
            "tools.confirm(token)",
            text,
        )
        self.assertIn(
            "autonomy.authorize(",
            text,
        )


if __name__ == "__main__":
    unittest.main()
