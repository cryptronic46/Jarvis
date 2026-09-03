import unittest
from pathlib import Path


class DefenderPowerShellCompatTests(unittest.TestCase):
    def test_signature_date_is_precomputed_for_powershell_51(self):
        text = Path(
            "jarvis_core/tools/security_audit.py"
        ).read_text(encoding="utf-8")
        self.assertIn("$signatureUpdated = $null", text)
        self.assertIn(
            "antivirus_signature_last_updated = $signatureUpdated",
            text,
        )
        self.assertNotIn(
            "antivirus_signature_last_updated = (\\n"
            "                if (",
            text,
        )


if __name__ == "__main__":
    unittest.main()
