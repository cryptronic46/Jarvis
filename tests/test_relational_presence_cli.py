import unittest
from pathlib import Path


class RelationalPresenceRuntimeIntegrationTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(cls):
        cls.cli_source = Path(
            "jarvis_core/cli.py"
        ).read_text(
            encoding="utf-8"
        )

        cls.runtime_source = Path(
            "jarvis_core/runtime.py"
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
            self.cli_source,
        )

        self.assertEqual(
            self.cli_source.count(
                (
                    "relational_presence_store = "
                    "relational_presence()"
                )
            ),
            1,
        )

        self.assertNotIn(
            "RelationalPresenceStore()",
            self.cli_source,
        )


    def test_owner_input_is_observed_after_synthetic_self(
        self,
    ):
        process_start = self.runtime_source.index(
            "    def process_request("
        )

        method = self.runtime_source[
            process_start:
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
            self.runtime_source.count(
                marker
            ),
            2,
        )

        self.assertIn(
            (
                "relational_presence_store."
                "observe_exchange(\n"
                "                    user_text,\n"
                "                    answer,"
            ),
            self.runtime_source,
        )

        self.assertIn(
            (
                "relational_presence_store."
                "observe_exchange(\n"
                "                user_text,\n"
                "                hybrid.text,"
            ),
            self.runtime_source,
        )


if __name__ == "__main__":
    unittest.main()
