import json
import unittest
from pathlib import Path


class CyberSourcesContractTests(unittest.TestCase):
    def test_official_sources_present(self):
        data = json.loads(
            Path("defaults/cyber_sources.json").read_text(encoding="utf-8")
        )
        ids = {row["id"] for row in data["sources"]}
        for expected in (
            "nist_csf_2",
            "nist_sp800_53",
            "owasp_top10_2025",
            "microsoft_windows_security",
            "cisa_kev",
            "mitre_attack_enterprise",
        ):
            self.assertIn(expected, ids)

    def test_mitre_is_bulk_and_manual(self):
        data = json.loads(
            Path("defaults/cyber_sources.json").read_text(encoding="utf-8")
        )
        row = next(
            x for x in data["sources"]
            if x["id"] == "mitre_attack_enterprise"
        )
        self.assertTrue(row["bulk"])
        self.assertFalse(row["auto_sync"])


if __name__ == "__main__":
    unittest.main()
