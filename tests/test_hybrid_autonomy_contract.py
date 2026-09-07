import unittest
from pathlib import Path


class HybridAutonomyContractTests(unittest.TestCase):
    def test_autonomous_web_path_is_gated(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn("def _autonomy_gate", text)
        self.assertIn('capability="web_research"', text)
        self.assertIn('source="local_research_router"', text)

    def test_forced_local_is_local_and_learning_first(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn('"local", "forced_local"', text)
        self.assertIn("def _learning_gap_offer", text)
        self.assertIn('action="external_learning_resume_query"', text)

    def test_external_ai_is_structurally_blocked(self):
        text = Path(
            "jarvis_core/core/hybrid_brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '"external_ai_blocked"',
            text,
        )
        self.assertIn(
            '"external_ai_hard_block"',
            text,
        )
        self.assertNotIn(
            'capability="cloud_reasoning"',
            text,
        )

    def test_web_authority_is_fail_closed(self):
        text = Path(
            "jarvis_core/core/hybrid_brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'route="AUTH/BLOCKED"',
            text,
        )
        self.assertIn(
            'reason="owner_authority_unavailable"',
            text,
        )
        self.assertIn(
            'reason="owner_authority_error"',
            text,
        )

    def test_explicit_owner_web_is_audited(self):
        text = Path(
            "jarvis_core/core/hybrid_brain.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "record_direct_authorization(",
            text,
        )
        self.assertIn(
            'capability="web_research"',
            text,
        )
        self.assertIn(
            "source_text=user_text",
            text,
        )


if __name__ == "__main__":
    unittest.main()
