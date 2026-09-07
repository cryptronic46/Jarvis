import unittest
from pathlib import Path


class DashboardContractTests(unittest.TestCase):
    def test_dashboard_has_current_sections(self):
        text = Path(
            "jarvis_core/tools/dashboard_tools.py"
        ).read_text(
            encoding="utf-8"
        )

        for key in (
            '"profile"',
            '"authority"',
            '"environment"',
            '"pc_health"',
            '"agenda"',
            '"security_watch"',
            '"network"',
            '"integrations"',
            '"ui_contract_version"',
        ):
            self.assertIn(
                key,
                text,
            )

        self.assertNotIn(
            '"privacy"',
            text,
        )
        self.assertIn(
            '"ui_contract_version": 2',
            text,
        )
        self.assertIn(
            "get_autonomy_status",
            text,
        )


if __name__ == "__main__":
    unittest.main()
