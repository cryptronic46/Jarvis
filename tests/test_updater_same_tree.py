import unittest
from pathlib import Path


class UpdaterSameTreeTests(unittest.TestCase):
    def test_same_tree_is_supported(self):
        text = Path("update_core.ps1").read_text(encoding="utf-8")
        self.assertIn("$SameTree", text)
        self.assertIn("Nao vou copiar ficheiros sobre eles proprios", text)
        self.assertIn("if ($SameTree)", text)


if __name__ == "__main__":
    unittest.main()
