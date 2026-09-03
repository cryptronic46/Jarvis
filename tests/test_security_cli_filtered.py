import unittest
from pathlib import Path


class SecurityCliFilteredTests(unittest.TestCase):
    def setUp(self):
        self.cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

    def test_security_scan_is_filtered_by_default(self):
        self.assertIn('if lower == "/security scan":', self.cli)
        self.assertIn("format_security_overview(result)", self.cli)
        self.assertIn('if lower == "/security scan full":', self.cli)

    def test_network_status_is_filtered_by_default(self):
        self.assertIn('if lower == "/network status":', self.cli)
        self.assertIn("format_network_overview(result)", self.cli)
        self.assertIn('if lower == "/network status full":', self.cli)


if __name__ == "__main__":
    unittest.main()
