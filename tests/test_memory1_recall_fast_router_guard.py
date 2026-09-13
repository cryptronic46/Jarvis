from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jarvis_core.cli as cli_module
from jarvis_core.core.fast_router import (
    FastCommandRouter,
)


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append(
            (name, payload)
        )


class _FastWouldHandle:
    def __init__(self):
        self.calls = []

    def dispatch(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            {
                "text": text,
                "request": request,
            }
        )

        return SimpleNamespace(
            handled=True,
            route="DANGEROUS_FAST",
            response="fast response",
        )


class _Hybrid:
    def __init__(self):
        self.calls = []

    def ask(
        self,
        text,
        *,
        request=None,
        memory_grounding_context=None,
    ):
        self.calls.append(
            {
                "text": text,
                "request": request,
                "memory_grounding_context":
                    memory_grounding_context,
            }
        )

        return SimpleNamespace(
            text="grounded hybrid response",
            route="LOCAL",
        )


def _request():
    return SimpleNamespace(
        intent="OPERATIONAL_ACTION",
        domain="general",
        subject="owner",
        action="answer",
        requires_tool=False,
        preferred_tool=None,
        epistemic_learning_eligible=False,
        confidence=1.0,
    )


def _route(
    *,
    grounding="",
    requires_memory_aware=False,
):
    events = _Events()
    fast = _FastWouldHandle()
    hybrid = _Hybrid()
    request = _request()

    with (
        patch.object(
            cli_module,
            "resolve_semantic_request",
            return_value=request,
        ),
        patch.object(
            cli_module,
            "_MODEL_OWNED_SEMANTIC_INTENTS",
            frozenset(),
        ),
    ):
        answer, route, result = (
            cli_module.route_runtime_request(
                "pedido",
                source="terminal",
                semantic_context_inputs=(
                    lambda: (
                        [],
                        {},
                    )
                ),
                events=events,
                fast_router=fast,
                hybrid_brain=hybrid,
                memory_grounding_context=grounding,
                requires_memory_aware_response=(
                    requires_memory_aware
                ),
            )
        )

    return (
        answer,
        route,
        result,
        events,
        fast,
        hybrid,
    )


class Memory1RecallFastRouterGuardTests(
    unittest.TestCase
):
    def test_grounding_makes_fast_router_ineligible(
        self,
    ):
        (
            answer,
            route,
            result,
            _events,
            fast,
            hybrid,
        ) = _route(
            grounding=(
                "JARVIS_MEMORY_GROUNDING_EVIDENCE\n"
                "memory_scope=memory1_canonical_recall\n"
                "[NO ADMISSIBLE MEMORY EVIDENCE]"
            ),
        )

        self.assertEqual(
            fast.calls,
            [],
        )

        self.assertEqual(
            len(hybrid.calls),
            1,
        )

        self.assertEqual(
            answer,
            "grounded hybrid response",
        )

        self.assertEqual(
            route,
            "LOCAL",
        )

        self.assertIs(
            result,
            result,
        )

        self.assertIn(
            "memory1_canonical_recall",
            hybrid.calls[0][
                "memory_grounding_context"
            ],
        )

    def test_explicit_memory_aware_requirement_blocks_fast_without_grounding(
        self,
    ):
        (
            _answer,
            _route_name,
            _result,
            events,
            fast,
            hybrid,
        ) = _route(
            requires_memory_aware=True,
        )

        self.assertEqual(
            fast.calls,
            [],
        )

        self.assertEqual(
            len(hybrid.calls),
            1,
        )

        bypass = [
            payload
            for name, payload
            in events.rows
            if name
            == "FAST_ROUTER_BYPASSED"
        ]

        self.assertEqual(
            len(bypass),
            1,
        )

        self.assertEqual(
            bypass[0]["reason"],
            "memory_aware_response_required",
        )

    def test_fast_router_entrypoint_refuses_memory_aware_direct_call(
        self,
    ):
        router = object.__new__(
            FastCommandRouter
        )

        result = router.dispatch(
            "qualquer texto",
            requires_memory_aware_response=True,
        )

        self.assertFalse(
            result.handled
        )

    def test_fast_router_default_contract_remains_backward_compatible(
        self,
    ):
        signature = inspect.signature(
            FastCommandRouter.dispatch
        )

        parameter = signature.parameters[
            "requires_memory_aware_response"
        ]

        self.assertFalse(
            parameter.default
        )

        self.assertEqual(
            parameter.kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

    def test_process_request_is_fail_closed_until_interpretation_succeeds(
        self,
    ):
        source = inspect.getsource(
            cli_module.main
        )

        process = source[
            source.index(
                "def process_request"
            ):
        ]

        default_index = process.index(
            "memory1_requires_memory_aware_response = True"
        )
        interpret_index = process.index(
            "memory1_adapter.interpret("
        )
        resolved_index = process.index(
            "memory1_requires_memory_aware_response = ("
        )
        route_index = process.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        self.assertLess(default_index, interpret_index)
        self.assertLess(interpret_index, resolved_index)
        self.assertLess(resolved_index, route_index)

        resolved_block = process[resolved_index:route_index]
        self.assertIn("MemoryOperation.RECALL", resolved_block)
        self.assertIn("MemoryOperation.REMEMBER", resolved_block)

    def test_process_request_transports_memory_aware_requirement_to_router(
        self,
    ):
        source = inspect.getsource(
            cli_module.main
        )

        process = source[
            source.index(
                "def process_request"
            ):
        ]

        route_index = process.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )
        route_block = process[route_index:route_index + 1400]

        self.assertIn(
            "requires_memory_aware_response=",
            route_block,
        )
        self.assertIn(
            "memory1_requires_memory_aware_response",
            route_block,
        )

if __name__ == "__main__":
    unittest.main()
