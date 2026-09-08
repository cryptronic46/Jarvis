import unittest
from pathlib import Path


class PersonalMemorySemanticsTests(unittest.TestCase):
    def test_system_prompt_allows_explicit_ordinary_personal_facts(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("family/relationship facts", text)
        self.assertIn("Do not invent a blanket privacy-policy refusal", text)
        self.assertIn("Credential/recovery secrets", text)

    def test_memory_write_semantics_are_owned_by_semantic_resolver(self):
        fast_text = Path(
            "jarvis_core/core/fast_router.py"
        ).read_text(
            encoding="utf-8"
        )

        semantic_text = Path(
            "jarvis_core/services/semantic_intent.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "_extract_explicit_memory_fact",
            fast_text,
        )

        self.assertNotIn(
            "_clean_memory_fact",
            fast_text,
        )

        self.assertNotIn(
            "remember_prefixes",
            fast_text,
        )

        self.assertIn(
            'action="remember_owner_fact"',
            semantic_text,
        )

        self.assertIn(
            'preferred_tool="remember_user_fact"',
            semantic_text,
        )

        self.assertIn(
            'if preferred_tool == "remember_user_fact":',
            fast_text,
        )


if __name__ == "__main__":
    unittest.main()
