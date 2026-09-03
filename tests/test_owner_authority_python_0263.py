import unittest
from pathlib import Path

from jarvis_core.services.autonomy import parse_direct_external_learning_order


class OwnerAuthorityPython0263Tests(unittest.TestCase):
    def test_exact_owner_python_sentence_is_intercepted(self):
        result = parse_direct_external_learning_order(
            "Jarvis tens a minha autorização para acederes a internet e aprendas a programar em python"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "direct_external_learning")
        self.assertEqual(result["topic"], "programar em python")
        self.assertTrue(result["direct_user_authority"])
        self.assertEqual(result["scope"], "single_research_session")

    def test_infinitive_complement_learning_form_is_supported(self):
        result = parse_direct_external_learning_order(
            "Tens a minha autorização para usar a internet e aprender a programar em Python"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["topic"].lower(), "programar em python")

    def test_terminal_wake_is_resolved_before_authority_parser(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        loop = text.index("while True:")
        wake = text.index('source="explicit_terminal_wake"', loop)
        parser = text.index("parse_direct_external_learning_order(", loop)
        generic = text.rindex("process_request(text)")
        self.assertLess(wake, parser)
        self.assertLess(parser, generic)

    def test_direct_learning_action_stays_bounded_while_explicit_web_access_can_persist(self):
        result = parse_direct_external_learning_order(
            "Jarvis tens a minha autorização para acederes a internet e aprendas a programar em python"
        )
        self.assertEqual(result["scope"], "single_research_session")
        self.assertTrue(result["standing_public_web_read_only_grant"])


if __name__ == "__main__":
    unittest.main()
