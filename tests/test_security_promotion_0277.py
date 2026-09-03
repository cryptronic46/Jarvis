import unittest
from pathlib import Path


class SecurityPromotion0277Tests(unittest.TestCase):
    def test_repair_security_baseline_has_no_0276_version_gate(self):
        text = Path("repair_security_baseline.ps1").read_text(encoding="utf-8")
        self.assertNotIn('$ExpectedVersion = "0.27.6"', text)
        self.assertIn('$ReleaseVersion = [string]$Manifest.release', text)
        self.assertIn('CoreVersion', text)
        self.assertIn('nao corresponde ao manifesto', text)

    def test_setup_hash_verifies_before_unblocking_nested_scripts(self):
        text = Path("setup.ps1").read_text(encoding="utf-8")
        verify = text.index('Get-FileHash -Algorithm SHA256')
        unblock = text.index('Unblock-File -LiteralPath $Path')
        repair = text.index(r'& ".\repair_security_baseline.ps1"')
        self.assertLess(verify, unblock)
        self.assertLess(unblock, repair)
        self.assertIn('hash alterado apos Unblock-File', text)

    def test_updater_unblocks_verified_files_by_default(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8")
        self.assertIn('[switch]$PreserveMarkOfTheWeb', text)
        self.assertIn('REMOVIDO APOS SHA-256', text)
        self.assertIn('DESTINO-POS-UNBLOCK', text)


if __name__ == "__main__":
    unittest.main()
