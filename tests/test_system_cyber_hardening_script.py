import unittest
from pathlib import Path


class HardeningScriptTests(unittest.TestCase):
    def test_script_is_fixed_and_read_only(self):
        text = Path(
            "jarvis_core/services/system_cyber_audit.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Confirm-SecureBootUEFI", text)
        self.assertIn("Get-BitLockerVolume", text)
        self.assertIn("Get-SmbServerConfiguration", text)
        self.assertIn("Get-HotFix", text)
        self.assertIn("Get-MpComputerStatus", text)

        for forbidden in (
            "Set-MpPreference",
            "Set-NetFirewallProfile",
            "Set-SmbServerConfiguration",
            "Disable-WindowsOptionalFeature",
            "Enable-WindowsOptionalFeature",
            "Remove-ItemProperty",
            "Set-ItemProperty",
        ):
            self.assertNotIn(forbidden, text)

    def test_cve_limitation_is_explicit(self):
        text = Path(
            "jarvis_core/services/system_cyber_audit.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "não faz correspondência exata de CVEs",
            text,
        )


if __name__ == "__main__":
    unittest.main()
