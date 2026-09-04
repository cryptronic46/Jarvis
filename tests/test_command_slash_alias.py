import ast
import unittest
from pathlib import Path


class CommandSlashAliasTests(unittest.TestCase):
    def test_backslash_command_normalization_is_present(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        found_startswith = False
        found_rewrite = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "startswith" and node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and arg.value == "\\":
                        found_startswith = True

            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "text":
                        # Source-level check is simpler for exact rewrite shape.
                        segment = ast.get_source_segment(source, node) or ""
                        if 'text = "/" + text[1:]' in segment:
                            found_rewrite = True

        self.assertTrue(found_startswith)
        self.assertTrue(found_rewrite)


    def test_qquit_typo_is_a_safe_quit_alias(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('"/qquit"', source)

if __name__ == "__main__":
    unittest.main()
