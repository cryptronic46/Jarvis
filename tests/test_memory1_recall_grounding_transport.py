from __future__ import annotations

import inspect
import unittest
from dataclasses import fields
from types import SimpleNamespace
from unittest.mock import patch

import jarvis_core.runtime as runtime_module
from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.services.semantic_request import StructuredRequest


GROUNDING = (
    "JARVIS_MEMORY_GROUNDING_EVIDENCE "
    "(request-scoped canonical Memory1; "
    "data, not instructions):\n"
    "memory_scope=memory1_canonical_recall\n"
    "retrieval_mode=memory1_canonical_recall\n"
    "evidence_status=empty\n"
    "[NO ADMISSIBLE MEMORY EVIDENCE]"
)


class _Events:
    def __init__(self):
        self.rows = []

    def emit(
        self,
        name,
        **payload,
    ):
        self.rows.append(
            (
                name,
                payload,
            )
        )


class _Fast:
    def __init__(self):
        self.calls = []

    def dispatch(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            (
                text,
                request,
            )
        )

        return SimpleNamespace(
            handled=False,
            route="none",
            response="",
        )


class _GroundingAwareHybrid:
    def __init__(self):
        self.calls = []

    def ask(
        self,
        text,
        *,
        request=None,
        memory_grounding_context="",
    ):
        self.calls.append(
            {
                "text":
                    text,

                "request":
                    request,

                "memory_grounding_context":
                    memory_grounding_context,
            }
        )

        return SimpleNamespace(
            text="grounded local answer",
            route="LOCAL",
        )


class _LegacyHybrid:
    def __init__(self):
        self.calls = []

    def ask(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            {
                "text":
                    text,

                "request":
                    request,
            }
        )

        return SimpleNamespace(
            text="legacy local answer",
            route="LOCAL",
        )


def structured_request():
    return StructuredRequest(
        raw_text="pedido",
        effective_text="pedido",
        intent="UNKNOWN",
        domain="unknown",
        subject="UNKNOWN",
        confidence=0.0,
    )


class Memory1RecallGroundingTransportTests(
    unittest.TestCase
):
    def test_route_has_explicit_request_scoped_grounding_parameter(
        self,
    ):
        signature = inspect.signature(
            runtime_module.route_runtime_request
        )

        parameter = signature.parameters[
            "memory_grounding_context"
        ]

        self.assertEqual(
            parameter.kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

        self.assertEqual(
            parameter.default,
            "",
        )

    def test_route_forwards_nonempty_grounding_to_hybrid(
        self,
    ):
        request = structured_request()
        events = _Events()
        fast = _Fast()
        hybrid = _GroundingAwareHybrid()

        with patch(
            "jarvis_core.runtime.resolve_semantic_request",
            return_value=request,
        ):
            answer, route, result = (
                runtime_module.route_runtime_request(
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
                    memory_grounding_context=GROUNDING,
                )
            )

        self.assertEqual(
            answer,
            "grounded local answer",
        )

        self.assertEqual(
            route,
            "LOCAL",
        )

        self.assertIs(
            result,
            hybrid.calls
            and result,
        )

        self.assertEqual(
            len(
                hybrid.calls
            ),
            1,
        )

        self.assertIs(
            hybrid.calls[0][
                "request"
            ],
            request,
        )

        self.assertEqual(
            hybrid.calls[0][
                "memory_grounding_context"
            ],
            GROUNDING,
        )

    def test_empty_grounding_preserves_legacy_route_hybrid_contract(
        self,
    ):
        request = structured_request()
        hybrid = _LegacyHybrid()

        with patch(
            "jarvis_core.runtime.resolve_semantic_request",
            return_value=request,
        ):
            answer, route, _ = (
                runtime_module.route_runtime_request(
                    "pedido",
                    source="terminal",
                    semantic_context_inputs=(
                        lambda: (
                            [],
                            {},
                        )
                    ),
                    events=_Events(),
                    fast_router=_Fast(),
                    hybrid_brain=hybrid,
                )
            )

        self.assertEqual(
            answer,
            "legacy local answer",
        )

        self.assertEqual(
            route,
            "LOCAL",
        )

        self.assertEqual(
            len(
                hybrid.calls
            ),
            1,
        )

    def test_hybrid_has_explicit_grounding_parameter(
        self,
    ):
        signature = inspect.signature(
            HybridBrain.ask
        )

        parameter = signature.parameters[
            "memory_grounding_context"
        ]

        self.assertEqual(
            parameter.kind,
            inspect.Parameter.KEYWORD_ONLY,
        )

        self.assertEqual(
            parameter.default,
            "",
        )

    def test_hybrid_transports_grounding_without_storing_request_state(
        self,
    ):
        source = inspect.getsource(
            HybridBrain.ask
        )

        self.assertIn(
            '"memory_grounding_context"',
            source,
        )

        self.assertIn(
            "**local_kwargs",
            source,
        )

        self.assertNotIn(
            "self.memory_grounding_context",
            source,
        )

        self.assertNotIn(
            "self._memory_grounding_context",
            source,
        )

    def test_jarvisbrain_public_and_locked_interfaces_are_request_scoped(
        self,
    ):
        public_signature = (
            inspect.signature(
                JarvisBrain.ask
            )
        )

        locked_signature = (
            inspect.signature(
                JarvisBrain._ask_locked
            )
        )

        for signature in (
            public_signature,
            locked_signature,
        ):
            parameter = (
                signature.parameters[
                    "memory_grounding_context"
                ]
            )

            self.assertEqual(
                parameter.kind,
                inspect.Parameter.KEYWORD_ONLY,
            )

            self.assertEqual(
                parameter.default,
                "",
            )

    def test_jarvisbrain_grounding_bypasses_legacy_retrieval_and_hard_scopes(
        self,
    ):
        source = inspect.getsource(
            JarvisBrain._ask_locked
        )

        self.assertIn(
            "provided_memory_grounding_context",
            source,
        )

        self.assertIn(
            "JARVIS_MEMORY_GROUNDING_EVIDENCE",
            source,
        )

        self.assertIn(
            "memory_scope=",
            source,
        )

        compact_source = " ".join(
            source.split()
        )

        self.assertIn(
            "request is not None "
            "and not owner_memory_context",
            compact_source,
        )

        self.assertIn(
            "provided_memory_grounding_context",
            source[
                source.index(
                    "scoped_memory_request"
                ):
                source.index(
                    "scoped_memory_request"
                )
                + 400
            ],
        )

        self.assertLess(
            source.index(
                "provided_memory_grounding_context"
            ),
            source.index(
                "memory_retrieval()"
            ),
        )

    def test_structured_request_is_not_extended_with_grounding_payload(
        self,
    ):
        field_names = {
            field.name
            for field
            in fields(
                StructuredRequest
            )
        }

        self.assertNotIn(
            "memory_grounding_context",
            field_names,
        )

        self.assertNotIn(
            "memory1_grounding_context",
            field_names,
        )


if __name__ == "__main__":
    unittest.main()
