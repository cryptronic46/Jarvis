import unittest
from pathlib import Path


class CloudAuthErrorContractTests(unittest.TestCase):
    def test_invalid_key_is_sanitized(self):
        text = Path(
            "jarvis_core/core/cloud_brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '"OPENAI_AUTH_INVALID"',
            text,
        )
        self.assertIn(
            "A OpenAI rejeitou a credencial configurada.",
            text,
        )
        self.assertIn(
            "self._client = None",
            text,
        )

    def test_cli_hard_blocks_cloud_commands(self):
        text = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn("External AI: HARD BLOCKED", text)
        self.assertIn('/cloud diagnose', text)
        self.assertIn('External AI: HARD BLOCKED', text)
        self.assertNotIn("cloud_brain.diagnose()", text)


if __name__ == "__main__":
    unittest.main()
