import unittest
from pathlib import Path


class SecurityAuditContractTests(unittest.TestCase):
    def setUp(self):
        self.audit = Path("jarvis_core/tools/security_audit.py").read_text(encoding="utf-8")
        self.registry = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        self.cloud = Path("jarvis_core/core/cloud_brain.py").read_text(encoding="utf-8")

    def test_security_tools_registered_read_only(self):
        for name in (
            "get_admin_accounts",
            "get_active_user_sessions",
            "get_network_security_snapshot",
            "get_windows_security_posture",
            "run_security_audit",
        ):
            self.assertIn(f'"{name}"', self.registry)
        self.assertIn("RiskLevel.READ_ONLY", self.registry)

    def test_fixed_powershell_only(self):
        self.assertIn("ADMIN_ACCOUNTS_SCRIPT = r'''", self.audit)
        self.assertIn("WINDOWS_PROTECTION_SCRIPT = r'''", self.audit)
        self.assertIn("NETWORK_NEIGHBORS_SCRIPT = r'''", self.audit)
        self.assertIn("No user/LLM text is interpolated", self.audit)

    def test_neighbor_inspection_is_passive(self):
        self.assertIn("Get-NetNeighbor", self.audit)
        self.assertNotIn("Test-Connection", self.audit)
        self.assertNotIn("nmap", self.audit.lower())

    def test_detailed_audit_is_not_cloud_allowlisted(self):
        start = self.cloud.index("DEFAULT_ALLOWED_TOOLS = {")
        end = self.cloud.index("}", start)
        section = self.cloud[start:end]
        for name in (
            "get_admin_accounts",
            "get_active_user_sessions",
            "get_network_security_snapshot",
            "get_windows_security_posture",
            "run_security_audit",
        ):
            self.assertNotIn(f'"{name}"', section)


if __name__ == "__main__":
    unittest.main()
