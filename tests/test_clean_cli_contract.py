import unittest
from pathlib import Path


class CleanCliContractTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

    def test_clean_formatters_are_used(self):
        for formatter in (
            "format_profile_status",
            "format_network_inventory",
            "format_watch_baseline",
            "format_file_index",
            "format_integrations",
            "format_dashboard_preview",
        ):
            self.assertIn(formatter, self.cli)

    def test_raw_commands_exist(self):
        for command in (
            "/profile status raw",
            "/watch baseline raw",
            "/files index raw",
            "/integrations raw",
            "/dashboard raw",
            "/network inventory raw",
            "/cyber audit raw",
        ):
            self.assertIn(f'lower == "{command}"', self.cli)

    def test_cyber_commands_exist(self):
        for command in (
            "/cyber status",
            "/cyber curriculum",
            "/cyber audit",
        ):
            self.assertIn(f'lower == "{command}"', self.cli)


if __name__ == "__main__":
    unittest.main()
