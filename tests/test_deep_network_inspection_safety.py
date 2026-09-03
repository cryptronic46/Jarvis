import unittest
from pathlib import Path


class DeepNetworkInspectionSafetyTests(unittest.TestCase):
    def test_powershell_is_read_only(self):
        text = Path(
            "jarvis_core/services/deep_network_inspection.py"
        ).read_text(encoding="utf-8")

        expected_reads = (
            "Get-NetTCPConnection",
            "Get-NetUDPEndpoint",
            "Get-AuthenticodeSignature",
            "Get-CimInstance Win32_Service",
            "Get-NetFirewallRule",
            "Get-NetFirewallPortFilter",
            "Get-NetFirewallApplicationFilter",
        )
        for item in expected_reads:
            self.assertIn(item, text)

        forbidden = (
            "Set-NetFirewall",
            "New-NetFirewallRule",
            "Remove-NetFirewallRule",
            "Stop-Process",
            "Stop-Service",
            "Set-Service",
            "Remove-Item",
            "Set-ItemProperty",
            "Invoke-WebRequest",
            "curl ",
            "wget ",
        )
        for item in forbidden:
            self.assertNotIn(item, text)

    def test_no_external_ip_reputation_calls(self):
        text = Path(
            "jarvis_core/services/deep_network_inspection.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("requests.", text)
        self.assertNotIn("urlopen(", text)
        self.assertNotIn("VirusTotal", text)
        self.assertNotIn("AbuseIPDB", text)

    def test_expected_is_not_claimed_as_proven_safe(self):
        text = Path(
            "jarvis_core/services/deep_network_inspection.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "não é uma garantia absoluta de benignidade",
            text,
        )


if __name__ == "__main__":
    unittest.main()
