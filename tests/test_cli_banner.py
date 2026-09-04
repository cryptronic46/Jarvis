import unittest

from pathlib import Path


class CliBannerTests(unittest.TestCase):
    def test_banner_uses_plain_interface_safe_ascii(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        banner = source.split('BANNER_TEMPLATE = """', 1)[1].split('"""', 1)[0]
        self.assertIn("J A R V I S", banner)
        self.assertIn("CORE {version}", banner)
        self.assertNotIn("_", banner)
        self.assertNotIn("*", banner)
        self.assertNotIn("\\", banner)


if __name__ == "__main__":
    unittest.main()