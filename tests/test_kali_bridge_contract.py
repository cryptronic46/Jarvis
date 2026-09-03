import unittest
from pathlib import Path


class KaliBridgeContractTests(unittest.TestCase):
    def test_tools_and_owner_cli_boundary_exist(self):
        registry = Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        brain = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        for name in (
            "get_kali_bridge_status",
            "get_kali_tool_inventory",
            "run_kali_nmap_service_scan",
            "run_kali_whatweb_fingerprint",
            "run_kali_nikto_safe_web_scan",
        ):
            self.assertIn(name, registry)
        self.assertIn('lower.startswith("/cyber kali configure ")', cli)
        self.assertIn("kali_bridge.configure(", cli)
        self.assertNotIn('"configure_kali_bridge"', registry)
        self.assertIn("no arbitrary remote shell", brain.lower())

    def test_service_revalidates_both_bridge_and_target(self):
        text = Path("jarvis_core/services/kali_bridge.py").read_text(encoding="utf-8")
        self.assertIn("KALI_HOST_NO_LONGER_AUTHORIZED_LAB", text)
        self.assertIn("TARGET_NOT_AUTHORIZED_LAB", text)
        self.assertIn("cyber_range_manager().classify", text)
        self.assertIn("BatchMode=yes", text)
        self.assertIn("StrictHostKeyChecking=accept-new", text)


if __name__ == "__main__":
    unittest.main()
