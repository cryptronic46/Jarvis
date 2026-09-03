import unittest
from pathlib import Path


class AppControlObserveOnlyTests(unittest.TestCase):
    def setUp(self):
        self.trust = Path("setup_appcontrol_trust.ps1").read_text(encoding="utf-8-sig")

    def test_compat_script_is_observe_only(self):
        self.assertIn("OBSERVE-ONLY", self.trust)
        self.assertIn("diagnose_app_control.ps1", self.trust)
        for forbidden in ("New-CIPolicyRule", "ConvertFrom-CIPolicy", "Set-RuleOption", "CiTool.exe", "-up", "-rp"):
            self.assertNotIn(forbidden, self.trust)

    def test_enforcement_modes_do_not_enforce(self):
        self.assertIn("Modo '{0}' desativado", self.trust)
        self.assertIn("não tem capacidade de enforcement", self.trust)

if __name__ == "__main__":
    unittest.main()
