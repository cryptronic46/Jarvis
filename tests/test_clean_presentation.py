import unittest

from jarvis_core.services.presentation import (
    format_profile_status,
    format_network_inventory,
    format_watch_baseline,
    format_file_index,
    format_integrations,
    format_dashboard_preview,
)


class CleanPresentationTests(unittest.TestCase):
    def test_profile_status_hides_arrays(self):
        text = format_profile_status({
            "ok": True,
            "active_profile": {
                "display_name": "Tiago",
                "address_as": "Senhor",
                "role": "owner",
                "voice_profile": "owner",
                "allowed_tools": ["*"],
            },
            "profiles": [{"role": "owner"}, {"role": "restricted"}],
            "voice_binding_enforcement": False,
        })
        self.assertIn("PERFIL", text)
        self.assertIn("acesso total", text)
        self.assertNotIn("allowed_tools", text)
        self.assertNotIn("{", text)

    def test_inventory_only_shows_active_devices(self):
        text = format_network_inventory({
            "ok": True,
            "devices": [
                {"ip": "192.168.1.1", "active": True, "label": "Router"},
                {"ip": "192.168.1.65", "active": True, "label": None},
                {"ip": "192.168.1.121", "active": False, "label": None},
            ],
            "new_devices": [
                {"ip": "192.168.1.121", "active": False},
            ],
        })
        self.assertIn("192.168.1.1", text)
        self.assertIn("192.168.1.65", text)
        self.assertNotIn("192.168.1.121", text)
        self.assertNotIn("mac", text.lower())

    def test_baseline_is_human(self):
        text = format_watch_baseline({
            "ok": True,
            "fingerprint": {
                "other_admin_sids": [],
                "remote_sessions": [],
                "remote_access_software": [],
                "active_lan_macs": ["AA", "BB"],
                "firewall_all_enabled": True,
                "defender_realtime_enabled": True,
                "rdp_enabled": False,
                "remote_assistance_enabled": False,
            },
        })
        self.assertIn("BASELINE CRIADA", text)
        self.assertIn("Firewall: OK", text)
        self.assertNotIn("other_admin_sids", text)

    def test_file_index_hides_full_windows_paths(self):
        text = format_file_index({
            "ok": True,
            "indexed": 1114,
            "skipped": 0,
            "roots": [
                "C:\\Users\\tiago\\Desktop",
                "C:\\Users\\tiago\\Documents",
            ],
        })
        self.assertIn("1114", text)
        self.assertIn("Desktop", text)
        self.assertNotIn("C:\\Users\\tiago", text)

    def test_integrations_are_compact(self):
        text = format_integrations({
            "ok": True,
            "local_agenda": {"configured": True, "status": "READY"},
            "google_calendar": {"configured": False, "status": "NOT_CONFIGURED"},
            "email": {"configured": False, "status": "NOT_CONFIGURED"},
            "smart_home": {"configured": False, "status": "NOT_CONFIGURED"},
        })
        self.assertIn("Agenda local: Pronto", text)
        self.assertIn("Prontas: 1/4", text)
        self.assertNotIn("note", text)

    def test_dashboard_preview_is_not_json(self):
        text = format_dashboard_preview({
            "ok": True,
            "profile": {"display_name": "Tiago", "address_as": "Senhor", "role": "owner"},
            "privacy": {"privacy_mode": False, "cloud_allowed": True},
            "environment": {
                "location": {"label": "Furadouro, Ovar"},
                "weather": {
                    "temperature_c": 21.6,
                    "relative_humidity_percent": 74,
                    "condition": "parcialmente nublado",
                },
                "marine": {"state": "agitado", "wave_height_m": 1.86},
            },
            "pc_health": {
                "overall": "ok",
                "cpu_percent": 4.2,
                "memory": {"percent": 44.2},
                "gpu": {"temperature_c": 33},
            },
            "agenda": {"today_count": 0, "pending_count": 0},
            "security_watch": {"baseline_exists": True, "alerts": []},
            "network": {"active_count": 3},
            "integrations": {
                "local_agenda": {"configured": True, "status": "READY"},
                "google_calendar": {"configured": False, "status": "NOT_CONFIGURED"},
                "email": {"configured": False, "status": "NOT_CONFIGURED"},
                "smart_home": {"configured": False, "status": "NOT_CONFIGURED"},
            },
        })
        self.assertIn("DASHBOARD — PRÉ-VISUALIZAÇÃO", text)
        self.assertIn("Furadouro", text)
        self.assertIn("Rede: 3", text)
        self.assertNotIn('"weather"', text)
        self.assertNotIn("{", text)


if __name__ == "__main__":
    unittest.main()
