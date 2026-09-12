from __future__ import annotations

import json
import unittest

from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    MemoryOperation,
    PropertyQueryProposal,
    parse_memory_interpretation,
)
from jarvis_core.memory.model_adapter import (
    MEMORY_INTERPRETER_CONTRACT_VERSION,
    MEMORY_INTERPRETER_SCHEMA_VERSION,
    MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION,
    memory_recall_extraction_json_schema,
)
from jarvis_core.memory.qwen_model import (
    memory_interpretation_json_schema,
)


class Memory1StructuredRecallPropertyQueryV2Tests(
    unittest.TestCase
):
    def test_interpreter_schema_evolves_to_v2_only(
        self,
    ) -> None:
        self.assertEqual(
            MEMORY_INTERPRETER_SCHEMA_VERSION,
            4,
        )

        self.assertEqual(
            MEMORY_INTERPRETER_CONTRACT_VERSION,
            "1.0",
        )

        self.assertEqual(
            MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION,
            "1.0",
        )

    def test_property_query_groups_multiple_labels_for_one_property(
        self,
    ) -> None:
        result = parse_memory_interpretation(
            json.dumps(
                {
                    "operation":
                        "RECALL",

                    "confidence":
                        0.91,

                    "explicit_memory_request":
                        True,

                    "query": {
                        "subject_refs": [
                            "owner",
                        ],

                        "fact_properties": [
                            {
                                "semantic_labels": [
                                    "preference",
                                    "color",
                                ],

                                "semantic_type":
                                    "preference",
                            },
                        ],

                        "relation_properties":
                            [],

                        "target_refs":
                            [],

                        "temporal_mode":
                            "CURRENT",
                    },
                }
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.RECALL,
        )

        self.assertIsNotNone(
            result.query
        )

        assert result.query is not None

        self.assertEqual(
            len(
                result.query
                .fact_properties
            ),
            1,
        )

        proposal = (
            result.query
            .fact_properties[0]
        )

        self.assertIsInstance(
            proposal,
            PropertyQueryProposal,
        )

        self.assertEqual(
            proposal.semantic_labels,
            (
                "preference",
                "color",
            ),
        )

        self.assertEqual(
            proposal.semantic_type,
            "preference",
        )

    def test_multiple_property_objects_mean_multiple_properties(
        self,
    ) -> None:
        result = parse_memory_interpretation(
            json.dumps(
                {
                    "operation":
                        "RECALL",

                    "confidence":
                        0.88,

                    "explicit_memory_request":
                        True,

                    "query": {
                        "subject_refs": [
                            "owner",
                        ],

                        "fact_properties": [
                            {
                                "semantic_labels": [
                                    "attribute_a",
                                ],

                                "semantic_type":
                                    "attribute",
                            },

                            {
                                "semantic_labels": [
                                    "attribute_b",
                                ],

                                "semantic_type":
                                    "attribute",
                            },
                        ],

                        "relation_properties":
                            [],
                    },
                }
            )
        )

        assert result.query is not None

        self.assertEqual(
            len(
                result.query
                .fact_properties
            ),
            2,
        )

    def test_old_flat_predicates_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    {
                        "operation":
                            "RECALL",

                        "confidence":
                            0.9,

                        "explicit_memory_request":
                            True,

                        "query": {
                            "subject_refs": [
                                "owner",
                            ],

                            "predicates": [
                                "attribute",
                            ],
                        },
                    }
                )
            )

    def test_old_flat_relation_predicates_fail_closed(
        self,
    ) -> None:
        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    {
                        "operation":
                            "RECALL",

                        "confidence":
                            0.9,

                        "explicit_memory_request":
                            True,

                        "query": {
                            "subject_refs": [
                                "owner",
                            ],

                            "relation_predicates": [
                                "relationship",
                            ],
                        },
                    }
                )
            )

    def test_empty_v2_query_is_structurally_empty(
        self,
    ) -> None:
        result = parse_memory_interpretation(
            json.dumps(
                {
                    "operation":
                        "NONE",

                    "confidence":
                        0.95,

                    "explicit_memory_request":
                        False,

                    "query": {
                        "subject_refs":
                            [],

                        "fact_properties":
                            [],

                        "relation_properties":
                            [],

                        "target_refs":
                            [],

                        "temporal_mode":
                            "CURRENT",
                    },
                }
            )
        )

        self.assertIsNone(
            result.query
        )

    def test_property_query_rejects_duplicate_labels(
        self,
    ) -> None:
        with self.assertRaises(
            MemoryValidationError
        ):
            PropertyQueryProposal(
                semantic_labels=(
                    "same",
                    "same",
                ),
                semantic_type=(
                    "property"
                ),
            )

    def test_property_query_rejects_empty_labels(
        self,
    ) -> None:
        with self.assertRaises(
            MemoryValidationError
        ):
            PropertyQueryProposal(
                semantic_labels=(),
                semantic_type=(
                    "property"
                ),
            )

    def test_two_stage_recall_schema_is_structured(
        self,
    ) -> None:
        schema = (
            memory_recall_extraction_json_schema()
        )

        query = (
            schema[
                "properties"
            ][
                "query"
            ]
        )

        properties = query[
            "properties"
        ]

        self.assertIn(
            "fact_properties",
            properties,
        )

        self.assertIn(
            "relation_properties",
            properties,
        )

        self.assertNotIn(
            "predicates",
            properties,
        )

        self.assertNotIn(
            "relation_predicates",
            properties,
        )

        fact_item = (
            properties[
                "fact_properties"
            ][
                "items"
            ]
        )

        self.assertEqual(
            set(
                fact_item[
                    "required"
                ]
            ),
            {
                "semantic_labels",
                "semantic_type",
            },
        )

        self.assertNotIn(
            "canonical_id",
            fact_item[
                "properties"
            ],
        )

    def test_monolithic_qwen_schema_matches_v2_query_shape(
        self,
    ) -> None:
        schema = (
            memory_interpretation_json_schema()
        )

        recall_branch = (
            schema[
                "oneOf"
            ][2]
        )

        query = (
            recall_branch[
                "properties"
            ][
                "query"
            ]
        )

        properties = query[
            "properties"
        ]

        self.assertIn(
            "fact_properties",
            properties,
        )

        self.assertIn(
            "relation_properties",
            properties,
        )

        self.assertNotIn(
            "predicates",
            properties,
        )

        self.assertNotIn(
            "relation_predicates",
            properties,
        )

    def test_structured_query_contains_no_canonical_property_id(
        self,
    ) -> None:
        proposal = (
            PropertyQueryProposal(
                semantic_labels=(
                    "semantic_label",
                ),
                semantic_type=(
                    "property"
                ),
            )
        )

        self.assertFalse(
            hasattr(
                proposal,
                "canonical_id",
            )
        )


if __name__ == "__main__":
    unittest.main()
