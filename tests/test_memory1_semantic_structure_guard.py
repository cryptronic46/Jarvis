from __future__ import annotations

import inspect
import unittest

from jarvis_core.memory.enums import (
    Cardinality,
    MemoryClass,
    ValueType,
)

from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.interpreter import (
    EntityProposal,
    FactProposal,
    MemoryInterpretation,
    MemoryOperation,
    PropertyProposal,
)

from jarvis_core.memory.model_adapter import (
    _remember_structural_retry_prompt,
    trusted_memory_remember_extractor_system_prompt,
)

from jarvis_core.memory.proposal_validation import (
    validate_new_entity_literal_wrappers,
    validate_remember_entity_proposal_usage,
)

from jarvis_core.memory.write_executor import (
    execute_memory_resolution_plan,
)


def property_proposal(
    *,
    semantic_type: str = "attribute",
    semantic_labels: tuple[str, ...] = (
        "attribute",
    ),
    value_type: ValueType = ValueType.STRING,
) -> PropertyProposal:
    return PropertyProposal(
        local_ref="property_value",
        semantic_labels=semantic_labels,
        semantic_type=semantic_type,
        cardinality=(
            Cardinality.SINGLE_CURRENT
        ),
        value_type=value_type,
    )


def entity_proposal(
    *,
    entity_type: str = "person",
) -> EntityProposal:
    return EntityProposal(
        local_ref="target",
        canonical_name="Target",
        entity_type=entity_type,
    )


def fact_proposal(
    *,
    memory_class: MemoryClass,
    value_entity_ref: str | None = None,
    subject_ref: str = "owner",
    property_ref: str = "property_value",
) -> FactProposal:
    return FactProposal(
        subject_ref=subject_ref,
        property_ref=property_ref,
        value=(
            value_entity_ref
            if value_entity_ref is not None
            else "literal-value"
        ),
        memory_class=memory_class,
        confidence=1.0,
        value_entity_ref=value_entity_ref,
    )


def remember(
    *,
    entities=(),
    properties=(),
    facts=(),
) -> MemoryInterpretation:
    return MemoryInterpretation(
        operation=MemoryOperation.REMEMBER,
        confidence=1.0,
        explicit_memory_request=True,
        entities=tuple(entities),
        fact_properties=tuple(
            properties
        ),
        facts=tuple(facts),
    )


class Memory1SemanticStructureGuardTests(
    unittest.TestCase
):
    def test_entity_ref_requires_relational_memory_class(
        self,
    ) -> None:
        interpretation = remember(
            properties=(
                property_proposal(
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.PREFERENCE
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "ENTITY_REF fact property requires "
            "RELATIONAL memory_class",
        ):
            validate_remember_entity_proposal_usage(
                interpretation
            )

    def test_relational_requires_entity_ref_property(
        self,
    ) -> None:
        interpretation = remember(
            properties=(
                property_proposal(
                    value_type=(
                        ValueType.STRING
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                ),
            ),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "RELATIONAL fact requires "
            "ENTITY_REF fact property",
        ):
            validate_remember_entity_proposal_usage(
                interpretation
            )

    def test_entity_ref_relational_pair_is_valid(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity_proposal(
                    entity_type="person",
                ),
            ),
            properties=(
                property_proposal(
                    semantic_type=(
                        "relationship_role"
                    ),
                    semantic_labels=(
                        "contact",
                    ),
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            interpretation
        )

    def test_literal_non_relational_pair_is_valid(
        self,
    ) -> None:
        interpretation = remember(
            properties=(
                property_proposal(
                    value_type=(
                        ValueType.STRING
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.PREFERENCE
                    ),
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            interpretation
        )

    def test_new_entity_wrapper_matching_semantic_type_is_rejected(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity_proposal(
                    entity_type="wrapper_type",
                ),
            ),
            properties=(
                property_proposal(
                    semantic_type="wrapper_type",
                    semantic_labels=(
                        "role_label",
                    ),
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            interpretation
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "NEW entity proposal appears "
            "to wrap a literal fact value",
        ):
            validate_new_entity_literal_wrappers(
                interpretation,
                new_entity_refs=(
                    "target",
                ),
            )

    def test_new_entity_wrapper_matching_semantic_label_is_rejected(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity_proposal(
                    entity_type="wrapper_label",
                ),
            ),
            properties=(
                property_proposal(
                    semantic_type=(
                        "different_role"
                    ),
                    semantic_labels=(
                        "wrapper_label",
                    ),
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "NEW entity proposal appears "
            "to wrap a literal fact value",
        ):
            validate_new_entity_literal_wrappers(
                interpretation,
                new_entity_refs=(
                    "target",
                ),
            )

    def test_wrapper_rule_does_not_apply_to_non_new_entity(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity_proposal(
                    entity_type="wrapper_type",
                ),
            ),
            properties=(
                property_proposal(
                    semantic_type="wrapper_type",
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        validate_new_entity_literal_wrappers(
            interpretation,
            new_entity_refs=(),
        )

    def test_independently_typed_new_entity_remains_valid(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity_proposal(
                    entity_type="vehicle",
                ),
            ),
            properties=(
                property_proposal(
                    semantic_type="owned_vehicle",
                    semantic_labels=(
                        "owns vehicle",
                    ),
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact_proposal(
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref="target",
                ),
            ),
        )

        validate_new_entity_literal_wrappers(
            interpretation,
            new_entity_refs=(
                "target",
            ),
        )

    def test_base_prompt_declares_value_class_biconditional(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertIn(
            "ENTITY_REF requires "
            "memory_class=RELATIONAL",
            prompt,
        )

        self.assertIn(
            "memory_class=RELATIONAL "
            "requires ENTITY_REF",
            prompt,
        )

        self.assertIn(
            "Literal fact ValueTypes must "
            "use a non-RELATIONAL MemoryClass",
            prompt,
        )

    def test_retry_prompt_reconsiders_entity_and_surfaces_core_reason(
        self,
    ) -> None:
        prompt = (
            _remember_structural_retry_prompt(
                "BASE_PROMPT",
                validation_reason=(
                    "CORE_REASON"
                ),
            )
        )

        self.assertTrue(
            prompt.startswith(
                "BASE_PROMPT"
            )
        )

        self.assertIn(
            "CORE_REASON",
            prompt,
        )

        self.assertIn(
            "reconsider whether each proposed "
            "entity should exist independently",
            prompt,
        )

        self.assertIn(
            "Do not fabricate value_entity_ref",
            prompt,
        )

        self.assertIn(
            "only wraps a literal value",
            prompt,
        )

    def test_write_executor_invokes_wrapper_guard_before_episode(
        self,
    ) -> None:
        source = inspect.getsource(
            execute_memory_resolution_plan
        )

        guard_index = source.index(
            "validate_new_entity_literal_wrappers("
        )

        episode_index = source.index(
            "episode = MemoryEpisode("
        )

        self.assertLess(
            guard_index,
            episode_index,
        )

    def test_write_executor_rechecks_value_class_invariant(
        self,
    ) -> None:
        source = inspect.getsource(
            execute_memory_resolution_plan
        )

        self.assertIn(
            "ENTITY_REF fact property requires ",
            source,
        )

        self.assertIn(
            "RELATIONAL fact requires ",
            source,
        )


if __name__ == "__main__":
    unittest.main()
