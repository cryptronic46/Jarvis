import ast
import unittest
from pathlib import Path


class PerformanceWiringTests(unittest.TestCase):
    def test_brain_constructor_accepts_performance(self):
        path = Path("jarvis_core/core/brain.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))

        jarvis = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "JarvisBrain"
        )
        init = next(
            node
            for node in jarvis.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "__init__"
        )
        names = [arg.arg for arg in init.args.args]
        self.assertIn("performance", names)

    def test_cli_passes_governor_to_brain_and_hybrid(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(
            cli.count("performance=performance"),
            2,
        )
        self.assertIn("PerformanceGovernor(", cli)

    def test_brain_stores_governor(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("self.performance = performance", text)


if __name__ == "__main__":
    unittest.main()
