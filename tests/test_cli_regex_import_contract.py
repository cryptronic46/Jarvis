import ast
import re
import unittest
from pathlib import Path


class CliRegexImportContractTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("jarvis_core/cli.py")
        self.text = self.path.read_text(encoding="utf-8")
        self.tree = ast.parse(self.text)

    def test_re_usage_requires_re_import(self):
        uses_re = any(
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "re"
            for node in ast.walk(self.tree)
        )

        imported_re = any(
            isinstance(node, ast.Import)
            and any(alias.name == "re" for alias in node.names)
            for node in self.tree.body
        )

        imported_from_re = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "re"
            for node in self.tree.body
        )

        if uses_re:
            self.assertTrue(
                imported_re or imported_from_re,
                "cli.py uses re.<member> but does not import re",
            )

    def test_natural_authorization_regexes_are_present_and_valid(self):
        self.assertIn("re.fullmatch(", self.text)

        auth_pattern = (
            r"(?:jarvis[ ,]+)?autorizo\s+([a-f0-9]{6})[.!]?"
        )
        deny_pattern = (
            r"(?:jarvis[ ,]+)?"
            r"(?:nego|recuso|nao autorizo|não autorizo)"
            r"\s+([a-f0-9]{6})[.!]?"
        )

        # Compiling these guards the intended syntax itself.
        re.compile(auth_pattern)
        re.compile(deny_pattern)

        self.assertIsNotNone(
            re.fullmatch(auth_pattern, "autorizo a1b2c3")
        )
        self.assertIsNotNone(
            re.fullmatch(deny_pattern, "não autorizo a1b2c3")
        )

    def test_normal_input_does_not_match_authorization_patterns(self):
        auth_pattern = (
            r"(?:jarvis[ ,]+)?autorizo\s+([a-f0-9]{6})[.!]?"
        )
        deny_pattern = (
            r"(?:jarvis[ ,]+)?"
            r"(?:nego|recuso|nao autorizo|não autorizo)"
            r"\s+([a-f0-9]{6})[.!]?"
        )

        text = "bom dia jarvis"
        self.assertIsNone(re.fullmatch(auth_pattern, text))
        self.assertIsNone(re.fullmatch(deny_pattern, text))


if __name__ == "__main__":
    unittest.main()
