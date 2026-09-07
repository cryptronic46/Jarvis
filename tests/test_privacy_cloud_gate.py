import unittest
from pathlib import Path


class ExternalRuntimeAuthorityContractTests(unittest.TestCase):
    def test_cloud_has_no_privacy_dependency(self):
        text = Path(
            "jarvis_core/core/cloud_brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "privacy_state",
            text,
        )
        self.assertNotIn(
            "jarvis_core.services.privacy",
            text,
        )
        self.assertIn(
            "external_ai_enabled",
            text,
        )

    def test_local_research_has_no_privacy_dependency(self):
        text = Path(
            "jarvis_core/services/local_research.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "privacy_state",
            text,
        )
        self.assertNotIn(
            "jarvis_core.services.privacy",
            text,
        )
        self.assertNotIn(
            "PRIVACY_OR_RESEARCH_DISABLED",
            text,
        )
        self.assertIn(
            "RESEARCH_DISABLED",
            text,
        )

    def test_external_learning_uses_capability_error(self):
        text = Path(
            "jarvis_core/services/external_learning.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "PRIVACY_OR_RESEARCH_DISABLED",
            text,
        )
        self.assertIn(
            "RESEARCH_DISABLED",
            text,
        )


if __name__ == "__main__":
    unittest.main()
