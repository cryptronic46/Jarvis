import unittest
from pathlib import Path


class CoreAddonBoundaryTests(unittest.TestCase):
    def test_updater_preserves_external_addons(self):
        text = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'add-ons/pastas externas (ex.: Wallpaper)',
            text,
        )

        # /MIR is allowed only on these controlled trees.
        self.assertIn('Mirror-Tree "jarvis_core"', text)
        self.assertIn('Mirror-Tree "tests"', text)
        self.assertIn('Mirror-Tree "defaults"', text)

        self.assertNotIn(
            'Mirror-Tree "JARVIS_Live_Wallpaper',
            text,
        )

    def test_updater_cleans_only_old_core_audits(self):
        text = Path(
            "update_core.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'function Remove-StaleManagedTopLevelFiles',
            text,
        )
        self.assertIn(
            '-Filter "AUDIT_0.*.md"',
            text,
        )
        self.assertIn(
            '$CurrentAudit = "AUDIT_0.27.8.md"',
            text,
        )

    def test_current_audit_is_installable(self):
        self.assertTrue(
            Path("AUDIT_0.27.8.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
