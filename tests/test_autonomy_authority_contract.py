import unittest
from pathlib import Path


class AutonomyAuthorityContractTests(unittest.TestCase):
    def test_no_authorize_or_deny_model_tool_exists(self):
        registry = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(encoding="utf-8")

        forbidden_tool_names = (
            '"authorize_autonomy"',
            '"approve_autonomy"',
            '"deny_autonomy"',
            '"grant_autonomy"',
        )
        for name in forbidden_tool_names:
            self.assertNotIn(
                name,
                registry,
            )

    def test_authorize_enters_through_cli(self):
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'lower.startswith("/authorize ")',
            cli,
        )
        self.assertIn(
            "autonomy.authorize(",
            cli,
        )

    def test_owner_strict_is_not_model_changeable(self):
        service = Path(
            "jarvis_core/services/autonomy.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"mode": "owner_strict"',
            service,
        )
        self.assertIn(
            '"owner_authority": "absolute"',
            service,
        )
        self.assertIn(
            '"self_authorization": False',
            service,
        )

    def test_exact_scope_uses_sha256(self):
        service = Path(
            "jarvis_core/services/autonomy.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "def scope_hash(",
            service,
        )
        self.assertIn(
            "sha256(",
            service,
        )
        self.assertIn(
            '"remaining_uses": 1',
            service,
        )


if __name__ == "__main__":
    unittest.main()
