from __future__ import annotations

import json
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
    InterpreterContext,
    MemoryInterpretation,
    MemoryOperation,
    PropertyProposal,
    RelationProposal,
)

from jarvis_core.memory.model_adapter import (
    MemoryModelContractError,
    TrustedTwoStageSemanticMemoryAdapter,
)

from jarvis_core.memory.proposal_validation import (
    validate_remember_entity_proposal_usage,
)


def fact_property(
    *,
    local_ref: str = "property_preference",
    value_type: ValueType = ValueType.STRING,
) -> PropertyProposal:
    return PropertyProposal(
        local_ref=local_ref,
        semantic_labels=(
            "preference",
        ),
        semantic_type=(
            "preference"
        ),
        cardinality=(
            Cardinality.SINGLE_CURRENT
        ),
        value_type=value_type,
    )


def relation_property(
    *,
    local_ref: str = "property_relationship",
) -> PropertyProposal:
    return PropertyProposal(
        local_ref=local_ref,
        semantic_labels=(
            "relationship",
        ),
        semantic_type=(
            "relationship"
        ),
        cardinality=(
            Cardinality.MULTI_CURRENT
        ),
        value_type=None,
    )


def entity(
    local_ref: str,
) -> EntityProposal:
    return EntityProposal(
        local_ref=local_ref,
        canonical_name=local_ref,
        entity_type="person",
    )


def fact(
    *,
    subject_ref: str = "owner",
    property_ref: str = "property_preference",
    value="pt-PT",
    memory_class: MemoryClass = MemoryClass.PREFERENCE,
    value_entity_ref: str | None = None,
) -> FactProposal:
    return FactProposal(
        subject_ref=subject_ref,
        property_ref=property_ref,
        value=value,
        memory_class=memory_class,
        confidence=0.99,
        value_entity_ref=(
            value_entity_ref
        ),
    )


def relation(
    *,
    source_ref: str,
    target_ref: str,
) -> RelationProposal:
    return RelationProposal(
        source_ref=source_ref,
        property_ref=(
            "property_relationship"
        ),
        target_ref=target_ref,
        memory_class=(
            MemoryClass.RELATIONAL
        ),
        confidence=0.99,
    )


def remember(
    *,
    entities=(),
    fact_properties=(),
    relation_properties=(),
    facts=(),
    relations=(),
) -> MemoryInterpretation:
    return MemoryInterpretation(
        operation=(
            MemoryOperation.REMEMBER
        ),
        confidence=0.99,
        explicit_memory_request=True,
        entities=tuple(entities),
        fact_properties=tuple(
            fact_properties
        ),
        relation_properties=tuple(
            relation_properties
        ),
        facts=tuple(facts),
        relations=tuple(
            relations
        ),
    )


class ScriptedMemoryModel:
    def __init__(
        self,
        outputs,
    ) -> None:
        self.outputs = list(
            outputs
        )

        self.calls = []
        self.returned = []

    def generate_constrained_json(
        self,
        *,
        system_prompt,
        user_text,
        context_json,
        schema,
        num_predict=None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt":
                    system_prompt,

                "user_text":
                    user_text,

                "context_json":
                    context_json,

                "schema":
                    schema,

                "num_predict":
                    num_predict,
            }
        )

        if not self.outputs:
            raise AssertionError(
                "unexpected model invocation"
            )

        raw = self.outputs.pop(
            0
        )

        self.returned.append(
            raw
        )

        return raw


def operation_json() -> str:
    return json.dumps(
        {
            "operation":
                "REMEMBER",

            "confidence":
                0.99,
        },
        separators=(
            ",",
            ":",
        ),
    )


def remember_json(
    *,
    orphan_entity: bool,
) -> str:
    entities = []

    if orphan_entity:
        entities.append(
            {
                "local_ref":
                    "unused_entity",

                "canonical_name":
                    "unused entity",

                "entity_type":
                    "concept",
            }
        )

    return json.dumps(
        {
            "entities":
                entities,

            "fact_properties": [
                {
                    "local_ref":
                        "property_preferred_language",

                    "semantic_labels": [
                        "preferred language",
                    ],

                    "semantic_type":
                        "preferred_language",

                    "cardinality":
                        "SINGLE_CURRENT",

                    "value_type":
                        "STRING",
                }
            ],

            "relation_properties":
                [],

            "facts": [
                {
                    "subject_ref":
                        "owner",

                    "property_ref":
                        "property_preferred_language",

                    "value":
                        "pt-PT",

                    "memory_class":
                        "PREFERENCE",

                    "confidence":
                        0.99,
                }
            ],

            "relations":
                [],

            "needs_confirmation":
                False,

            "ambiguities":
                [],
        },
        separators=(
            ",",
            ":",
        ),
    )


class EntityCrossReferenceTests(
    unittest.TestCase
):
    def test_orphan_entity_is_rejected(
        self,
    ) -> None:
        interpretation = remember(
            entities=(
                entity(
                    "unused_entity"
                ),
            ),
            fact_properties=(
                fact_property(),
            ),
            facts=(
                fact(),
            ),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "unused entity proposal",
        ):
            validate_remember_entity_proposal_usage(
                interpretation
            )

    def test_fact_subject_ref_uses_entity(
        self,
    ) -> None:
        result = remember(
            entities=(
                entity(
                    "person_a"
                ),
            ),
            fact_properties=(
                fact_property(),
            ),
            facts=(
                fact(
                    subject_ref="person_a"
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            result
        )

        self.assertEqual(
            result.entities[0].local_ref,
            "person_a",
        )

    def test_fact_value_entity_ref_uses_entity(
        self,
    ) -> None:
        result = remember(
            entities=(
                entity(
                    "person_b"
                ),
            ),
            fact_properties=(
                fact_property(
                    local_ref=(
                        "property_contact"
                    ),
                    value_type=(
                        ValueType.ENTITY_REF
                    ),
                ),
            ),
            facts=(
                fact(
                    property_ref=(
                        "property_contact"
                    ),
                    value="person_b",
                    memory_class=(
                        MemoryClass.RELATIONAL
                    ),
                    value_entity_ref=(
                        "person_b"
                    ),
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            result
        )

        self.assertEqual(
            result.entities[0].local_ref,
            "person_b",
        )

    def test_relation_source_ref_uses_entity(
        self,
    ) -> None:
        result = remember(
            entities=(
                entity(
                    "person_c"
                ),
            ),
            relation_properties=(
                relation_property(),
            ),
            relations=(
                relation(
                    source_ref="person_c",
                    target_ref="owner",
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            result
        )

        self.assertEqual(
            result.entities[0].local_ref,
            "person_c",
        )

    def test_relation_target_ref_uses_entity(
        self,
    ) -> None:
        result = remember(
            entities=(
                entity(
                    "person_d"
                ),
            ),
            relation_properties=(
                relation_property(),
            ),
            relations=(
                relation(
                    source_ref="owner",
                    target_ref="person_d",
                ),
            ),
        )

        validate_remember_entity_proposal_usage(
            result
        )

        self.assertEqual(
            result.entities[0].local_ref,
            "person_d",
        )

    def test_known_owner_needs_no_entity_proposal(
        self,
    ) -> None:
        result = remember(
            fact_properties=(
                fact_property(),
            ),
            facts=(
                fact(),
            ),
        )

        validate_remember_entity_proposal_usage(
            result
        )

        self.assertEqual(
            result.entities,
            (),
        )


class StructuralRetryTests(
    unittest.TestCase
):
    def make_adapter(
        self,
        outputs,
    ):
        model = ScriptedMemoryModel(
            outputs
        )

        adapter = (
            TrustedTwoStageSemanticMemoryAdapter(
                model,
                model_id=(
                    "test-memory-model"
                ),
            )
        )

        return (
            model,
            adapter,
        )

    def test_structural_failure_retries_once(
        self,
    ) -> None:
        model, adapter = (
            self.make_adapter(
                [
                    operation_json(),
                    remember_json(
                        orphan_entity=True
                    ),
                    remember_json(
                        orphan_entity=False
                    ),
                ]
            )
        )

        envelope = adapter.interpret(
            (
                "Lembra-te de que o meu "
                "idioma preferido é pt-PT."
            ),
            context=(
                InterpreterContext(
                    known_entity_refs=(
                        "owner",
                    )
                )
            ),
        )

        self.assertEqual(
            len(model.calls),
            3,
        )

        self.assertEqual(
            envelope.interpretation.entities,
            (),
        )

        self.assertEqual(
            envelope
            .interpretation
            .facts[0]
            .value,
            "pt-PT",
        )

        self.assertIn(
            "structural Memory 1.0 contract",
            model.calls[2][
                "system_prompt"
            ],
        )

    def test_second_structural_failure_fails_closed(
        self,
    ) -> None:
        model, adapter = (
            self.make_adapter(
                [
                    operation_json(),
                    remember_json(
                        orphan_entity=True
                    ),
                    remember_json(
                        orphan_entity=True
                    ),
                ]
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ) as captured:
            adapter.interpret(
                "Lembra-te disto.",
                context=(
                    InterpreterContext(
                        known_entity_refs=(
                            "owner",
                        )
                    )
                ),
            )

        self.assertEqual(
            len(model.calls),
            3,
        )

        self.assertIsInstance(
            captured
            .exception
            .__cause__,
            MemoryValidationError,
        )

    def test_retry_does_not_prune_first_payload(
        self,
    ) -> None:
        invalid = remember_json(
            orphan_entity=True
        )

        valid = remember_json(
            orphan_entity=False
        )

        model, adapter = (
            self.make_adapter(
                [
                    operation_json(),
                    invalid,
                    valid,
                ]
            )
        )

        envelope = adapter.interpret(
            "Lembra-te disto.",
            context=(
                InterpreterContext(
                    known_entity_refs=(
                        "owner",
                    )
                )
            ),
        )

        first = json.loads(
            model.returned[1]
        )

        self.assertEqual(
            first["entities"][0][
                "local_ref"
            ],
            "unused_entity",
        )

        self.assertEqual(
            len(model.calls),
            3,
        )

        self.assertEqual(
            envelope.interpretation.entities,
            (),
        )

if __name__ == "__main__":
    unittest.main()
