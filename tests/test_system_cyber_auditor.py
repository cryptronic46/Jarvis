import unittest
from unittest.mock import patch

from jarvis_core.services.system_cyber_audit import (
    analyze_system_cybersecurity,
    format_system_cyber_audit,
)


BASE_AUDIT = {
    "ok": True,
    "summary": {
        "current_user": "PC\\owner",
        "current_user_admin": True,
        "only_current_enabled_admin_detected": True,
        "remote_interactive_session_count": 0,
        "smb_session_count": 0,
        "remote_access_software_count": 0,
        "firewall_all_enabled": True,
        "defender_realtime_enabled": True,
        "rdp_enabled": False,
        "network": {
            "lan_device_count": 3,
            "non_loopback_listener_count": 2,
            "public_connection_count": 6,
        },
    },
    "accounts": {
        "only_current_enabled_admin_detected": True,
        "other_enabled_or_unknown_admin_principals": [],
    },
    "sessions": {
        "ok": True,
        "remote_sessions": [],
    },
    "windows_security": {
        "rdp_enabled": False,
        "remote_assistance_enabled": False,
        "firewall": [
            {"name": "Domain", "enabled": True},
            {"name": "Private", "enabled": True},
            {"name": "Public", "enabled": True},
        ],
        "defender": {
            "real_time_protection_enabled": True,
        },
        "smb_sessions": [],
    },
    "network": {
        "counts": {
            "listeners_non_loopback": 2,
            "public_established": 6,
        },
        "filtered": {
            "non_loopback_listeners": [
                {
                    "local": {"ip": "0.0.0.0", "port": 1234},
                    "process": "example.exe",
                }
            ],
            "remote_connections": [],
            "active_lan_devices": [],
        },
        "remote_access_software_running": [],
    },
}

HARDENING = {
    "ok": True,
    "uac": {
        "enabled": 1,
        "consent_prompt_behavior_admin": 5,
        "prompt_on_secure_desktop": 1,
    },
    "rdp": {
        "nla_user_authentication": 1,
    },
    "smb": {
        "smb1_enabled": False,
        "smb2_enabled": True,
    },
    "secure_boot_supported": True,
    "secure_boot": True,
    "bitlocker": [
        {
            "mount_point": "C:",
            "volume_type": "OperatingSystem",
            "protection_status": "On",
            "encryption_percentage": 100,
        }
    ],
    "latest_hotfix": None,
    "defender_extended": {
        "antivirus_signature_age_days": 0,
    },
}


class FakeVault:
    def search(self, query, limit=3):
        return {
            "ok": True,
            "results": [{
                "id": 1,
                "title": "Security guidance",
                "publisher": "Microsoft",
                "source_id": "microsoft",
                "external_id": "root",
                "trust": "official",
                "provenance": "official-web-import",
                "url": "https://learn.microsoft.com/",
                "snippet": "Official guidance.",
            }],
        }


class SystemCyberAuditorTests(unittest.TestCase):
    @patch(
        "jarvis_core.services.system_cyber_audit.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.system_cyber_audit._powershell_hardening",
        return_value=HARDENING,
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.get_security_watch_status",
        return_value={"ok": True, "baseline_exists": True, "alerts": []},
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.run_security_audit",
        return_value=BASE_AUDIT,
    )
    def test_good_system_is_low_risk(
        self,
        audit,
        watch,
        hardening,
        vault,
    ):
        result = analyze_system_cybersecurity()
        self.assertTrue(result["ok"])
        self.assertEqual(result["risk"]["level"], "low")
        self.assertEqual(result["confidence"], "high")
        self.assertTrue(result["knowledge_references"])
        self.assertIn(
            "Não encontrei evidência direta de compromisso",
            result["conclusion"],
        )

    @patch(
        "jarvis_core.services.system_cyber_audit.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.system_cyber_audit._powershell_hardening",
        return_value={
            **HARDENING,
            "uac": {"enabled": 0},
            "smb": {"smb1_enabled": True},
        },
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.get_security_watch_status",
        return_value={
            "ok": True,
            "baseline_exists": True,
            "alerts": [{
                "severity": "critical",
                "code": "NEW_ADMIN",
                "message": "Novo administrador.",
            }],
        },
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.run_security_audit",
        return_value=BASE_AUDIT,
    )
    def test_baseline_critical_change_makes_risk_critical(
        self,
        audit,
        watch,
        hardening,
        vault,
    ):
        result = analyze_system_cybersecurity()
        self.assertEqual(result["risk"]["level"], "critical")
        codes = {x["code"] for x in result["findings"]}
        self.assertIn("UAC_DISABLED", codes)
        self.assertIn("SMB1_ENABLED", codes)
        self.assertIn("WATCH_NEW_ADMIN", codes)

    @patch(
        "jarvis_core.services.system_cyber_audit.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.system_cyber_audit._powershell_hardening",
        return_value=HARDENING,
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.get_security_watch_status",
        return_value={"ok": True, "baseline_exists": True, "alerts": []},
    )
    @patch(
        "jarvis_core.services.system_cyber_audit.run_security_audit",
        return_value=BASE_AUDIT,
    )
    def test_report_is_human_readable(
        self,
        audit,
        watch,
        hardening,
        vault,
    ):
        report = format_system_cyber_audit(
            analyze_system_cybersecurity("full"),
            full=True,
        )
        self.assertIn(
            "JARVIS — ANÁLISE DE CIBERSEGURANÇA",
            report,
        )
        self.assertIn("Risco global: BAIXO", report)
        self.assertIn("CONHECIMENTO CORRELACIONADO", report)
        self.assertIn("LIMITAÇÕES", report)
        self.assertNotIn('"findings"', report)


if __name__ == "__main__":
    unittest.main()
