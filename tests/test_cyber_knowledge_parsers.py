import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.cyber_knowledge import CyberKnowledgeVault


class CyberKnowledgeParserTests(unittest.TestCase):
    def make(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        src = root / "sources.json"
        src.write_text('{"sources":[]}', encoding="utf-8")
        vault = CyberKnowledgeVault(
            root / "db.sqlite3",
            src,
            root / "state.json",
        )
        return tmp, vault

    def test_cisa_kev_parser_creates_cve(self):
        tmp, vault = self.make()
        try:
            raw = json.dumps({
                "catalogVersion": "test",
                "vulnerabilities": [{
                    "cveID": "CVE-2099-0001",
                    "vendorProject": "Vendor",
                    "product": "Product",
                    "vulnerabilityName": "Example",
                    "shortDescription": "Actively exploited example.",
                    "requiredAction": "Apply mitigations.",
                    "dateAdded": "2099-01-01",
                    "dueDate": "2099-01-20",
                    "knownRansomwareCampaignUse": "Unknown"
                }]
            }).encode()
            result = vault._sync_cisa_kev({
                "id": "cisa_kev",
                "url": "https://www.cisa.gov/feed.json",
                "category": "vulnerability-intelligence",
                "publisher": "CISA",
                "trust": "official"
            }, raw)
            self.assertEqual(result["documents"], 1)
            found = vault.search("CVE-2099-0001")
            self.assertTrue(found["results"])
            self.assertEqual(
                found["results"][0]["external_id"],
                "CVE-2099-0001",
            )
        finally:
            tmp.cleanup()

    def test_mitre_parser_creates_attack_id(self):
        tmp, vault = self.make()
        try:
            raw = json.dumps({
                "objects": [{
                    "type": "attack-pattern",
                    "id": "attack-pattern--x",
                    "name": "Command and Scripting Interpreter",
                    "description": "Adversaries may abuse command interpreters.",
                    "created": "2020-01-01T00:00:00Z",
                    "modified": "2026-01-01T00:00:00Z",
                    "external_references": [{
                        "source_name": "mitre-attack",
                        "external_id": "T1059",
                        "url": "https://attack.mitre.org/techniques/T1059/"
                    }],
                    "kill_chain_phases": [{
                        "kill_chain_name": "mitre-attack",
                        "phase_name": "execution"
                    }],
                    "x_mitre_platforms": ["Windows", "Linux"]
                }]
            }).encode()
            result = vault._sync_mitre_attack({
                "id": "mitre_attack_enterprise",
                "url": "https://raw.githubusercontent.com/test.json",
                "category": "threat-behavior",
                "publisher": "MITRE",
                "trust": "official-repository"
            }, raw)
            self.assertEqual(result["documents"], 1)
            found = vault.search("T1059")
            self.assertTrue(found["results"])
            self.assertEqual(found["results"][0]["external_id"], "T1059")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
