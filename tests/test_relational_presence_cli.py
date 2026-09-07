import unittest
from pathlib import Path


class RelationalPresenceCLIIntegrationTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )


    def test_store_is_instantiated_once(
        self,
    ):
        self.assertIn(
            (
                "from jarvis_core.services."
                "relational_presence import "
                "relational_presence"
            ),
            self.source,
        )

        self.assertEqual(
            self.source.count(
                (
                    "relational_presence_store = "
                    "relational_presence()"
                )
            ),
            1,
        )

        self.assertNotIn(
            "RelationalPresenceStore()",
            self.source,
        )


    def test_owner_input_is_observed_after_synthetic_self(
        self,
    ):
        process_start = self.source.index(
            "    def process_request("
        )

        process_end = self.source.index(
            "\n    def ",
            process_start + 8,
        )

        method = self.source[
            process_start:process_end
        ]

        synthetic = method.index(
            (
                "self_engine."
                "observe_owner_input("
            )
        )

        relational = method.index(
            (
                "relational_presence_store."
                "observe_owner_input("
            )
        )

        request_dispatch = method.index(
            (
                "answer, route, hybrid = "
                "route_runtime_request("
            )
        )

        self.assertLess(
            synthetic,
            relational,
        )

        self.assertLess(
            relational,
            request_dispatch,
        )


    def test_fast_and_hybrid_exchanges_are_both_observed(
        self,
    ):
        marker = (
            "relational_presence_store."
            "observe_exchange("
        )

        self.assertEqual(
            self.source.count(marker),
            2,
        )

        self.assertIn(
            (
                "relational_presence_store."
                "observe_exchange(\n"
                "                    user_text,\n"
                "                    answer,"
            ),
            self.source,
        )

        self.assertIn(
            (
                "relational_presence_store."
                "observe_exchange(\n"
                "                user_text,\n"
                "                hybrid.text,"
            ),
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
