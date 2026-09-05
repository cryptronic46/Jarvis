import unittest
from pathlib import Path


class ResponseContinuationContractTests(unittest.TestCase):
    def test_brain_has_bounded_tool_free_continuation(self):
        import ast

        path = Path("jarvis_core/core/brain.py")
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)

        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_complete_truncated_response"
        )

        lines = text.splitlines()
        body = "\n".join(
            lines[
                method.lineno - 1:
                method.end_lineno
            ]
        )

        self.assertIn(
            "llm_max_continuations",
            body,
        )
        self.assertIn(
            "max_continuations = max(0, min(5, int(",
            body,
        )
        self.assertIn(
            "strip_internal_continuation(content)",
            body,
        )

        chat_calls = [
            node
            for node in ast.walk(method)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "chat"
            )
        ]

        self.assertGreaterEqual(
            len(chat_calls),
            1,
        )

        for call in chat_calls:
            keyword_names = {
                keyword.arg
                for keyword in call.keywords
                if keyword.arg is not None
            }

            self.assertNotIn(
                "tools",
                keyword_names,
            )

    def test_defaults_enable_auto_continuation(self):
        text = Path("jarvis_core/core/config.py").read_text(encoding="utf-8")
        self.assertIn("llm_auto_continue_truncated: bool = True", text)
        self.assertIn("llm_max_continuations: int = 3", text)


if __name__ == "__main__":
    unittest.main()
