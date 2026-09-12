from __future__ import annotations

import inspect
import unittest

import jarvis_core.memory.resolution_plan as resolution_plan_module
import jarvis_core.memory.write_executor as write_executor_module

from jarvis_core.memory.errors import (
    MemoryCanonicalContractMismatchError,
    MemoryValidationError,
)

from jarvis_core.memory.model_adapter import (
    _remember_structural_retry_prompt,
    trusted_memory_remember_extractor_system_prompt,
)

from jarvis_core.memory.property_resolution import (
    CanonicalPropertyCatalogReader,
)


class Memory1E4RPromptResolutionGuardTests(
    unittest.TestCase
):
    def test_canonical_contract_mismatch_is_validation_subclass(
        self,
    ) -> None:
        self.assertTrue(
            issubclass(
                MemoryCanonicalContractMismatchError,
                MemoryValidationError,
            )
        )

    def test_base_stage2_prompt_explicitly_forbids_literal_entity_wrapping(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertIn(
            "Do not fabricate value_entity_ref",
            prompt,
        )

        self.assertIn(
            "merely to make an entity proposal appear used",
            prompt,
        )

        self.assertIn(
            "would only wrap a literal value",
            prompt,
        )

        self.assertIn(
            "narrowest literal ValueType",
            prompt,
        )

        self.assertIn(
            "coherent non-RELATIONAL MemoryClass",
            prompt,
        )

    def test_retry_prompt_retains_wrapper_rule_without_payload_reuse(
        self,
    ) -> None:
        prompt = _remember_structural_retry_prompt(
            "BASE_PROMPT",
            validation_reason="CORE_REASON",
        )

        self.assertIn(
            "Do not fabricate value_entity_ref",
            prompt,
        )

        self.assertIn(
            "only wraps a literal value",
            prompt,
        )

        self.assertIn(
            "Do not reuse, prune, patch or locally repair "
            "the previous payload.",
            prompt,
        )

    def test_resolution_plan_runs_wrapper_guard_before_properties(
        self,
    ) -> None:
        source = inspect.getsource(
            resolution_plan_module
        )

        entity_pos = source.index(
            "remember_entities = ("
        )

        guard_pos = source.index(
            "validate_new_entity_literal_wrappers(",
            entity_pos,
        )

        property_pos = source.index(
            "remember_fact_properties = (",
            entity_pos,
        )

        self.assertLess(
            entity_pos,
            guard_pos,
        )

        self.assertLess(
            guard_pos,
            property_pos,
        )

        guard_source = source[
            guard_pos:
            property_pos
        ]

        self.assertIn(
            "row.resolution.action",
            guard_source,
        )

        self.assertIn(
            "IdentityResolutionAction.NEW",
            guard_source,
        )

    def test_remember_existing_property_contract_uses_typed_diagnostic(
        self,
    ) -> None:
        source = inspect.getsource(
            CanonicalPropertyCatalogReader
            .validate_existing_property_contract
        )

        self.assertEqual(
            source.count(
                "MemoryCanonicalContractMismatchError("
            ),
            4,
        )

        self.assertIn(
            "kind mismatch",
            source,
        )

        self.assertIn(
            "cardinality mismatch",
            source,
        )

        self.assertIn(
            "value_type mismatch",
            source,
        )

        self.assertIn(
            "MemoryValidationError(",
            source,
        )

    def test_write_executor_retains_defense_in_depth_guard(
        self,
    ) -> None:
        source = inspect.getsource(
            write_executor_module
            .execute_memory_resolution_plan
        )

        guard_pos = source.index(
            "validate_new_entity_literal_wrappers("
        )

        episode_pos = source.index(
            "episode = MemoryEpisode("
        )

        self.assertLess(
            guard_pos,
            episode_pos,
        )


if __name__ == "__main__":
    unittest.main()
