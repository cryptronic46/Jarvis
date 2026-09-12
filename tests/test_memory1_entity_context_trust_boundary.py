from __future__ import annotations

import inspect
import json
import unittest
from datetime import (
    datetime,
    timezone,
)

from jarvis_core.memory import (
    interpreter,
    model_adapter,
)
from jarvis_core.memory.entity_bindings import (
    TrustedEntityBindings,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.qwen_model import (
    memory_interpretation_json_schema,
)



class CaptureMemoryModel:
    def __init__(
        self,
    ) -> None:
        self.context_json = None

    def generate_memory_json(
        self,
        *,
        system_prompt,
        user_text,
        context_json,
    ):
        self.context_json = (
            context_json
        )

        return json.dumps(
            {
                "operation":
                    "NONE",

                "confidence":
                    1.0,

                "explicit_memory_request":
                    False,

                "entities":
                    [],

                "facts":
                    [],

                "relations":
                    [],

                "query":
                    None,

                "needs_confirmation":
                    False,

                "ambiguities":
                    [],
            }
        )


class Memory1EntityContextTrustBoundaryTests(
    unittest.TestCase,
):
    def test_model_context_has_only_safe_entity_refs(
        self,
    ):
        context = (
            interpreter
            .InterpreterContext(
                locale="pt-PT",
                default_subject_ref=(
                    "owner"
                ),
                current_time=datetime(
                    2026,
                    9,
                    8,
                    12,
                    0,
                    tzinfo=timezone.utc,
                ),
                known_entity_refs=(
                    "owner",
                    "person_ref",
                ),
            )
        )

        self.assertEqual(
            context.known_entity_refs,
            (
                "owner",
                "person_ref",
            ),
        )

        self.assertFalse(
            hasattr(
                context,
                "known_entities",
            )
        )

    def test_model_context_rejects_old_mapping_contract(
        self,
    ):
        with self.assertRaises(
            TypeError
        ):
            (
                interpreter
                .InterpreterContext(
                    known_entities={
                        "owner":
                            "private-id"
                    }
                )
            )

    def test_model_context_refs_are_strict_and_unique(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            (
                interpreter
                .InterpreterContext(
                    known_entity_refs=[
                        "owner"
                    ]
                )
            )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                interpreter
                .InterpreterContext(
                    known_entity_refs=(
                        "owner",
                        "owner",
                    )
                )
            )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                interpreter
                .InterpreterContext(
                    known_entity_refs=(
                        " owner ",
                    )
                )
            )

    def test_trusted_entity_bindings_are_private_immutable_mapping(
        self,
    ):
        bindings = (
            TrustedEntityBindings(
                {
                    "owner":
                        "private-canonical-owner",

                    "person_ref":
                        "private-canonical-person",
                }
            )
        )

        self.assertEqual(
            bindings
            .canonical_id_for(
                "owner"
            ),
            "private-canonical-owner",
        )

        self.assertTrue(
            bindings.contains(
                "person_ref"
            )
        )

        self.assertEqual(
            bindings.local_refs(),
            (
                "owner",
                "person_ref",
            ),
        )

        with self.assertRaises(
            TypeError
        ):
            bindings.bindings[
                "other"
            ] = "private-other"

    def test_trusted_adapter_serialization_never_contains_private_ids(
        self,
    ):
        private_id = (
            "private-canonical-owner"
        )

        bindings = (
            TrustedEntityBindings(
                {
                    "owner":
                        private_id,
                }
            )
        )

        context = (
            interpreter
            .InterpreterContext(
                known_entity_refs=(
                    "owner",
                )
            )
        )

        serialized = (
            model_adapter
            ._context_json(
                context
            )
        )

        payload = json.loads(
            serialized
        )

        self.assertEqual(
            payload[
                "known_entity_refs"
            ],
            [
                "owner"
            ],
        )

        self.assertNotIn(
            "known_entities",
            payload,
        )

        self.assertEqual(
            payload[
                "model_context_contract_version"
            ],
            (
                interpreter
                .MEMORY_MODEL_CONTEXT_CONTRACT_VERSION
            ),
        )

        self.assertNotIn(
            private_id,
            serialized,
        )

        self.assertEqual(
            bindings
            .canonical_id_for(
                "owner"
            ),
            private_id,
        )

    def test_direct_interpreter_serialization_never_contains_private_ids(
        self,
    ):
        private_id = (
            "private-canonical-owner"
        )

        bindings = (
            TrustedEntityBindings(
                {
                    "owner":
                        private_id,
                }
            )
        )

        model = (
            CaptureMemoryModel()
        )

        memory_interpreter = (
            interpreter
            .SemanticMemoryInterpreter(
                model
            )
        )

        result = (
            memory_interpreter
            .interpret(
                "hello",
                context=(
                    interpreter
                    .InterpreterContext(
                        known_entity_refs=(
                            "owner",
                        )
                    )
                ),
            )
        )

        self.assertEqual(
            result.operation.value,
            "NONE",
        )

        self.assertIsNotNone(
            model.context_json
        )

        payload = json.loads(
            model.context_json
        )

        self.assertEqual(
            payload[
                "known_entity_refs"
            ],
            [
                "owner"
            ],
        )

        self.assertNotIn(
            "known_entities",
            payload,
        )

        self.assertNotIn(
            private_id,
            model.context_json,
        )

        self.assertEqual(
            bindings
            .canonical_id_for(
                "owner"
            ),
            private_id,
        )

    def test_model_context_has_independent_contract_version(
        self,
    ):
        self.assertEqual(
            (
                interpreter
                .MEMORY_MODEL_CONTEXT_CONTRACT_VERSION
            ),
            "1.0",
        )

        self.assertEqual(
            (
                model_adapter
                .MEMORY_INTERPRETER_SCHEMA_VERSION
            ),
            4,
        )

        self.assertEqual(
            (
                model_adapter
                .MEMORY_INTERPRETER_CONTRACT_VERSION
            ),
            "1.0",
        )

        self.assertEqual(
            (
                model_adapter
                .MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION
            ),
            "1.0",
        )

    def test_trusted_prompts_declare_model_context_contract(
        self,
    ):
        marker = (
            "model_context_contract_version="
            + (
                interpreter
                .MEMORY_MODEL_CONTEXT_CONTRACT_VERSION
            )
        )

        prompts = (
            (
                model_adapter
                .trusted_memory_interpreter_system_prompt()
            ),
            (
                model_adapter
                .trusted_memory_remember_extractor_system_prompt()
            ),
            (
                model_adapter
                .trusted_memory_recall_extractor_system_prompt()
            ),
        )

        for prompt in prompts:
            self.assertIn(
                marker,
                prompt,
            )

    def test_proposal_json_schema_does_not_gain_context_fields(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        serialized = json.dumps(
            schema,
            sort_keys=True,
        )

        self.assertNotIn(
            "known_entities",
            serialized,
        )

        self.assertNotIn(
            "known_entity_refs",
            serialized,
        )

        self.assertNotIn(
            "model_context_contract_version",
            serialized,
        )

    def test_private_binding_type_is_not_imported_by_model_layers(
        self,
    ):
        interpreter_source = (
            inspect.getsource(
                interpreter
            )
        )

        adapter_source = (
            inspect.getsource(
                model_adapter
            )
        )

        self.assertNotIn(
            "TrustedEntityBindings",
            interpreter_source,
        )

        self.assertNotIn(
            "TrustedEntityBindings",
            adapter_source,
        )

        self.assertNotIn(
            "entity_bindings",
            interpreter_source,
        )

        self.assertNotIn(
            "entity_bindings",
            adapter_source,
        )


if __name__ == "__main__":
    unittest.main()
