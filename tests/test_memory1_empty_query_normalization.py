from __future__ import annotations

from pathlib import Path
import ast
import json
import unittest

from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.interpreter import (
    MemoryOperation,
    QueryTemporalMode,
    parse_memory_interpretation,
)



def payload(
    operation: str,
    *,
    explicit: bool,
    query_marker="__OMITTED__",
    facts=None,
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
            explicit,

        "entities":
            [],

        "fact_properties":
            (
                [
                    age_property()
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
        query_marker
        != "__OMITTED__"
    ):
        row[
            "query"
        ] = query_marker

    return row




def age_property():
    return {
        "local_ref":
            "age_property",

        "semantic_labels": [
            "age",
        ],

        "semantic_type":
            "age",

        "cardinality":
            "SINGLE_CURRENT",

        "value_type":
            "INTEGER",
    }


def age_fact():
    return {
        "subject_ref":
            "owner",

        "property_ref":
            "age_property",

        "value":
            38,

        "memory_class":
            "FACTUAL",

        "confidence":
            0.99,
    }



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


class Memory1EmptyQueryNormalizationTests(
    unittest.TestCase
):
    def test_none_with_empty_query_object_normalizes_to_none(
        self,
    ):
        result = parse(
            payload(
                "NONE",
                explicit=False,
                query_marker={},
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.NONE,
        )

        self.assertIsNone(
            result.query
        )

    def test_none_with_empty_predicates_normalizes_to_none(
        self,
    ):
        result = parse(
            payload(
                "NONE",
                explicit=False,
                query_marker={'fact_properties': []},
            )
        )

        self.assertIsNone(
            result.query
        )

    def test_none_with_all_empty_lists_and_current_normalizes(
        self,
    ):
        result = parse(
            payload(
                "NONE",
                explicit=False,
                query_marker={'subject_refs': [], 'fact_properties': [], 'relation_properties': [], 'target_refs': [], 'temporal_mode': 'CURRENT'},
            )
        )

        self.assertIsNone(
            result.query
        )

    def test_remember_with_real_fact_and_empty_query_normalizes(
        self,
    ):
        result = parse(
            payload(
                "REMEMBER",
                explicit=True,
                query_marker={'fact_properties': []},
                facts=[
                    age_fact()
                ],
            )
        )

        self.assertIs(
            result.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            len(
                result.facts
            ),
            1,
        )

        self.assertIsNone(
            result.query
        )

    def test_recall_empty_query_object_fails_after_normalization(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "RECALL requires query",
        ):
            parse(
                payload(
                    "RECALL",
                    explicit=True,
                    query_marker={},
                )
            )

    def test_recall_empty_predicates_fails_after_normalization(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "RECALL requires query",
        ):
            parse(
                payload(
                    "RECALL",
                    explicit=True,
                    query_marker={'fact_properties': []},
                )
            )

    def test_recall_current_only_fails_after_normalization(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "RECALL requires query",
        ):
            parse(
                payload(
                    "RECALL",
                    explicit=True,
                    query_marker={
                        "temporal_mode":
                            "CURRENT",
                    },
                )
            )

    def test_real_subject_query_is_not_normalized(
        self,
    ):
        result = parse(
            payload(
                "RECALL",
                explicit=True,
                query_marker={
                    "subject_refs":
                        [
                            "owner"
                        ],
                },
            )
        )

        self.assertIsNotNone(
            result.query
        )

        self.assertEqual(
            result.query.subject_refs,
            (
                "owner",
            ),
        )

    def test_real_predicate_query_is_not_normalized(
        self,
    ):
        result = parse(
            payload(
                "RECALL",
                explicit=True,
                query_marker={'fact_properties': [{'semantic_labels': ['age'], 'semantic_type': 'property'}]},
            )
        )

        self.assertEqual(
            tuple(label for item in result.query.fact_properties for label in item.semantic_labels),
            (
                "age",
            ),
        )

    def test_historical_mode_is_not_normalized(
        self,
    ):
        result = parse(
            payload(
                "RECALL",
                explicit=True,
                query_marker={
                    "temporal_mode":
                        "HISTORICAL",
                },
            )
        )

        self.assertIs(
            result
            .query
            .temporal_mode,
            QueryTemporalMode.HISTORICAL,
        )

    def test_as_of_revision_is_not_normalized(
        self,
    ):
        result = parse(
            payload(
                "RECALL",
                explicit=True,
                query_marker={
                    "temporal_mode":
                        "AS_OF_REVISION",

                    "as_of_revision":
                        3,
                },
            )
        )

        self.assertEqual(
            result
            .query
            .as_of_revision,
            3,
        )

    def test_none_with_real_query_still_fails_closed(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "NONE cannot carry memory proposals",
        ):
            parse(
                payload(
                    "NONE",
                    explicit=False,
                    query_marker={'fact_properties': [{'semantic_labels': ['age'], 'semantic_type': 'property'}]},
                )
            )

    def test_unknown_query_key_is_not_normalized_away(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            parse(
                payload(
                    "NONE",
                    explicit=False,
                    query_marker={
                        "unknown":
                            [],
                    },
                )
            )

    def test_malformed_empty_candidate_is_not_normalized_away(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            parse(
                payload(
                    "NONE",
                    explicit=False,
                    query_marker={'fact_properties': ''},
                )
            )

    def test_non_object_query_is_not_normalized_away(
        self,
    ):
        with self.assertRaisesRegex(
            MemoryValidationError,
            "query must be an object",
        ):
            parse(
                payload(
                    "NONE",
                    explicit=False,
                    query_marker=[],
                )
            )

    def test_structural_normalizer_has_no_language_regex(
        self,
    ):
        source = Path(
            "jarvis_core/memory/interpreter.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source
        )

        imports = set()

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imports.update(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                if node.module:
                    imports.add(
                        node.module
                    )

        self.assertNotIn(
            "re",
            imports,
        )

        self.assertNotIn(
            "regex",
            imports,
        )

    def test_structural_normalizer_has_no_canonical_write_dependency(
        self,
    ):
        source = Path(
            "jarvis_core/memory/interpreter.py"
        ).read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "CanonicalMemoryStore",
            "CanonicalMemoryTransaction",
            "begin_transaction",
            "MemoryCommitReceipt",
            "commit_memory",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )


if __name__ == "__main__":
    unittest.main()
