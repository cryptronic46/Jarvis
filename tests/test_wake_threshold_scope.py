from __future__ import annotations

import ast
import unittest
from pathlib import Path


class WakeThresholdScopeTests(unittest.TestCase):
    def test_command_threshold_is_local_to_capture_command(self):
        path = Path("jarvis_core/services/wakeword.py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        leaks: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name == "_capture_command":
                continue
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id == "command_threshold"
                ):
                    leaks.append((node.name, int(child.lineno)))

        self.assertEqual([], leaks, f"command_threshold leaked outside _capture_command: {leaks}")

    def test_pre_wake_gate_uses_calibrated_threshold(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        marker = "# This is the PRE-WAKE speech gate."
        self.assertIn(marker, text)
        block = text[text.index(marker): text.index(marker) + 500]
        self.assertIn("if value < threshold:", block)
        self.assertNotIn("if value < command_threshold:", block)


if __name__ == "__main__":
    unittest.main()
