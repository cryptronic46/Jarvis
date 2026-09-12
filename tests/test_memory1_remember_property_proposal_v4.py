from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import FrozenInstanceError

from jarvis_core.memory import (
    interpreter,
    model_adapter,
    qwen_model,
)
from jarvis_core.memory.enums import (
    Cardinality,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    FactProposal,
    MemoryOperation,
    PropertyProposal,
    RelationProposal,
    parse_memory_interpretation,
)


def fact_property(
    *,
    local_ref="age_property",
    value_type="INTEGER",
):
    return {
        "local_ref": local_ref,
        "semantic_labels": ["age"],
        "semantic_type": "age",
        "cardinality": "SINGLE_CURRENT",
        "value_type": value_type,
    }


def scalar_fact(
    *,
    property_ref="age_property",
):
    return {
        "subject_ref": "owner",
        "property_ref": property_ref,
        "value": 38,
        "memory_class": "FACTUAL",
        "confidence": 0.99,
    }


def remember_payload():
    return {
        "operation": "REMEMBER",
        "confidence": 0.99,
        "explicit_memory_request": True,
        "entities": [],
        "fact_properties": [
            fact_property()
        ],
        "relation_properties": [],
        "facts": [
            scalar_fact()
        ],
        "relations": [],
        "query": None,
        "needs_confirmation": False,
        "ambiguities": [],
    }


def qwen_remember_branch():
    schema = (
        qwen_model
        .memory_interpretation_json_schema()
    )

    return next(
        branch
        for branch in schema["oneOf"]
        if (
            branch[
                "properties"
            ][
                "operation"
            ].get(
                "const"
            )
            == "REMEMBER"
        )
    )


class Memory1RememberPropertyProposalV4Tests(
    unittest.TestCase,
):
    def test_schema_version_is_v4(
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

    def test_property_proposal_is_first_class(
        self,
    ):
        proposal = PropertyProposal(
            local_ref="age_property",
            semantic_labels=("age",),
            semantic_type="age",
            cardinality=(
                Cardinality
                .SINGLE_CURRENT
            ),
            value_type=(
                ValueType.INTEGER
            ),
        )

        self.assertEqual(
            tuple(
                proposal
                .__dataclass_fields__
            ),
            (
                "local_ref",
                "semantic_labels",
                "semantic_type",
                "cardinality",
                "value_type",
            ),
        )

        self.assertFalse(
            hasattr(
                proposal,
                "kind",
            )
        )

        self.assertFalse(
            hasattr(
                proposal,
                "canonical_id",
            )
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            proposal.local_ref = "other"

    def test_assertions_do_not_duplicate_property_structure(
        self,
    ):
        for forbidden in (
            "predicate",
            "value_type",
            "cardinality",
        ):
            self.assertNotIn(
                forbidden,
                FactProposal
                .__dataclass_fields__,
            )

        for forbidden in (
            "predicate",
            "cardinality",
        ):
            self.assertNotIn(
                forbidden,
                RelationProposal
                .__dataclass_fields__,
            )

        self.assertIn(
            "property_ref",
            FactProposal
            .__dataclass_fields__,
        )

        self.assertIn(
            "property_ref",
            RelationProposal
            .__dataclass_fields__,
        )

    def test_valid_v4_fact_parses(
        self,
    ):
        result = (
            parse_memory_interpretation(
                json.dumps(
                    remember_payload()
                )
            )
        )

        self.assertEqual(
            result.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            result
            .facts[0]
            .property_ref,
            "age_property",
        )

        self.assertEqual(
            result
            .fact_properties[0]
            .value_type,
            ValueType.INTEGER,
        )

    def test_duplicate_property_ref_fails_closed(
        self,
    ):
        payload = (
            remember_payload()
        )

        payload[
            "fact_properties"
        ].append(
            fact_property()
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(payload)
            )

    def test_cross_kind_property_ref_fails_closed(
        self,
    ):
        payload = (
            remember_payload()
        )

        payload[
            "relation_properties"
        ] = [
            {
                "local_ref":
                    "age_property",
                "semantic_labels": [
                    "related",
                ],
                "semantic_type":
                    "relation",
                "cardinality":
                    "MULTI_CURRENT",
            }
        ]

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(payload)
            )

    def test_unused_property_fails_closed(
        self,
    ):
        payload = (
            remember_payload()
        )

        payload["facts"] = []

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(payload)
            )

    def test_property_reuse_is_allowed(
        self,
    ):
        payload = (
            remember_payload()
        )

        second = scalar_fact()
        second["value"] = 39

        payload["facts"].append(
            second
        )

        result = (
            parse_memory_interpretation(
                json.dumps(payload)
            )
        )

        self.assertEqual(
            len(result.facts),
            2,
        )

        self.assertEqual(
            len(
                result.fact_properties
            ),
            1,
        )

    def test_entity_ref_contract_is_cross_object(
        self,
    ):
        payload = (
            remember_payload()
        )

        payload[
            "fact_properties"
        ][0][
            "value_type"
        ] = "ENTITY_REF"

        payload[
            "facts"
        ][0][
            "value"
        ] = "person_ref"

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(payload)
            )

        payload[
            "facts"
        ][0][
            "value_entity_ref"
        ] = "person_ref"

        result = (
            parse_memory_interpretation(
                json.dumps(payload)
            )
        )

        self.assertEqual(
            result
            .facts[0]
            .value_entity_ref,
            "person_ref",
        )

    def test_relation_property_schema_has_no_value_type(
        self,
    ):
        schema = (
            model_adapter
            .memory_remember_extraction_json_schema()
        )

        fact_item = (
            schema[
                "properties"
            ][
                "fact_properties"
            ][
                "items"
            ]
        )

        relation_item = (
            schema[
                "properties"
            ][
                "relation_properties"
            ][
                "items"
            ]
        )

        self.assertIn(
            "value_type",
            fact_item[
                "properties"
            ],
        )

        self.assertNotIn(
            "value_type",
            relation_item[
                "properties"
            ],
        )

        self.assertNotIn(
            "kind",
            fact_item[
                "properties"
            ],
        )

        self.assertNotIn(
            "kind",
            relation_item[
                "properties"
            ],
        )

    def test_qwen_remember_required_is_v4(
        self,
    ):
        branch = (
            qwen_remember_branch()
        )

        self.assertEqual(
            tuple(
                branch[
                    "required"
                ]
            ),
            (
                "operation",
                "confidence",
                "explicit_memory_request",
                "entities",
                "fact_properties",
                "relation_properties",
                "facts",
                "relations",
            ),
        )

        rendered = json.dumps(
            branch,
            sort_keys=True,
        )

        self.assertNotIn(
            '"predicate"',
            rendered,
        )

    def test_v3_fact_shape_is_rejected(
        self,
    ):
        payload = (
            remember_payload()
        )

        payload["facts"][0] = {
            "subject_ref": "owner",
            "predicate": "age",
            "value_type": "INTEGER",
            "value": 38,
            "memory_class": "FACTUAL",
            "cardinality":
                "SINGLE_CURRENT",
            "confidence": 0.99,
        }

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(payload)
            )

    def test_old_schema_helpers_are_physically_removed(
        self,
    ):
        self.assertFalse(
            hasattr(
                model_adapter,
                "_non_entity_fact_extraction_schema",
            )
        )

        self.assertFalse(
            hasattr(
                model_adapter,
                "_entity_ref_fact_extraction_schema",
            )
        )

    def test_interpreter_has_no_legacy_predicate_dependency(
        self,
    ):
        source = inspect.getsource(
            interpreter
        )

        self.assertNotIn(
            "require_predicate",
            source,
        )


if __name__ == "__main__":
    unittest.main()
