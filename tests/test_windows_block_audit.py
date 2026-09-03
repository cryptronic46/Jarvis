import unittest
from pathlib import Path
from jarvis_core.services.windows_block_audit import (
    _candidate_allowed, _annotate_current_file_state, classify_windows_event, parse_zone_identifier,
)

class WindowsBlockAuditTests(unittest.TestCase):
    def test_zone_identifier_internet_is_current_motw(self):
        data=parse_zone_identifier("[ZoneTransfer]\nZoneId=3\nHostUrl=https://example.test/file.zip\n")
        self.assertEqual(data["zone_id"],3)
        self.assertTrue(data["currently_marked_from_internet"])

    def test_zone_identifier_trusted_is_not_current_motw(self):
        data=parse_zone_identifier("[ZoneTransfer]\nZoneId=2\n")
        self.assertFalse(data["currently_marked_from_internet"])

    def test_confirmed_block_ids(self):
        for event_id in (3077,8004,8007):
            self.assertEqual(classify_windows_event(event_id)[0],"confirmed_block")

    def test_integrity_ids(self):
        for event_id in (3004,3033):
            self.assertEqual(classify_windows_event(event_id)[0],"integrity_issue")

    def test_venv_python_skipped_native_scanned(self):
        root=Path(r"C:\JARVIS")
        self.assertFalse(_candidate_allowed(root/".venv/Lib/site-packages/pkg/module.py",root))
        self.assertTrue(_candidate_allowed(root/".venv/Lib/site-packages/pkg/native.dll",root))
        self.assertTrue(_candidate_allowed(root/".venv/Lib/site-packages/pkg/native.pyd",root))

    def test_missing_blocked_artifact_is_historical_not_active(self):
        row = _annotate_current_file_state({
            "classification": "confirmed_block",
            "mitigated": False,
            "paths": [str(Path("definitely_missing") / "blocked_native.pyd")],
        })
        self.assertTrue(row["resolved_historical"])
        self.assertFalse(row["current_file_present"])

    def test_existing_blocked_artifact_remains_actionable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blocked_native.pyd"
            path.write_bytes(b"x")
            row = _annotate_current_file_state({
                "classification": "confirmed_block",
                "mitigated": False,
                "paths": [str(path)],
            })
            self.assertFalse(row["resolved_historical"])
            self.assertTrue(row["current_file_present"])

if __name__=="__main__":
    unittest.main()
