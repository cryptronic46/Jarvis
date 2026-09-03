import unittest
from pathlib import Path


class SecurityCliLevelsTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

    def test_three_security_levels_exist(self):
        self.assertIn(
            'if lower == "/security scan":',
            self.cli,
        )
        self.assertIn(
            'if lower == "/security scan full":',
            self.cli,
        )
        self.assertIn(
            'if lower == "/security scan raw":',
            self.cli,
        )

    def test_full_uses_formatter_not_json_dump(self):
        start = self.cli.index(
            'if lower == "/security scan full":'
        )
        end = self.cli.index(
            'if lower == "/security scan raw":',
            start,
        )
        block = self.cli[start:end]
        self.assertIn(
            "format_security_full",
            block,
        )
        self.assertNotIn(
            "json.dumps",
            block,
        )

    def test_raw_keeps_json_for_diagnostics(self):
        start = self.cli.index(
            'if lower == "/security scan raw":'
        )
        end = self.cli.index(
            'if lower == "/security admins":',
            start,
        )
        block = self.cli[start:end]
        self.assertIn(
            "json.dumps",
            block,
        )


if __name__ == "__main__":
    unittest.main()
