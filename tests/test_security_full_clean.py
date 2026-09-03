import unittest

from jarvis_core.tools.security_audit import (
    format_security_full,
)


class SecurityFullCleanTests(unittest.TestCase):
    def sample(self):
        return {
            "ok": True,
            "summary": {
                "level": "attention",
                "current_user": "GAMINGRTX\\\\tiago",
                "current_user_admin": True,
                "only_current_enabled_admin_detected": True,
                "other_admin_count": 0,
                "other_session_count": 0,
                "remote_interactive_session_count": 0,
                "smb_session_count": 0,
                "remote_access_software_count": 0,
                "active_remote_access_detected": False,
                "rdp_enabled": False,
                "remote_assistance_enabled": True,
                "firewall_all_enabled": True,
                "defender_realtime_enabled": True,
                "network": {
                    "active_interfaces": [{
                        "name": "Wi-Fi",
                        "ipv4": ["192.168.1.70"],
                        "speed_mbps": 866,
                    }],
                    "lan_device_count": 3,
                    "public_connection_count": 8,
                },
                "findings": [{
                    "severity": "attention",
                    "message": (
                        "A Assistência Remota do Windows "
                        "está permitida."
                    ),
                }],
            },
            "accounts": {
                "current_user": {
                    "name": "GAMINGRTX\\\\tiago",
                    "token_is_admin": False,
                    "in_local_administrators_group": True,
                },
                "other_enabled_or_unknown_admin_principals": [],
            },
            "sessions": {
                "sessions": [{
                    "session_id": 1,
                    "username": "tiago",
                    "is_remote": False,
                }],
            },
            "network": {
                "counts": {
                    "lan_devices_active": 3,
                    "public_established": 8,
                },
                "filtered": {
                    "active_interfaces": [{
                        "name": "Wi-Fi",
                        "ipv4": ["192.168.1.70"],
                        "speed_mbps": 866,
                    }],
                },
                "remote_access_software_running": [],
            },
            "windows_security": {
                "defender": {
                    "antivirus_signature_last_updated": (
                        "2026-08-28T00:39:43+01:00"
                    ),
                },
            },
        }

    def test_full_is_sectioned_and_not_json(self):
        text = format_security_full(
            self.sample()
        )
        for section in (
            "CONTA",
            "SESSÕES",
            "PROTEÇÃO",
            "REDE",
            "ATENÇÃO",
        ):
            self.assertIn(section, text)

        self.assertIn(
            "Outros administradores habilitados: 0",
            text,
        )
        self.assertIn(
            "Acesso remoto ativo: não detetado",
            text,
        )
        self.assertIn(
            "Defender em tempo real: ativo",
            text,
        )
        self.assertIn(
            "Ligação principal: Wi-Fi · "
            "192.168.1.70 · 866 Mbps",
            text,
        )
        self.assertIn(
            "JSON bruto: /security scan raw",
            text,
        )

        # No raw JSON structure in normal full view.
        self.assertNotIn(
            '"summary":',
            text,
        )
        self.assertNotIn(
            '"accounts":',
            text,
        )
        self.assertNotIn(
            '"listening_ports":',
            text,
        )

    def test_full_is_reasonably_short(self):
        text = format_security_full(
            self.sample()
        )
        self.assertLessEqual(
            len(text.splitlines()),
            30,
        )


if __name__ == "__main__":
    unittest.main()
