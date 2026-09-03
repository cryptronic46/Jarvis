import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.cyber_knowledge import CyberKnowledgeVault


class CyberKnowledgeVaultTests(unittest.TestCase):
    def make(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        sources = root / "sources.json"
        sources.write_text(
            json.dumps({
                "sources": [{
                    "id": "test",
                    "name": "Test",
                    "publisher": "Official Test",
                    "kind": "html",
                    "url": "https://www.nist.gov/example",
                    "category": "test",
                    "trust": "official",
                    "auto_sync": False
                }]
            }),
            encoding="utf-8",
        )
        vault = CyberKnowledgeVault(
            db_path=root / "knowledge.sqlite3",
            sources_path=sources,
            state_path=root / "state.json",
        )
        return tmp, vault

    def test_seed_is_searchable(self):
        tmp, vault = self.make()
        try:
            self.assertGreaterEqual(vault.stats()["documents"], 12)
            result = vault.search("RDP acesso remoto")
            self.assertTrue(result["ok"])
            self.assertGreaterEqual(result["count"], 1)
        finally:
            tmp.cleanup()

    def test_upsert_preserves_provenance(self):
        tmp, vault = self.make()
        try:
            vault._upsert(
                source_id="test",
                external_id="T1",
                title="Example",
                body="Firewall network security example",
                url="https://www.nist.gov/example",
                category="test",
                publisher="Official Test",
                trust="official",
                provenance="official-web-import",
            )
            rows = vault.search("Firewall")["results"]
            row = next(x for x in rows if x["title"] == "Example")
            self.assertEqual(row["publisher"], "Official Test")
            self.assertEqual(row["provenance"], "official-web-import")
            self.assertEqual(row["trust"], "official")
        finally:
            tmp.cleanup()

    def test_arbitrary_web_hosts_are_denied(self):
        tmp, vault = self.make()
        try:
            with self.assertRaises(ValueError):
                vault._validate_url("https://evil.example/data")
            vault._validate_url("https://www.nist.gov/data")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
