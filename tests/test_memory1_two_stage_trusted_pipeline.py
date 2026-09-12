from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import tempfile
import unittest

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)

from jarvis_core.memory.interpreter import (
    InterpreterContext,
    MemoryOperation,
)

from jarvis_core.memory.model_adapter import (
    MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION,
    MemoryInterpretationStageReceipt,
    TrustedTwoStageSemanticMemoryAdapter,
    TwoStageMemoryInterpretationEnvelope,
    memory_operation_selection_json_schema,
    memory_recall_extraction_json_schema,
    memory_remember_extraction_json_schema,
)

from jarvis_core.memory.qwen_model import (
    JarvisQwenMemoryModel,
)


class FakeTwoStageModel:
    def __init__(
        self,
        outputs,
    ):
        self.outputs = list(
            outputs
        )

        self.calls = []

    def generate_constrained_json(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        if not self.outputs:
            raise RuntimeError(
                "no fake output"
            )

        item = self.outputs.pop(
            0
        )

        if isinstance(
            item,
            Exception,
        ):
            raise item

        return item


class FakeLocalClient:
    def __init__(
        self,
        output,
    ):
        self.output = output
        self.calls = []

    def chat(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return SimpleNamespace(
            message=SimpleNamespace(
                content=self.output,
                tool_calls=[],
            )
        )


def operation_output(
    operation,
    confidence,
):
    return json.dumps(
        {
            "operation":
                operation,

            "confidence":
                confidence,
        }
    )



def remember_output():
    return json.dumps(
        {
            "entities":
                [],

            "fact_properties": [
                {
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
            ],

            "relation_properties":
                [],

            "facts": [
                {
                    "subject_ref":
                        "owner",

                    "property_ref":
                        "age_property",

                    "value":
                        38,

                    "memory_class":
                        "FACTUAL",

                    "confidence":
                        0.87,
                }
            ],

            "relations":
                [],
        }
    )



def recall_output():
    return json.dumps(
        {
            "query": {
                "subject_refs": ["owner"],
                "fact_properties": [
                    {
                        "semantic_labels": ["age"],
                        "semantic_type": "property",
                    },
                ],
                "retrieval_scope": "SELECTOR_SCOPED",
            },
        }
    )


class Memory1TwoStageTrustedPipelineTests(
    unittest.TestCase
):
    @staticmethod
    def fixed_time():
        return datetime(
            2026,
            9,
            8,
            18,
            0,
            tzinfo=timezone.utc,
        )

    def build_adapter(
        self,
        outputs,
    ):
        model = FakeTwoStageModel(
            outputs
        )

        adapter = (
            TrustedTwoStageSemanticMemoryAdapter(
                model,
                model_id="qwen3:14b",
                clock=self.fixed_time,
            )
        )

        return (
            model,
            adapter,
        )

    def test_none_requires_exactly_one_model_call(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "NONE",
                        0.99,
                    )
                ]
            )
        )

        envelope = adapter.interpret(
            "ordinary turn"
        )

        self.assertEqual(
            len(
                model.calls
            ),
            1,
        )

        self.assertIs(
            envelope.interpretation.operation,
            MemoryOperation.NONE,
        )

        self.assertEqual(
            envelope.interpretation.confidence,
            0.99,
        )

        self.assertIsNone(
            envelope.extraction_stage
        )


    def test_remember_requires_two_distinct_model_calls(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "REMEMBER",
                        0.96,
                    ),

                    remember_output(),
                ]
            )
        )

        envelope = adapter.interpret(
            "arbitrary persistence request"
        )

        self.assertEqual(
            len(
                model.calls
            ),
            2,
        )

        self.assertIs(
            envelope.interpretation.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            envelope.interpretation.confidence,
            0.96,
        )

        self.assertEqual(
            envelope.interpretation
            .facts[0]
            .confidence,
            0.87,
        )

        self.assertEqual(
            len(
                envelope.interpretation
                .fact_properties
            ),
            1,
        )

        property_proposal = (
            envelope.interpretation
            .fact_properties[0]
        )

        fact = (
            envelope.interpretation
            .facts[0]
        )

        self.assertEqual(
            property_proposal.local_ref,
            "age_property",
        )

        self.assertEqual(
            property_proposal.semantic_labels,
            (
                "age",
            ),
        )

        self.assertEqual(
            property_proposal.semantic_type,
            "age",
        )

        self.assertEqual(
            property_proposal
            .cardinality
            .value,
            "SINGLE_CURRENT",
        )

        self.assertEqual(
            property_proposal
            .value_type
            .value,
            "INTEGER",
        )

        self.assertEqual(
            fact.property_ref,
            property_proposal.local_ref,
        )

        self.assertEqual(
            envelope.extraction_stage.stage,
            "remember_extraction",
        )


    def test_recall_requires_two_distinct_model_calls(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "RECALL",
                        0.94,
                    ),

                    recall_output(),
                ]
            )
        )

        envelope = adapter.interpret(
            "arbitrary recall request"
        )

        self.assertEqual(
            len(
                model.calls
            ),
            2,
        )

        self.assertIs(
            envelope.interpretation.operation,
            MemoryOperation.RECALL,
        )

        self.assertEqual(
            envelope.interpretation.confidence,
            0.94,
        )

        self.assertEqual(
            tuple(label for item in envelope.interpretation
            .query.fact_properties for label in item.semantic_labels),
            (
                "age",
            ),
        )

        self.assertEqual(
            envelope.extraction_stage.stage,
            "recall_extraction",
        )

    def test_final_confidence_belongs_only_to_operation_stage(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "REMEMBER",
                        0.91,
                    ),

                    remember_output(),
                ]
            )
        )

        envelope = adapter.interpret(
            "text"
        )

        self.assertEqual(
            envelope.interpretation.confidence,
            0.91,
        )

        self.assertEqual(
            envelope.operation_stage
            .operation_confidence,
            0.91,
        )

        self.assertIsNone(
            envelope.extraction_stage
            .operation_confidence
        )

    def test_stage_receipts_hash_exact_prompts_schemas_and_outputs(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "RECALL",
                        0.88,
                    ),

                    recall_output(),
                ]
            )
        )

        envelope = adapter.interpret(
            "text"
        )

        first = model.calls[0]
        second = model.calls[1]

        for call, receipt in (
            (
                first,
                envelope.operation_stage,
            ),
            (
                second,
                envelope.extraction_stage,
            ),
        ):
            self.assertEqual(
                receipt.system_prompt_sha256,
                hashlib.sha256(
                    call[
                        "system_prompt"
                    ].encode(
                        "utf-8"
                    )
                ).hexdigest(),
            )

            schema_json = json.dumps(
                call[
                    "schema"
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )

            self.assertEqual(
                receipt.schema_sha256,
                hashlib.sha256(
                    schema_json.encode(
                        "utf-8"
                    )
                ).hexdigest(),
            )

    def test_envelope_stores_no_raw_user_or_model_text(
        self,
    ):
        names = {
            field.name
            for field
            in fields(
                TwoStageMemoryInterpretationEnvelope
            )
        }

        self.assertNotIn(
            "user_text",
            names,
        )

        self.assertNotIn(
            "raw_output",
            names,
        )

        stage_names = {
            field.name
            for field
            in fields(
                MemoryInterpretationStageReceipt
            )
        }

        self.assertNotIn(
            "raw_output",
            stage_names,
        )

    def test_stage2_cannot_reclassify_operation(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "REMEMBER",
                        0.9,
                    ),

                    json.dumps(
                        {
                            "operation":
                                "NONE",

                            "entities":
                                [],

                            "facts":
                                [],

                            "relations":
                                [],
                        }
                    ),
                ]
            )
        )

        with self.assertRaises(
            Exception
        ):
            adapter.interpret(
                "text"
            )

    def test_unsupported_operation_fails_closed(
        self,
    ):
        model, adapter = (
            self.build_adapter(
                [
                    operation_output(
                        "FORGET",
                        0.9,
                    )
                ]
            )
        )

        with self.assertRaises(
            Exception
        ):
            adapter.interpret(
                "text"
            )

        self.assertEqual(
            len(
                model.calls
            ),
            1,
        )

    def test_two_stage_contract_has_no_forget_or_conflict_branch(
        self,
    ):
        schema = (
            memory_operation_selection_json_schema()
        )

        operations = schema[
            "properties"
        ][
            "operation"
        ][
            "enum"
        ]

        self.assertEqual(
            operations,
            [
                "NONE",
                "REMEMBER",
                "RECALL",
            ],
        )

    def test_stage2_schemas_have_no_operation_field(
        self,
    ):
        for schema in (
            memory_remember_extraction_json_schema(),
            memory_recall_extraction_json_schema(),
        ):
            self.assertNotIn(
                "operation",
                schema[
                    "properties"
                ],
            )


    def test_entity_ref_property_contract_is_structural(
        self,
    ):
        schema = (
            memory_remember_extraction_json_schema()
        )

        fact_property = (
            schema[
                "properties"
            ][
                "fact_properties"
            ][
                "items"
            ]
        )

        self.assertIn(
            "ENTITY_REF",
            fact_property[
                "properties"
            ][
                "value_type"
            ][
                "enum"
            ],
        )

        fact_schema = (
            schema[
                "properties"
            ][
                "facts"
            ][
                "items"
            ]
        )

        self.assertIn(
            "value_entity_ref",
            fact_schema[
                "properties"
            ],
        )

        self.assertNotIn(
            "value_entity_ref",
            fact_schema[
                "required"
            ],
        )


    def test_execution_contract_version_is_explicit(
        self,
    ):
        self.assertEqual(
            MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION,
            "1.0",
        )

    def test_interpretation_remains_read_only(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            store = CanonicalMemoryStore(
                Path(
                    tmp
                )
                / "memory.sqlite3"
            )

            before = (
                store.canonical_revision()
            )

            model, adapter = (
                self.build_adapter(
                    [
                        operation_output(
                            "REMEMBER",
                            0.93,
                        ),

                        remember_output(),
                    ]
                )
            )

            adapter.interpret(
                "text"
            )

            after = (
                store.canonical_revision()
            )

            self.assertEqual(
                before,
                0,
            )

            self.assertEqual(
                after,
                before,
            )

    def test_qwen_generic_constrained_call_uses_supplied_schema(
        self,
    ):
        output = json.dumps(
            {
                "operation":
                    "NONE",

                "confidence":
                    0.9,
            }
        )

        client = FakeLocalClient(
            output
        )

        model = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
            keep_alive="5m",
        )

        schema = (
            memory_operation_selection_json_schema()
        )

        result = (
            model.generate_constrained_json(
                system_prompt="system",
                user_text="text",
                context_json="{}",
                schema=schema,
                num_predict=64,
            )
        )

        self.assertEqual(
            result,
            output,
        )

        self.assertEqual(
            len(
                client.calls
            ),
            1,
        )

        call = client.calls[0]

        self.assertEqual(
            call[
                "format"
            ],
            schema,
        )

        self.assertEqual(
            call[
                "options"
            ][
                "num_predict"
            ],
            64,
        )

        self.assertEqual(
            call[
                "options"
            ][
                "temperature"
            ],
            0.0,
        )

        self.assertIsNone(
            call[
                "tools"
            ],
        )

        self.assertFalse(
            call[
                "think"
            ],
        )

        self.assertFalse(
            call[
                "stream"
            ],
        )

    def test_production_two_stage_sources_have_no_case_specific_rules(
        self,
    ):
        source = Path(
            "jarvis_core/memory/model_adapter.py"
        ).read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "Spotify",
            "azul",
            "38 anos",
            "Marta",
            "cor preferida",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )

    def test_two_stage_pipeline_has_no_canonical_write_dependency(
        self,
    ):
        source = Path(
            "jarvis_core/memory/model_adapter.py"
        ).read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "CanonicalMemoryStore",
            "CanonicalMemoryTransaction",
            "MemoryCommitReceipt",
            "begin_transaction",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )


if __name__ == "__main__":
    unittest.main()
