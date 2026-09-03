import ast
import inspect
import unittest
from pathlib import Path

from jarvis_core.services.wakeword import WakeWordConfig


class WakeConstructor081ContractTests(unittest.TestCase):
    def test_cli_passes_only_valid_wake_config_keywords(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        keywords = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "WakeWordConfig"
            ):
                keywords = {
                    kw.arg
                    for kw in node.keywords
                    if kw.arg is not None
                }
                break

        self.assertIsNotNone(keywords)

        valid = set(inspect.signature(WakeWordConfig).parameters)
        self.assertEqual(keywords - valid, set())

        obsolete = {
            "silence_seconds",
            "max_phrase_seconds",
            "min_candidate_seconds",
            "min_peak_ratio",
            "rejected_cooldown_seconds",
            "match_threshold",
        }
        self.assertTrue(keywords.isdisjoint(obsolete))


if __name__ == "__main__":
    unittest.main()
