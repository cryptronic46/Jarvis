import unittest
from pathlib import Path
from unittest.mock import patch

from jarvis_core.services.cybersecurity import (
    get_cyber_mentor_status,
    get_cyber_curriculum,
    get_cybersecurity_posture,
)


class CybersecurityMentorTests(unittest.TestCase):
    def test_role_is_explicit(self):
        status = get_cyber_mentor_status()
        self.assertEqual(
            status["role"],
            "cybersecurity_teacher_and_local_auditor",
        )
        self.assertEqual(status["curriculum_topics"], 12)
        self.assertIn(
            "evidence before conclusions",
            status["audit_principles"],
        )

    def test_curriculum_has_expected_topics(self):
        topics = " ".join(
            row["topic"]
            for row in get_cyber_curriculum()["curriculum"]
        ).lower()
        self.assertIn("tcp/ip", topics)
        self.assertIn("firewall", topics)
        self.assertIn("resposta a incidentes", topics)

    @patch("jarvis_core.services.cybersecurity.run_security_audit")
    def test_posture_turns_audit_into_teaching_observations(self, audit):
        audit.return_value = {
            "ok": True,
            "summary": {
                "level": "ok",
                "only_current_enabled_admin_detected": True,
                "active_remote_access_detected": False,
                "remote_interactive_session_count": 0,
                "smb_session_count": 0,
            },
            "windows_security": {
                "rdp_enabled": False,
                "firewall": [{"enabled": True}],
                "defender": {"real_time_protection_enabled": True},
            },
            "network": {
                "counts": {
                    "lan_devices_active": 3,
                    "public_established": 8,
                }
            },
        }
        result = get_cybersecurity_posture()
        topics = {row["topic"] for row in result["observations"]}
        for expected in (
            "least_privilege",
            "rdp",
            "firewall",
            "defender",
            "remote_access",
        ):
            self.assertIn(expected, topics)

    def test_system_prompt_defines_teacher_method(self):
        text = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn("cybersecurity teacher", text)
        self.assertIn("concept -> what it means on this system", text)
        self.assertIn(
            "Distinguish observed fact, inference and unknown",
            text,
        )


if __name__ == "__main__":
    unittest.main()
