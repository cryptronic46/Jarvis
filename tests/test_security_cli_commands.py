import unittest
from pathlib import Path


class SecurityCliCommandTests(unittest.TestCase):
    def test_security_commands_exist(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for command in (
            "/security scan",
            "/security admins",
            "/security sessions",
            "/security posture",
            "/network status",
        ):
            self.assertIn(f'lower == "{command}"', cli)


if __name__ == "__main__":
    unittest.main()
