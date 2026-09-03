import unittest

from jarvis_core.services.deep_network_inspection import _classification, _group_logical_listeners


class DeepNetworkInspectionV2Tests(unittest.TestCase):
    def test_pid_zero_connection_is_transient(self):
        classification, severity, reasons = _classification(
            process={"pid": 0}, meta={}, row={"remote": {"ip": "4.208.165.241", "port": 443}},
            firewall_rules=[], kind="connection",
        )
        self.assertEqual(classification, "transient")
        self.assertEqual(severity, "low")

    def test_windows_core_canonical_path_is_observed_without_signature(self):
        classification, severity, reasons = _classification(
            process={"pid": 1234, "name": "svchost", "path": r"C:\Windows\System32\svchost.exe"},
            meta={"name": "svchost", "path": r"C:\Windows\System32\svchost.exe", "signature_status": None},
            row={"local": {"ip": "0.0.0.0", "port": 135, "scope": "unspecified"}},
            firewall_rules=[], kind="listener",
        )
        self.assertEqual(classification, "observed")
        self.assertEqual(severity, "low")

    def test_dual_stack_pair_groups_logically(self):
        rows = [
            {"protocol": "TCP", "status": "LISTEN", "pid": 10,
             "local": {"ip": "0.0.0.0", "port": 135, "scope": "unspecified"},
             "process": {"name": "svchost"}, "classification": "expected"},
            {"protocol": "TCP", "status": "LISTEN", "pid": 10,
             "local": {"ip": "::", "port": 135, "scope": "unspecified"},
             "process": {"name": "svchost"}, "classification": "expected"},
        ]
        grouped = _group_logical_listeners(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["raw_count"], 2)
        self.assertTrue(grouped[0]["dual_stack"])


if __name__ == "__main__":
    unittest.main()
