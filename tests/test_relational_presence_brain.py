import unittest
from pathlib import Path


class RelationalPresenceBrainTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "jarvis_core/core/brain.py"
        ).read_text(
            encoding="utf-8"
        )

    def test_main_prompt_uses_relational_presence(
        self,
    ):
        self.assertIn(
            (
                "def "
                "_relational_presence_contract()"
            ),
            self.source,
        )

        self.assertIn(
            (
                "relational_contract = (\n"
                "            "
                "_relational_presence_contract()"
            ),
            self.source,
        )

        self.assertIn(
            (
                ") + relational_contract"
            ),
            self.source,
        )

    def test_legacy_style_contract_is_removed(
        self,
    ):
        self.assertNotIn(
            "_conversation_style_contract",
            self.source,
        )

    def test_main_prompt_no_longer_reads_flirt_settings(
        self,
    ):
        start = self.source.index(
            "        relational_contract = ("
        )

        end = self.source.index(
            "        teaching_contract =",
            start,
        )

        block = self.source[
            start:end
        ]

        self.assertNotIn(
            "companion_flirt_enabled",
            block,
        )

        self.assertNotIn(
            "companion_flirt_intensity",
            block,
        )


if __name__ == "__main__":
    unittest.main()
