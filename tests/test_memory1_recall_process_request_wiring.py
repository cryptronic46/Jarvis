from __future__ import annotations

import inspect
import unittest

import jarvis_core.cli as cli_module

from jarvis_core.memory.recall_grounding import (
    MEMORY1_RECALL_SCOPE,
    build_memory1_recall_fail_closed_grounding,
    build_memory1_recall_fail_closed_status,
)


def process_source():
    source = inspect.getsource(
        cli_module.main
    )

    return source[
        source.index(
            "def process_request"
        ):
    ]


class Memory1RecallProcessRequestWiringTests(
    unittest.TestCase
):
    def test_fail_closed_grounding_is_hard_empty_scope(
        self,
    ):
        grounding = (
            build_memory1_recall_fail_closed_grounding()
        )

        self.assertEqual(
            grounding.memory_scope,
            MEMORY1_RECALL_SCOPE,
        )

        self.assertEqual(
            grounding.evidence_count,
            0,
        )

        self.assertEqual(
            grounding.evidence_status,
            "empty",
        )

        self.assertIn(
            "JARVIS_MEMORY_GROUNDING_EVIDENCE",
            grounding.context,
        )

        self.assertIn(
            "memory_scope=memory1_canonical_recall",
            grounding.context,
        )

        self.assertIn(
            "[NO ADMISSIBLE MEMORY EVIDENCE]",
            grounding.context,
        )

    def test_process_interprets_owner_turn_exactly_once(
        self,
    ):
        source = process_source()

        self.assertEqual(
            source.count(
                "memory1_adapter.interpret("
            ),
            1,
        )

    def test_recall_pipeline_executes_before_route(
        self,
    ):
        source = process_source()

        pre = source.index(
            "# MEMORY1_RUNTIME_PRE_ROUTE_V1"
        )

        recall_read = source.index(
            "execute_memory_recall_plan("
        )

        grounding = source.index(
            "build_memory1_recall_grounding("
        )

        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        self.assertLess(
            pre,
            recall_read,
        )

        self.assertLess(
            recall_read,
            grounding,
        )

        self.assertLess(
            grounding,
            route,
        )

    def test_route_receives_request_scoped_memory1_grounding(
        self,
    ):
        source = process_source()

        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        route_block = source[
            route:
            route + 1200
        ]

        self.assertIn(
            "memory_grounding_context",
            route_block,
        )

        self.assertIn(
            "memory1_grounding_context",
            route_block,
        )

    def test_recognized_recall_failure_becomes_hard_empty_scope(
        self,
    ):
        source = process_source()

        pre = source.index(
            "# MEMORY1_RUNTIME_PRE_ROUTE_V1"
        )

        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        pre_route = source[
            pre:
            route
        ]

        self.assertIn(
            "build_memory1_recall_fail_closed_grounding",
            pre_route,
        )

        self.assertIn(
            "MEMORY1_RUNTIME_RECALL_FAIL_CLOSED",
            pre_route,
        )

        self.assertIn(
            "build_memory1_recall_fail_closed_status",
            pre_route,
        )

        self.assertIn(
            "build_memory1_turn_status_context",
            pre_route,
        )

    def test_recall_status_is_built_before_route(
        self,
    ):
        source = process_source()
        status = source.index("build_memory1_recall_status(")
        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )
        self.assertLess(status, route)

    def test_interpretation_failures_have_explicit_hard_boundary(
        self,
    ):
        source = process_source()
        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )
        pre_route = source[:route]
        self.assertIn("MemoryInterpretationStatus.MODEL_FAILURE", pre_route)
        self.assertIn("MemoryInterpretationStatus.SCHEMA_INVALID", pre_route)
        self.assertIn(
            "build_memory1_interpretation_fail_closed_context",
            pre_route,
        )

    def test_remember_write_executes_before_response_route(
        self,
    ):
        source = process_source()

        pre = source.index(
            "# MEMORY1_RUNTIME_PRE_ROUTE_V1"
        )
        write = source.index(
            "execute_memory_resolution_plan("
        )
        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        self.assertLess(pre, write)
        self.assertLess(write, route)
        self.assertNotIn(
            "# MEMORY1_RUNTIME_REMEMBER_WRITE_V1",
            source,
        )

    def test_recall_branch_has_no_canonical_write_executor(
        self,
    ):
        source = process_source()

        recall = source.index(
            "is MemoryOperation.RECALL"
        )
        remember = source.index(
            "is MemoryOperation.REMEMBER",
            recall,
        )
        recall_branch = source[recall:remember]

        self.assertNotIn(
            "execute_memory_resolution_plan(",
            recall_branch,
        )
        self.assertIn(
            "execute_memory_recall_plan(",
            recall_branch,
        )

        route = source.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )
        self.assertLess(remember, route)

if __name__ == "__main__":
    unittest.main()
