from __future__ import annotations

import unittest
from dataclasses import (
    FrozenInstanceError,
)

from jarvis_core.memory import (
    interpreter,
    model_adapter,
    qwen_model,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    EntityQueryProposal,
    MemoryQueryProposal,
)


def recall_query_schema_from_qwen():
    schema = (
        qwen_model
        .memory_interpretation_json_schema()
    )

    for branch in schema[
        "oneOf"
    ]:
        operation = (
            branch[
                "properties"
            ][
                "operation"
            ]
            .get(
                "const"
            )
        )

        if operation == "RECALL":
            return (
                branch[
                    "properties"
                ][
                    "query"
                ]
            )

    raise AssertionError(
        "RECALL schema not found"
    )


class Memory1RecallEntityQueryV3Tests(
    unittest.TestCase,
):
    def test_schema_versions_are_v3_with_contracts_stable(
        self,
    ):
        self.assertEqual(
            model_adapter
            .MEMORY_INTERPRETER_SCHEMA_VERSION,
            4,
        )

        self.assertEqual(
            model_adapter
            .MEMORY_INTERPRETER_CONTRACT_VERSION,
            "1.0",
        )

        self.assertEqual(
            interpreter
            .MEMORY_MODEL_CONTEXT_CONTRACT_VERSION,
            "1.0",
        )

        self.assertEqual(
            model_adapter
            .MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION,
            "1.0",
        )

    def test_entity_query_contract_is_narrow_and_immutable(
        self,
    ):
        query = EntityQueryProposal(
            local_ref="person_candidate",
            semantic_labels=(
                "named person",
                "person reference",
            ),
            semantic_type="PERSON",
        )

        self.assertEqual(
            tuple(
                query
                .__dataclass_fields__
            ),
            (
                "local_ref",
                "semantic_labels",
                "semantic_type",
            ),
        )

        for forbidden in (
            "canonical_id",
            "canonical_name",
            "aliases",
            "namespace_hint",
        ):
            self.assertFalse(
                hasattr(
                    query,
                    forbidden,
                )
            )

        with self.assertRaises(
            FrozenInstanceError
        ):
            query.local_ref = "other"

    def test_entity_query_semantics_fail_closed(
        self,
    ):
        bad_cases = (
            {
                "local_ref":
                    " ",
                "semantic_labels":
                    (
                        "person",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "local_ref":
                    " person ",
                "semantic_labels":
                    (
                        "person",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "local_ref":
                    "person",
                "semantic_labels":
                    (),
                "semantic_type":
                    "PERSON",
            },
            {
                "local_ref":
                    "person",
                "semantic_labels":
                    (
                        "person",
                        "person",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "local_ref":
                    "person",
                "semantic_labels":
                    (
                        " person ",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "local_ref":
                    "person",
                "semantic_labels":
                    (
                        "person",
                    ),
                "semantic_type":
                    " PERSON ",
            },
        )

        for case in bad_cases:
            with self.subTest(
                case=case
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    EntityQueryProposal(
                        **case
                    )

    def test_memory_query_accepts_correlated_entity_query(
        self,
    ):
        entity_query = (
            EntityQueryProposal(
                local_ref="person_candidate",
                semantic_labels=(
                    "named person",
                ),
                semantic_type="PERSON",
            )
        )

        query = MemoryQueryProposal(
            subject_refs=(
                "person_candidate",
            ),
            entity_queries=(
                entity_query,
            ),
        )

        self.assertEqual(
            query.entity_queries,
            (
                entity_query,
            ),
        )

    def test_trusted_ref_does_not_require_entity_query(
        self,
    ):
        query = MemoryQueryProposal(
            subject_refs=(
                "owner",
            ),
        )

        self.assertEqual(
            query.subject_refs,
            (
                "owner",
            ),
        )

        self.assertEqual(
            query.entity_queries,
            (),
        )

    def test_duplicate_entity_query_local_ref_fails_closed(
        self,
    ):
        first = EntityQueryProposal(
            local_ref="candidate",
            semantic_labels=(
                "person one",
            ),
            semantic_type="PERSON",
        )

        second = EntityQueryProposal(
            local_ref="candidate",
            semantic_labels=(
                "person two",
            ),
            semantic_type="PERSON",
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            MemoryQueryProposal(
                subject_refs=(
                    "candidate",
                ),
                entity_queries=(
                    first,
                    second,
                ),
            )

    def test_unused_entity_query_local_ref_fails_closed(
        self,
    ):
        entity_query = (
            EntityQueryProposal(
                local_ref="unused",
                semantic_labels=(
                    "person",
                ),
                semantic_type="PERSON",
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            MemoryQueryProposal(
                subject_refs=(
                    "owner",
                ),
                entity_queries=(
                    entity_query,
                ),
            )

    def test_private_query_parser_accepts_entity_queries(
        self,
    ):
        result = (
            interpreter
            ._parse_query(
                {
                    "subject_refs": [
                        "candidate",
                    ],
                    "entity_queries": [
                        {
                            "local_ref":
                                "candidate",

                            "semantic_labels": [
                                "named person",
                            ],

                            "semantic_type":
                                "PERSON",
                        },
                    ],
                    "fact_properties":
                        [],
                    "relation_properties":
                        [],
                    "target_refs":
                        [],
                    "temporal_mode":
                        "CURRENT",
                }
            )
        )

        self.assertEqual(
            result.subject_refs,
            (
                "candidate",
            ),
        )

        self.assertEqual(
            len(
                result.entity_queries
            ),
            1,
        )

        self.assertEqual(
            result
            .entity_queries[0]
            .local_ref,
            "candidate",
        )

    def test_parser_rejects_write_or_canonical_entity_fields(
        self,
    ):
        for forbidden in (
            "canonical_id",
            "canonical_name",
            "aliases",
            "namespace_hint",
        ):
            payload = {
                "subject_refs": [
                    "candidate",
                ],
                "entity_queries": [
                    {
                        "local_ref":
                            "candidate",

                        "semantic_labels": [
                            "person",
                        ],

                        "semantic_type":
                            "PERSON",

                        forbidden:
                            "forbidden",
                    },
                ],
            }

            with self.subTest(
                forbidden=forbidden
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    (
                        interpreter
                        ._parse_query(
                            payload
                        )
                    )

    def test_trusted_recall_schema_has_exact_entity_query_shape(
        self,
    ):
        schema = (
            model_adapter
            .memory_recall_extraction_json_schema()
        )

        query = (
            schema[
                "properties"
            ][
                "query"
            ]
        )

        self.assertIn(
            "entity_queries",
            query[
                "properties"
            ],
        )

        item = (
            query[
                "properties"
            ][
                "entity_queries"
            ][
                "items"
            ]
        )

        self.assertEqual(
            set(
                item[
                    "properties"
                ]
            ),
            {
                "local_ref",
                "semantic_labels",
                "semantic_type",
            },
        )

        self.assertEqual(
            set(
                item[
                    "required"
                ]
            ),
            {
                "local_ref",
                "semantic_labels",
                "semantic_type",
            },
        )

        self.assertFalse(
            item[
                "additionalProperties"
            ]
        )

    def test_qwen_recall_schema_has_same_entity_query_shape(
        self,
    ):
        query = (
            recall_query_schema_from_qwen()
        )

        self.assertIn(
            "entity_queries",
            query[
                "properties"
            ],
        )

        item = (
            query[
                "properties"
            ][
                "entity_queries"
            ][
                "items"
            ]
        )

        self.assertEqual(
            set(
                item[
                    "properties"
                ]
            ),
            {
                "local_ref",
                "semantic_labels",
                "semantic_type",
            },
        )

        self.assertNotIn(
            "canonical_id",
            item[
                "properties"
            ],
        )

    def test_recall_prompt_describes_query_not_write_semantics(
        self,
    ):
        prompt = (
            model_adapter
            .trusted_memory_recall_extractor_system_prompt()
        )

        self.assertIn(
            'interpreter_schema_version=4',
            prompt,
        )

        self.assertIn(
            "entity_queries",
            prompt,
        )

        self.assertIn(
            "known entity reference",
            prompt,
        )

        self.assertIn(
            "Do not emit canonical entity or property IDs",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
