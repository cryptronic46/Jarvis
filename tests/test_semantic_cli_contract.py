from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "jarvis_core" / "cli.py"


class SemanticCliContractTests(unittest.TestCase):
    def test_cli_resolves_semantics_once(self):
        tree = ast.parse(
            CLI.read_text(encoding="utf-8")
        )

        calls = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "resolve_semantic_request"
            ):
                calls.append(node)

        self.assertEqual(
            len(calls),
            1,
            "CLI must resolve semantic intent exactly once",
        )

        call = calls[0]

        self.assertEqual(len(call.args), 1)
        self.assertIsInstance(call.args[0], ast.Name)
        self.assertEqual(call.args[0].id, "user_text")

    def test_cli_passes_resolved_request_to_hybrid_brain(self):
        tree = ast.parse(
            CLI.read_text(encoding="utf-8")
        )

        matching = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if not isinstance(node.func, ast.Attribute):
                continue

            if node.func.attr != "ask":
                continue

            if not isinstance(node.func.value, ast.Name):
                continue

            if node.func.value.id != "hybrid_brain":
                continue

            matching.append(node)

        self.assertEqual(len(matching), 1)

        keywords = {
            keyword.arg: keyword.value
            for keyword in matching[0].keywords
            if keyword.arg is not None
        }

        self.assertIn("request", keywords)
        self.assertIsInstance(
            keywords["request"],
            ast.Name,
        )
        self.assertEqual(
            keywords["request"].id,
            "structured_request",
        )


if __name__ == "__main__":
    unittest.main()
