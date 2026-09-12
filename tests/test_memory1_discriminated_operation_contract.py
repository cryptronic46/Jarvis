from __future__ import annotations

import json
import unittest

from jarvis_core.core.local_llm import (
    NativeLlamaClient,
)

from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.interpreter import (
    MemoryOperation,
    parse_memory_interpretation,
)

from jarvis_core.memory.qwen_model import (
    memory_interpretation_json_schema,
)



def fact_property():
    return {
        "local_ref": "age_property",
        "semantic_labels": [
            "age",
        ],
        "semantic_type": "age",
        "cardinality": "SINGLE_CURRENT",
        "value_type": "INTEGER",
    }


def fact():
    return {
        "subject_ref": "owner",
        "property_ref": "age_property",
        "value": 38,
        "memory_class": "FACTUAL",
        "confidence": 0.99,
    }



def query():
    return {'subject_refs': ['owner'], 'fact_properties': [{'semantic_labels': ['age'], 'semantic_type': 'property'}]}



def payload(
    operation,
    *,
    facts=None,
    query_value="__OMITTED__",
):
    fact_rows = list(
        facts
        or []
    )

    row = {
        "operation":
            operation,

        "confidence":
            0.99,

        "explicit_memory_request":
            (
                operation
                != "NONE"
            ),

        "entities":
            [],

        "fact_properties":
            (
                [
                    fact_property()
                ]
                if fact_rows
                else []
            ),

        "relation_properties":
            [],

        "facts":
            fact_rows,

        "relations":
            [],

        "needs_confirmation":
            False,

        "ambiguities":
            [],
    }

    if (
        query_value
        != "__OMITTED__"
    ):
        row[
            "query"
        ] = query_value

    return row



def parse(
    row,
):
    return (
        parse_memory_interpretation(
            json.dumps(
                row,
                ensure_ascii=False,
            )
        )
    )


class Memory1DiscriminatedOperationContractTests(
    unittest.TestCase
):
    def test_llama_safe_schema_preserves_proven_discriminators(
        self,
    ):
        probe = {
            "oneOf": [
                {
                    "type":
                        "object",

                    "properties": {
                        "operation": {
                            "const":
                                "NONE",
                        },
                    },

                    "required": [
                        "operation"
                    ],

                    "additionalProperties":
                        False,

                    "unsupported_keyword":
                        "discard-me",
                },
            ],
        }

        safe = (
            NativeLlamaClient
            ._llama_safe_schema(
                probe
            )
        )

        self.assertIn(
            "oneOf",
            safe,
        )

        branch = (
            safe[
                "oneOf"
            ][
                0
            ]
        )

        self.assertEqual(
            branch[
                "properties"
            ][
                "operation"
            ][
                "const"
            ],
            "NONE",
        )

        self.assertIs(
            branch[
                "additionalProperties"
            ],
            False,
        )

        self.assertNotIn(
            "unsupported_keyword",
            branch,
        )

    def test_qwen_schema_has_exactly_three_d2_branches(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        self.assertEqual(
            set(
                schema.keys()
            ),
            {
                "oneOf"
            },
        )

        branches = schema[
            "oneOf"
        ]

        self.assertEqual(
            len(branches),
            3,
        )

        operations = {
            branch[
                "properties"
            ][
                "operation"
            ][
                "const"
            ]
            for branch
            in branches
        }

        self.assertEqual(
            operations,
            {
                "NONE",
                "REMEMBER",
                "RECALL",
            },
        )

        self.assertNotIn(
            "FORGET",
            operations,
        )

        self.assertNotIn(
            "RESOLVE_CONFLICT",
            operations,
        )

    def test_none_branch_has_no_memory_payload_fields(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        branch = next(
            item
            for item
            in schema[
                "oneOf"
            ]
            if (
                item[
                    "properties"
                ][
                    "operation"
                ][
                    "const"
                ]
                == "NONE"
            )
        )

        props = set(
            branch[
                "properties"
            ]
        )

        for forbidden in (
            "entities",
            "facts",
            "relations",
            "query",
        ):
            self.assertNotIn(
                forbidden,
                props,
            )

        self.assertIs(
            branch[
                "additionalProperties"
            ],
            False,
        )

    def test_remember_branch_has_write_fields_but_no_query(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        branch = next(
            item
            for item
            in schema[
                "oneOf"
            ]
            if (
                item[
                    "properties"
                ][
                    "operation"
                ][
                    "const"
                ]
                == "REMEMBER"
            )
        )

        props = set(
            branch[
                "properties"
            ]
        )

        self.assertTrue(
            {
                "entities",
                "facts",
                "relations",
            }
            <= props
        )

        self.assertNotIn(
            "query",
            props,
        )

    def test_recall_branch_has_query_but_no_write_fields(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        branch = next(
            item
            for item
            in schema[
                "oneOf"
            ]
            if (
                item[
                    "properties"
                ][
                    "operation"
                ][
                    "const"
                ]
                == "RECALL"
            )
        )

        props = set(
            branch[
                "properties"
            ]
        )

        self.assertIn(
            "query",
            props,
        )

        for forbidden in (
            "entities",
            "facts",
            "relations",
        ):
            self.assertNotIn(
                forbidden,
                props,
            )

    def test_core_rejects_remember_with_real_query(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "REMEMBER cannot carry query",
        ):
            parse(
                payload(
                    "REMEMBER",
                    facts=[
                        fact()
                    ],
                    query_value=query(),
                )
            )

    def test_core_rejects_recall_with_write_fact(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "RECALL cannot carry write proposals",
        ):
            parse(
                payload(
                    "RECALL",
                    facts=[
                        fact()
                    ],
                    query_value=query(),
                )
            )

    def test_core_accepts_clean_remember(
        self,
    ):
        result = parse(
            payload(
                "REMEMBER",
                facts=[
                    fact()
                ],
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertIsNone(
            result.query,
        )

    def test_core_accepts_clean_recall(
        self,
    ):
        result = parse(
            payload(
                "RECALL",
                query_value=query(),
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.RECALL,
        )

        self.assertEqual(
            tuple(label for item in result.query.fact_properties for label in item.semantic_labels),
            (
                "age",
            ),
        )

    def test_d2_does_not_invent_forget_contract(
        self,
    ):
        result = parse(
            payload(
                "FORGET",
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.FORGET,
        )

    def test_d2_does_not_invent_resolve_conflict_contract(
        self,
    ):
        result = parse(
            payload(
                "RESOLVE_CONFLICT",
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.RESOLVE_CONFLICT,
        )

    def test_schema_contains_no_core_authority_fields(
        self,
    ):
        rendered = json.dumps(
            memory_interpretation_json_schema(),
            sort_keys=True,
        )

        for forbidden in (
            '"authority"',
            '"source_type"',
            '"transaction_id"',
            '"canonical_revision"',
            '"status"',
            '"permissions"',
            '"supersedes_fact_ids"',
        ):
            self.assertNotIn(
                forbidden,
                rendered,
            )


if __name__ == "__main__":
    unittest.main()
