import unittest
from pathlib import Path

from jarvis_core.skills.builtin.system_guardian import SystemGuardianService


class GuardianSeverityContractTests(unittest.TestCase):
    def test_severity_counts_are_explicit(self):
        counts = SystemGuardianService._severity_counts([
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "attention"},
            {"severity": "attention"},
        ])
        self.assertEqual(counts["critical"], 1)
        self.assertEqual(counts["high"], 1)
        self.assertEqual(counts["attention"], 2)
        self.assertEqual(counts["total"], 4)
        self.assertEqual(SystemGuardianService._highest_severity(counts), "critical")

    def test_guardian_event_publishes_severity_counts(self):
        text = Path("jarvis_core/skills/builtin/system_guardian.py").read_text(encoding="utf-8")
        self.assertIn("severity_counts=severity_counts", text)
        self.assertIn("highest_severity=self._highest_severity(severity_counts)", text)
        self.assertIn('"severity_counts": severity_counts', text)


if __name__ == "__main__":
    unittest.main()
