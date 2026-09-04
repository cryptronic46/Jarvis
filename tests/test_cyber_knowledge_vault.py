import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.services.cyber_knowledge import (
    CyberKnowledgeVault,
    CyberSourceError,
    DownloadedSource,
)


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
            with self.assertRaises(CyberSourceError):
                vault._validate_url("https://evil.example/data")
            vault._validate_url("https://www.nist.gov/data")
        finally:
            tmp.cleanup()

    def test_cisa_feed_routes_by_json_content_type_and_real_schema(self):
        tmp, vault = self.make()
        try:
            source = {
                "id": "cisa_kev",
                "name": "CISA Known Exploited Vulnerabilities",
                "publisher": "CISA",
                "kind": "cisa_kev",
                "url": (
                    "https://www.cisa.gov/sites/default/files/feeds/"
                    "known_exploited_vulnerabilities.json"
                ),
                "category": "vulnerability-intelligence",
                "trust": "official",
            }
            vault.sources = lambda: [source]
            payload = {
                "title": "CISA Catalog of Known Exploited Vulnerabilities",
                "catalogVersion": "2026.09.04",
                "dateReleased": "2026-09-04T10:00:00.0000Z",
                "count": 1,
                "vulnerabilities": [{
                    "cveID": "CVE-2099-0010",
                    "vendorProject": "Example Vendor",
                    "product": "Example Product",
                    "vulnerabilityName": "Example vulnerability",
                    "dateAdded": "2099-01-01",
                    "shortDescription": "Known exploitation.",
                    "requiredAction": "Apply vendor mitigations.",
                    "dueDate": "2099-01-22",
                    "knownRansomwareCampaignUse": "Known",
                    "forensicTriage": "Review process creation events.",
                    "notes": "https://www.cisa.gov/known-exploited-vulnerabilities",
                    "cwes": ["CWE-78"],
                }],
            }
            raw = json.dumps(payload).encode("utf-8")
            vault._download = lambda unused: DownloadedSource(
                raw=raw,
                content_type="application/json",
                final_url=source["url"],
            )

            result = vault.sync_source("cisa_kev")

            self.assertTrue(result["ok"])
            self.assertEqual(result["documents"], 1)
            self.assertEqual(result["declared_count"], 1)
            self.assertEqual(result["content_type"], "application/json")
            found = vault.search("Review process creation events")
            self.assertEqual(found["results"][0]["external_id"], "CVE-2099-0010")
        finally:
            tmp.cleanup()

    def test_cisa_invalid_json_returns_explicit_reason_code(self):
        tmp, vault = self.make()
        try:
            source = {
                "id": "cisa_kev",
                "name": "CISA KEV",
                "kind": "cisa_kev",
                "url": "https://www.cisa.gov/feed.json",
            }
            vault.sources = lambda: [source]
            vault._download = lambda unused: DownloadedSource(
                raw=b"not-json",
                content_type="application/json; charset=utf-8",
                final_url=source["url"],
            )

            result = vault.sync_source("cisa_kev")

            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "CYBER_SOURCE_ERROR")
            self.assertEqual(result["reason_code"], "CYBER_SOURCE_JSON_INVALID")
            self.assertNotEqual(result["error"], "ValueError")
        finally:
            tmp.cleanup()

    def test_download_rejects_declared_content_over_safe_limit(self):
        tmp, vault = self.make()
        try:
            class OversizedResponse:
                headers = {
                    "Content-Length": "64001",
                    "Content-Type": "application/json",
                }

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

            source = {
                "url": "https://www.cisa.gov/feed.json",
                "max_bytes": 64_000,
            }
            with patch(
                "jarvis_core.services.cyber_knowledge.urlopen",
                return_value=OversizedResponse(),
            ):
                with self.assertRaises(CyberSourceError) as caught:
                    vault._download(source)
            self.assertEqual(caught.exception.reason_code, "CYBER_SOURCE_TOO_LARGE")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
