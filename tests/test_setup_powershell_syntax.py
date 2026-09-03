import json
import re
import unittest
from pathlib import Path


class SetupPowerShellSyntaxTests(unittest.TestCase):
    def setUp(self):
        self.text = Path("setup.ps1").read_text(encoding="utf-8")
        self.manifest = json.loads(
            Path("release_manifest.json").read_text(encoding="utf-8")
        )

    def test_expected_tests_are_derived_from_manifest(self):
        match = re.search(
            r"\$expectedTests\s*=\s*@\((.*?)\n\)",
            self.text,
            flags=re.S,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertIn("$ReleaseManifest.files", body)
        self.assertIn("tests/test_*.py", body)
        self.assertIn("Sort-Object -Unique", body)

    def test_smart_app_control_test_is_manifest_controlled(self):
        paths = {
            str(item["path"]).replace("\\", "/")
            for item in self.manifest["files"]
        }
        self.assertIn(
            "tests/test_smart_app_control_compat.py",
            paths,
        )

    def test_setup_does_not_duplicate_test_inventory(self):
        # A static quoted test list was the root cause of the 0.19.7
        # Windows failure. The manifest must remain the only inventory.
        self.assertNotRegex(
            self.text,
            r'(?m)^\s*"test_[^"]+\.py",?\s*$',
        )
        self.assertIn("single source of truth", self.text)


if __name__ == "__main__":
    unittest.main()
