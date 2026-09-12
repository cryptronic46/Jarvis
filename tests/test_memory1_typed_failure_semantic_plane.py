from __future__ import annotations

import inspect
import unittest

import jarvis_core.cli as cli_module

from jarvis_core.memory.enums import (
    Cardinality,
    MemoryClass,
    ValueType,
)

from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.interpreter import (
    FactProposal,
    InterpreterContext,
    MemoryInterpretation,
    MemoryOperation,
    PropertyProposal,
)

from jarvis_core.memory.model_adapter import (
    MemoryModelContractError,
    TrustedTwoStageSemanticMemoryAdapter,
    _remember_structural_retry_prompt,
    trusted_memory_remember_extractor_system_prompt,
)

from jarvis_core.memory.proposal_validation import (
    validate_remember_property_control_plane_separation,
)

from jarvis_core.memory.runtime_result import (
    MemoryInterpretationStatus,
    MemoryTurnResult,
)


class SequenceModel:
    def __init__(
        self,
        outputs,
    ):
        self._outputs = iter(
            outputs
        )

    def generate_constrained_json(
        self,
        **kwargs,
    ):
        return next(
            self._outputs
        )


def interpretation_with_property(
    *,
    semantic_type: str,
    semantic_labels: tuple[str, ...],
) -> MemoryInterpretation:
    property_proposal = (
        PropertyProposal(
            local_ref="property_value",
            semantic_labels=(
                semantic_labels
            ),
            semantic_type=(
                semantic_type
            ),
            cardinality=(
                Cardinality.SINGLE_CURRENT
            ),
            value_type=(
                ValueType.STRING
            ),
        )
    )

    fact = FactProposal(
        subject_ref="owner",
        property_ref="property_value",
        value="literal-value",
        memory_class=(
            MemoryClass.FACTUAL
        ),
        confidence=1.0,
        unit=None,
        value_entity_ref=None,
        raw_representation=None,
        valid_from=None,
        valid_until=None,
    )

    return MemoryInterpretation(
        operation=(
            MemoryOperation.REMEMBER
        ),
        confidence=1.0,
        explicit_memory_request=True,
        entities=(),
        fact_properties=(
            property_proposal,
        ),
        relation_properties=(),
        facts=(
            fact,
        ),
        relations=(),
        needs_confirmation=False,
        ambiguities=(),
    )


class Memory1TypedFailureSemanticPlaneTests(
    unittest.TestCase
):
    def test_remember_stage2_contract_failure_carries_control_hint(
        self,
    ) -> None:
        adapter = (
            TrustedTwoStageSemanticMemoryAdapter(
                SequenceModel(
                    (
                        (
                            '{"operation":"REMEMBER",'
                            '"confidence":1.0}'
                        ),
                        "{not-valid-json",
                    )
                ),
                model_id="fake-model",
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ) as captured:
            adapter.interpret(
                "pedido",
                context=(
                    InterpreterContext(
                        known_entity_refs=(
                            "owner",
                        )
                    )
                ),
            )

        self.assertIs(
            captured.exception.selected_operation,
            MemoryOperation.REMEMBER,
        )

    def test_recall_stage2_contract_failure_carries_control_hint(
        self,
    ) -> None:
        adapter = (
            TrustedTwoStageSemanticMemoryAdapter(
                SequenceModel(
                    ('{"operation":"RECALL",'
                            '"confidence":1.0}', "{not-valid-json", "{not-valid-json")
                ),
                model_id="fake-model",
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ) as captured:
            adapter.interpret(
                "pedido",
                context=(
                    InterpreterContext(
                        known_entity_refs=(
                            "owner",
                        )
                    )
                ),
            )

        self.assertIs(
            captured.exception.selected_operation,
            MemoryOperation.RECALL,
        )

    def test_control_plane_only_property_identity_is_rejected(
        self,
    ) -> None:
        interpretation = (
            interpretation_with_property(
                semantic_type="REMEMBER",
                semantic_labels=(
                    "REMEMBER",
                ),
            )
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "MemoryOperation control token",
        ):
            validate_remember_property_control_plane_separation(
                interpretation
            )

    def test_control_token_plus_real_semantic_content_is_not_rejected(
        self,
    ) -> None:
        interpretation = (
            interpretation_with_property(
                semantic_type="REMEMBER",
                semantic_labels=(
                    "owner attribute",
                ),
            )
        )

        validate_remember_property_control_plane_separation(
            interpretation
        )

    def test_base_prompt_separates_control_and_semantic_planes(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertIn(
            "control-plane metadata only",
            prompt,
        )

        self.assertIn(
            "semantic_labels and semantic_type",
            prompt,
        )

        self.assertIn(
            "Never use the memory operation token",
            prompt,
        )

    def test_retry_prompt_rejects_operation_token_as_property_identity(
        self,
    ) -> None:
        prompt = (
            _remember_structural_retry_prompt(
                "BASE",
                validation_reason=(
                    "reason"
                ),
            )
        )

        self.assertIn(
            "Do not use the selected "
            "MemoryOperation token",
            prompt,
        )

        self.assertIn(
            "semantic_labels or semantic_type",
            prompt,
        )

    def test_cli_schema_invalid_remember_returns_before_router(
        self,
    ) -> None:
        source = inspect.getsource(
            cli_module.main
        )

        process = source[
            source.index(
                "def process_request"
            ):
        ]

        handler_start = process.index(
            "except MemoryModelContractError as exc:"
        )

        handler_end = process.index(
            "except Exception as exc:",
            handler_start,
        )

        handler = process[
            handler_start:
            handler_end
        ]

        self.assertIn(
            "exc.selected_operation",
            handler,
        )

        self.assertIn(
            "MemoryOperation.REMEMBER",
            handler,
        )

        self.assertIn(
            "não guardei nada",
            handler,
        )

        self.assertIn(
            "return answer, route, elapsed, None",
            handler,
        )

        self.assertNotIn(
            "route_runtime_request(",
            handler,
        )

    def test_failed_memory_turn_result_still_cannot_claim_operation(
        self,
    ) -> None:
        with self.assertRaises(
            MemoryValidationError
        ):
            MemoryTurnResult(
                operation=(
                    MemoryOperation.REMEMBER
                ),
                interpretation_status=(
                    MemoryInterpretationStatus.SCHEMA_INVALID
                ),
            )


if __name__ == "__main__":
    unittest.main()
