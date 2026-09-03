import unittest
from pathlib import Path


class CyberToolsLocalOnlyTests(unittest.TestCase):
    def test_tools_registered(self):
        registry = Path(
            "jarvis_core/core/tool_registry.py"
        ).read_text(encoding="utf-8")
        for name in (
            "get_cyber_mentor_status",
            "get_cyber_curriculum",
            "get_cybersecurity_posture",
        ):
            self.assertIn(f'"{name}"', registry)

    def test_posture_not_cloud_allowlisted(self):
        cloud = Path(
            "jarvis_core/core/cloud_brain.py"
        ).read_text(encoding="utf-8")
        section = cloud[
            cloud.index("DEFAULT_ALLOWED_TOOLS = {"):
            cloud.index("}", cloud.index("DEFAULT_ALLOWED_TOOLS = {"))
        ]
        self.assertNotIn(
            '"get_cybersecurity_posture"',
            section,
        )


if __name__ == "__main__":
    unittest.main()
