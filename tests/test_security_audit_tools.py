import unittest
from unittest.mock import patch

from jarvis_core.tools.security_audit import (
    _ip_classification,
    _security_summary,
    get_admin_accounts,
)


class SecurityAuditToolTests(unittest.TestCase):
    def test_ip_scope_classification(self):
        self.assertEqual(_ip_classification("127.0.0.1"), "loopback")
        self.assertEqual(_ip_classification("192.168.1.50"), "private")
        self.assertEqual(_ip_classification("8.8.8.8"), "public")

    @patch("jarvis_core.tools.security_audit._run_fixed_powershell_json")
    def test_admins_compare_current_user_by_sid(self, ps):
        ps.return_value = {
            "ok": True,
            "current": {"name": "PC\\Tiago", "sid": "S-1-5-21-1000", "is_admin": True},
            "local_users": [
                {"name": "Tiago", "sid": "S-1-5-21-1000", "disabled": False},
                {"name": "Administrator", "sid": "S-1-5-21-500", "disabled": True},
            ],
            "administrators": [
                {"name": "Tiago", "domain": "PC", "sid": "S-1-5-21-1000", "type": "Win32_UserAccount", "disabled": False},
                {"name": "Administrator", "domain": "PC", "sid": "S-1-5-21-500", "type": "Win32_UserAccount", "disabled": True},
            ],
        }
        result = get_admin_accounts()
        self.assertTrue(result["ok"])
        self.assertTrue(result["current_user"]["in_local_administrators_group"])
        self.assertTrue(result["only_current_enabled_admin_detected"])

    def test_remote_session_is_stronger_indicator(self):
        admins = {
            "current_user": {"name": "PC\\Tiago", "token_is_admin": True},
            "other_enabled_or_unknown_admin_principals": [],
            "only_current_enabled_admin_detected": True,
        }
        sessions = {
            "ok": True,
            "remote_sessions": [{"username": "Other", "is_remote": True}],
            "other_user_sessions": [{"username": "Other", "is_remote": True}],
        }
        network = {"remote_access_software_running": []}
        posture = {"smb_sessions": [], "firewall": [], "defender": {}}
        summary = _security_summary(admins, sessions, network, posture)
        self.assertTrue(summary["active_remote_access_detected"])
        self.assertEqual(summary["remote_interactive_session_count"], 1)


if __name__ == "__main__":
    unittest.main()
