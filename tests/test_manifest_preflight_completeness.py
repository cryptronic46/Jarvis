import unittest
from pathlib import Path


class ManifestPreflightCompletenessTests(unittest.TestCase):
    def test_updater_rejects_unmanifested_controlled_files(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-ControlledReleaseFiles", text)
        self.assertIn("Manifest.scope.trees", text)
        self.assertIn("Manifest.scope.top_level", text)
        self.assertIn("MissingFromManifest", text)
        self.assertIn("ManifestOutsideScope", text)
        self.assertIn("ficheiros controlados fora do manifesto", text)

    def test_verifier_checks_entire_controlled_scope(self):
        text = Path("verify_release.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-ControlledReleaseFiles", text)
        self.assertIn("Manifest.scope.trees", text)
        self.assertIn("Manifest.scope.top_level", text)
        self.assertIn("MissingFromManifest", text)
        self.assertIn("ManifestOutsideScope", text)
        self.assertIn("Ficheiros controlados inesperados: 0", text)


if __name__ == "__main__":
    unittest.main()
