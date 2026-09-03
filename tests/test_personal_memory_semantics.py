import unittest
from pathlib import Path


class PersonalMemorySemanticsTests(unittest.TestCase):
    def test_system_prompt_allows_explicit_ordinary_personal_facts(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("family/relationship facts", text)
        self.assertIn("Do not invent a blanket privacy-policy refusal", text)
        self.assertIn("Credential/recovery secrets", text)

    def test_fast_router_contains_explicit_memory_parser(self):
        text = Path("jarvis_core/core/fast_router.py").read_text(encoding="utf-8")
        self.assertIn("_extract_explicit_memory_fact", text)
        self.assertIn("remember_user_fact", text)


if __name__ == "__main__":
    unittest.main()
