import unittest
from unittest.mock import patch

from jarvis_core.services.deep_network_inspection import (
    inspect_network_deep,
    format_deep_network_inspection,
)


CONNECTIONS = [
    {
        "protocol": "TCP",
        "status": "LISTEN",
        "pid": 4,
        "local": {
            "ip": "0.0.0.0",
            "port": 445,
            "scope": "unspecified",
        },
        "remote": None,
    },
    {
        "protocol": "TCP",
        "status": "LISTEN",
        "pid": 100,
        "local": {
            "ip": "0.0.0.0",
            "port": 7777,
            "scope": "unspecified",
        },
        "remote": None,
    },
    {
        "protocol": "TCP",
        "status": "ESTABLISHED",
        "pid": 200,
        "local": {
            "ip": "192.168.1.70",
            "port": 53000,
            "scope": "private",
        },
        "remote": {
            "ip": "1.1.1.1",
            "port": 443,
            "scope": "public",
        },
    },
]


ENRICHMENT = {
    "ok": True,
    "processes": [
        {
            "pid": 100,
            "name": "mystery",
            "path": r"C:\Tools\mystery.exe",
            "signature_status": "NotSigned",
            "signer_subject": None,
            "company": None,
            "product": None,
            "file_version": "1.0",
        },
        {
            "pid": 200,
            "name": "brave",
            "path": r"C:\Program Files\Brave\brave.exe",
            "signature_status": "Valid",
            "signer_subject": "CN=Brave Software, Inc.",
            "company": "Brave Software, Inc.",
            "product": "Brave Browser",
            "file_version": "1.0",
        },
    ],
    "services": [],
    "inbound_allow_rules": [
        {
            "name": "Mystery",
            "display_name": "Mystery",
            "profile": "Private",
            "protocol": "TCP",
            "local_port": "7777",
            "program": r"C:\Tools\mystery.exe",
            "service": None,
        }
    ],
    "errors": [],
}


class FakeVault:
    def search(self, query, limit=3):
        return {
            "ok": True,
            "results": [{
                "title": "Network security guidance",
                "publisher": "Microsoft",
                "source_id": "microsoft",
                "external_id": "root",
                "trust": "official",
                "url": "https://learn.microsoft.com/",
            }],
        }


class DeepNetworkInspectionTests(unittest.TestCase):
    @patch(
        "jarvis_core.services.deep_network_inspection.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._run_enrichment",
        return_value=ENRICHMENT,
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._collect_connections",
        return_value=(CONNECTIONS, None),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection.get_network_security_snapshot",
        return_value={
            "ok": True,
            "counts": {
                "listeners_non_loopback": 2,
                "public_established": 1,
            },
        },
    )
    def test_unsigned_listener_is_review(
        self,
        snapshot,
        connections,
        enrichment,
        vault,
    ):
        result = inspect_network_deep("full")
        self.assertTrue(result["ok"])
        item = next(
            row for row in result["listeners"]
            if (row.get("local") or {}).get("port") == 7777
        )
        self.assertEqual(item["classification"], "review")
        self.assertEqual(item["severity"], "moderate")
        self.assertTrue(
            item["firewall"]["confirmed_allow_rule"]
        )

    @patch(
        "jarvis_core.services.deep_network_inspection.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._run_enrichment",
        return_value=ENRICHMENT,
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._collect_connections",
        return_value=(CONNECTIONS, None),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection.get_network_security_snapshot",
        return_value={"ok": True, "counts": {}},
    )
    def test_system_listener_is_expected(
        self,
        snapshot,
        connections,
        enrichment,
        vault,
    ):
        result = inspect_network_deep()
        item = next(
            row for row in result["listeners"]
            if row.get("pid") == 4
        )
        self.assertEqual(item["classification"], "expected")

    @patch(
        "jarvis_core.services.deep_network_inspection.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._run_enrichment",
        return_value=ENRICHMENT,
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._collect_connections",
        return_value=(CONNECTIONS, None),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection.get_network_security_snapshot",
        return_value={"ok": True, "counts": {}},
    )
    def test_signed_browser_https_is_expected(
        self,
        snapshot,
        connections,
        enrichment,
        vault,
    ):
        result = inspect_network_deep()
        item = result["public_connections"][0]
        self.assertEqual(
            item["classification"],
            "expected",
        )

    @patch(
        "jarvis_core.services.deep_network_inspection.cyber_vault",
        return_value=FakeVault(),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._run_enrichment",
        return_value=ENRICHMENT,
    )
    @patch(
        "jarvis_core.services.deep_network_inspection._collect_connections",
        return_value=(CONNECTIONS, None),
    )
    @patch(
        "jarvis_core.services.deep_network_inspection.get_network_security_snapshot",
        return_value={"ok": True, "counts": {}},
    )
    def test_full_report_contains_signature_and_firewall(
        self,
        snapshot,
        connections,
        enrichment,
        vault,
    ):
        report = format_deep_network_inspection(
            inspect_network_deep("full"),
            full=True,
        )
        self.assertIn(
            "JARVIS — DEEP SECURITY INSPECTION",
            report,
        )
        self.assertIn("mystery", report.lower())
        self.assertIn("NotSigned", report)
        self.assertIn("firewall allow SIM", report)


if __name__ == "__main__":
    unittest.main()
