import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.services.cyber_range import CyberRangeManager


class CyberRangeManagerTests(unittest.TestCase):
    def make_manager(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        manager = CyberRangeManager(Path(tmp.name) / "range.json")
        return manager

    def test_private_target_is_not_lab_by_default(self):
        manager = self.make_manager()
        result = manager.classify("192.168.56.10")
        self.assertEqual(result["scope"], "PRIVATE_UNAUTHORIZED")
        self.assertFalse(result["authorized"])

    def test_owner_cli_can_add_private_lab_scope(self):
        manager = self.make_manager()
        added = manager.add_lab_scope("192.168.56.0/24", "VirtualBox Lab")
        self.assertTrue(added["ok"])
        result = manager.classify("192.168.56.10")
        self.assertEqual(result["scope"], "LAB")
        self.assertTrue(result["authorized"])
        self.assertEqual(result["label"], "VirtualBox Lab")

    def test_public_scope_cannot_be_added(self):
        manager = self.make_manager()
        result = manager.add_lab_scope("8.8.8.8")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "LAB_SCOPE_MUST_BE_PRIVATE")

    def test_scope_cannot_be_too_broad(self):
        manager = self.make_manager()
        result = manager.add_lab_scope("10.0.0.0/8")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "LAB_SCOPE_TOO_BROAD")

    def test_owner_machine_beats_lab_network(self):
        manager = self.make_manager()
        manager.add_lab_scope("192.168.56.0/24")
        with patch.object(manager, "_owner_addresses", return_value={"192.168.56.1"}):
            result = manager.classify("192.168.56.1")
        self.assertEqual(result["scope"], "OWNER_MACHINE")
        self.assertFalse(result["authorized"])

    def test_probe_is_blocked_until_target_is_lab(self):
        manager = self.make_manager()
        result = manager.probe("192.168.56.10", [22])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "TARGET_NOT_AUTHORIZED_LAB")

    def test_probe_is_bounded_and_only_reports_connectivity(self):
        manager = self.make_manager()
        manager.add_lab_scope("192.168.56.10", "Metasploitable")

        class DummyConnection:
            def close(self):
                pass

        def fake_connect(addr, timeout):
            if addr[1] == 22:
                return DummyConnection()
            raise OSError("closed")

        with patch("jarvis_core.services.cyber_range.socket.create_connection", side_effect=fake_connect):
            result = manager.probe("192.168.56.10", [22, 80])
        self.assertTrue(result["ok"])
        self.assertEqual(result["open_ports"], [22])
        self.assertEqual(result["closed_or_filtered_ports"], [80])
        self.assertEqual(result["probe"], "tcp_connect")


if __name__ == "__main__":
    unittest.main()
