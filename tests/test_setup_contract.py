import unittest
from pathlib import Path


class SetupContractTests(unittest.TestCase):
    def test_setup_stops_on_native_failures_and_cleans_stale_tests(self):
        text = Path("setup.ps1").read_text(encoding="utf-8")
        self.assertIn("$LASTEXITCODE", text)
        self.assertIn("Remove-Item", text)
        self.assertIn("Invoke-Checked", text)
        self.assertIn('Filter "__pycache__"', text)
        self.assertIn('Filter "*.pyc"', text)
        self.assertIn("Settings.ensure_file_schema", text)

    def test_setup_forces_external_ai_hard_block(self):
        text = Path("setup.ps1").read_text(encoding="utf-8")
        self.assertIn("external AI HARD BLOCKED", text)
        self.assertIn("'external_ai_enabled':False", text)
        self.assertIn("'cloud_enabled':False", text)
        self.assertIn("'expert_escalation_enabled':False", text)

    def test_version_is_0193(self):
        text = Path("jarvis_core/__init__.py").read_text(encoding="utf-8")
        self.assertIn('0.27.8', text)

    def test_setup_derives_expected_tests_from_release_manifest(self):
        text = Path("setup.ps1").read_text(encoding="utf-8")
        self.assertIn('release_manifest.json', text)
        self.assertIn('$ReleaseManifest.files', text)
        self.assertIn("tests/test_*.py", text)
        self.assertIn("single source of truth", text)
        self.assertNotIn('"test_cloud_rate_limit_semantics.py",', text)
        self.assertNotIn('"test_personal_memory_semantics.py",', text)
        self.assertNotIn('"test_manifest_preflight_completeness.py",', text)


if __name__ == "__main__":
    unittest.main()
