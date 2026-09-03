import ast
import unittest
from pathlib import Path


class ToolSchemaNormalizationContractTests(unittest.TestCase):
    def test_unicodedata_normalize_uses_two_arguments(self):
        path = Path("jarvis_core/core/tool_registry.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))

        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "normalize"
                and isinstance(func.value, ast.Name)
                and func.value.id == "unicodedata"
            ):
                calls.append(node)

        self.assertTrue(calls, "unicodedata.normalize call not found")
        for call in calls:
            self.assertEqual(
                len(call.args),
                2,
                "unicodedata.normalize must receive exactly form and text",
            )


if __name__ == "__main__":
    unittest.main()
