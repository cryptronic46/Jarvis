import unittest

from jarvis_core.services.windows_block_audit import (
    format_startup_preflight,
)


class WindowsBlockAuditSeverityTests(unittest.TestCase):
    def base(self):
        return {
            "ok": True,
            "supported": True,
            "scanned_files": 100,
            "elapsed_ms": 10,
            "motw_counts": {
                "total": 0,
                "native": 0,
                "python": 0,
                "script": 0,
            },
            "confirmed_block_events": [],
            "active_block_events": [],
            "resolved_historical_block_events": [],
            "mitigated_block_events": [],
            "integrity_events": [],
        }

    def test_non_native_motw_is_info_not_block(self):
        report = self.base()
        report["motw_counts"].update(
            total=10,
            python=8,
            script=2,
        )
        text = format_startup_preflight(report)
        self.assertIn(
            "Windows Block Audit: INFO",
            text,
        )
        self.assertIn(
            "bloqueios ativos=0",
            text,
        )

    def test_native_motw_is_review(self):
        report = self.base()
        report["motw_counts"].update(
            total=2,
            native=2,
        )
        text = format_startup_preflight(report)
        self.assertIn(
            "Windows Block Audit: REVER",
            text,
        )

    def test_confirmed_event_is_block(self):
        report = self.base()
        report["confirmed_block_events"] = [{"id": 3077}]
        report["active_block_events"] = [{"id": 3077}]
        text = format_startup_preflight(report)
        self.assertIn(
            "Windows Block Audit: BLOQUEIO",
            text,
        )

    def test_resolved_historical_event_is_review_not_block(self):
        report = self.base()
        report["confirmed_block_events"] = [{"id": 3077, "resolved_historical": True}]
        report["resolved_historical_block_events"] = list(report["confirmed_block_events"])
        text = format_startup_preflight(report)
        self.assertIn("Windows Block Audit: REVER", text)
        self.assertIn("bloqueios ativos=0", text)
        self.assertIn("resolvidos=1", text)


if __name__ == "__main__":
    unittest.main()
