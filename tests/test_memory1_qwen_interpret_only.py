from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import tempfile
import unittest

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    InterpreterContext,
    MemoryOperation,
)
from jarvis_core.memory.model_adapter import (
    MemoryModelInvocationError,
    TrustedSemanticMemoryAdapter,
)
from jarvis_core.memory.qwen_model import (
    DEFAULT_MEMORY_INTERPRETER_NUM_CTX,
    DEFAULT_MEMORY_INTERPRETER_NUM_PREDICT,
    JarvisQwenMemoryModel,
    QwenMemoryModelError,
    memory_interpretation_json_schema,
)



def valid_output(
) -> str:
    return json.dumps(
        {
            "operation":
                "REMEMBER",

            "confidence":
                0.99,

            "explicit_memory_request":
                True,

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
                        "TEMPORAL_SINGLE",

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
        ensure_ascii=False,
    )



class FakeLocalClient:
    def __init__(
        self,
        *,
        output: str | None = None,
        error: Exception | None = None,
        message: object | None = None,
    ) -> None:
        self.output = (
            valid_output()
            if output is None
            else output
        )

        self.error = error
        self.message = message

        self.calls: list[
            dict
        ] = []

    def chat(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        if (
            self.error
            is not None
        ):
            raise self.error

        if (
            self.message
            is not None
        ):
            return SimpleNamespace(
                message=self.message
            )

        return SimpleNamespace(
            message=SimpleNamespace(
                role="assistant",
                content=self.output,
                thinking="",
                tool_calls=[],
            ),
            done_reason="stop",
            eval_count=12,
            model="jarvis-local",
        )


class Memory1QwenInterpretOnlyTests(
    unittest.TestCase
):

    @staticmethod
    def fixed_time(
    ):
        return datetime(
            2026,
            9,
            8,
            17,
            0,
            tzinfo=timezone.utc,
        )

    def build_adapter(
        self,
        client,
    ):
        qwen = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
            keep_alive="5m",
        )

        return TrustedSemanticMemoryAdapter(
            qwen,
            model_id="qwen3:14b",
            clock=self.fixed_time,
        )

    def test_uses_injected_local_client_only(
        self,
    ):
        client = FakeLocalClient()

        adapter = self.build_adapter(
            client
        )

        envelope = adapter.interpret(
            "Guarda que tenho 38 anos.",
            context=(
                InterpreterContext(
                    locale="pt-PT",
                    default_subject_ref=(
                        "owner"
                    ),
                )
            ),
        )

        self.assertEqual(
            envelope
            .interpretation
            .operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            len(
                client.calls
            ),
            1,
        )

    def test_chat_call_is_isolated_deterministic_and_tool_free(
        self,
    ):
        client = FakeLocalClient()

        adapter = self.build_adapter(
            client
        )

        adapter.interpret(
            "Guarda que tenho 38 anos."
        )

        call = client.calls[0]

        self.assertEqual(
            call[
                "model"
            ],
            "qwen3:14b",
        )

        self.assertFalse(
            call[
                "think"
            ]
        )

        self.assertIsNone(
            call[
                "tools"
            ]
        )

        self.assertFalse(
            call[
                "stream"
            ]
        )

        self.assertEqual(
            call[
                "keep_alive"
            ],
            "5m",
        )

        self.assertEqual(
            call[
                "options"
            ],
            {
                "num_ctx":
                    DEFAULT_MEMORY_INTERPRETER_NUM_CTX,

                "num_predict":
                    DEFAULT_MEMORY_INTERPRETER_NUM_PREDICT,

                "temperature":
                    0.0,
            },
        )

        self.assertIsInstance(
            call[
                "format"
            ],
            dict,
        )

    def test_exactly_system_and_current_user_payload_are_sent(
        self,
    ):
        client = FakeLocalClient()

        adapter = self.build_adapter(
            client
        )

        adapter.interpret(
            "texto atual",

            context=(
                InterpreterContext(
                    locale="pt-PT",

                    default_subject_ref=(
                        "owner"
                    ),

                    known_entity_refs=('owner',),
                )
            ),
        )

        messages = (
            client.calls[0][
                "messages"
            ]
        )

        self.assertEqual(
            len(
                messages
            ),
            2,
        )

        self.assertEqual(
            messages[0][
                "role"
            ],
            "system",
        )

        self.assertEqual(
            messages[1][
                "role"
            ],
            "user",
        )

        payload = json.loads(
            messages[1][
                "content"
            ]
        )

        self.assertEqual(
            payload[
                "user_text"
            ],
            "texto atual",
        )

        self.assertEqual(
            payload[
                "context"
            ][
                "default_subject_ref"
            ],
            "owner",
        )

        self.assertEqual(
            payload[
                "context"
            ][
                'known_entity_refs'
            ],
            ['owner'],
        )

    def test_schema_contains_semantic_fields_but_no_core_authority_fields(
        self,
    ):
        schema = (
            memory_interpretation_json_schema()
        )

        rendered = json.dumps(
            schema,
            sort_keys=True,
        )

        for required in (
            '"operation"',
            '"facts"',
            '"relations"',
            '"query"',
            '"memory_class"',
            '"cardinality"',
        ):
            self.assertIn(
                required,
                rendered,
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

    def test_schema_factory_returns_fresh_structure(
        self,
    ):
        first = (
            memory_interpretation_json_schema()
        )

        second = (
            memory_interpretation_json_schema()
        )

        self.assertIsNot(
            first,
            second,
        )

        self.assertIsNot(
            first[
                "oneOf"
            ],
            second[
                "oneOf"
            ],
        )

        first[
            "oneOf"
        ][
            0
        ][
            "required"
        ].append(
            "tampered"
        )

        self.assertNotIn(
            "tampered",
            second[
                "oneOf"
            ][
                0
            ][
                "required"
            ],
        )

    def test_canonical_revision_does_not_change_during_interpretation(
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

            client = FakeLocalClient()

            adapter = self.build_adapter(
                client
            )

            envelope = adapter.interpret(
                "Guarda que tenho 38 anos."
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

            self.assertEqual(
                envelope
                .interpretation
                .operation,
                MemoryOperation.REMEMBER,
            )

    def test_invalid_trusted_context_fails_before_local_model_call(
        self,
    ):
        client = FakeLocalClient()

        model = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
        )

        with self.assertRaises(
            QwenMemoryModelError
        ):
            model.generate_memory_json(
                system_prompt="system",
                user_text="text",
                context_json="{bad",
            )

        self.assertEqual(
            client.calls,
            [],
        )

    def test_non_object_trusted_context_fails_before_local_model_call(
        self,
    ):
        client = FakeLocalClient()

        model = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
        )

        with self.assertRaises(
            QwenMemoryModelError
        ):
            model.generate_memory_json(
                system_prompt="system",
                user_text="text",
                context_json="[]",
            )

        self.assertEqual(
            client.calls,
            [],
        )

    def test_local_client_failure_is_wrapped_fail_closed(
        self,
    ):
        client = FakeLocalClient(
            error=RuntimeError(
                "runtime unavailable"
            )
        )

        adapter = self.build_adapter(
            client
        )

        with self.assertRaises(
            MemoryModelInvocationError
        ):
            adapter.interpret(
                "texto"
            )

    def test_missing_assistant_message_fails_closed(
        self,
    ):
        class MissingMessageClient:
            def chat(
                self,
                **kwargs,
            ):
                return SimpleNamespace(
                    message=None
                )

        model = JarvisQwenMemoryModel(
            MissingMessageClient(),
            model="qwen3:14b",
        )

        with self.assertRaises(
            QwenMemoryModelError
        ):
            model.generate_memory_json(
                system_prompt="system",
                user_text="text",
                context_json="{}",
            )

    def test_unexpected_tool_call_fails_closed(
        self,
    ):
        client = FakeLocalClient(
            message=SimpleNamespace(
                content=(
                    valid_output()
                ),

                tool_calls=[
                    object()
                ],
            )
        )

        model = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
        )

        with self.assertRaises(
            QwenMemoryModelError
        ):
            model.generate_memory_json(
                system_prompt="system",
                user_text="text",
                context_json="{}",
            )

    def test_empty_content_fails_closed(
        self,
    ):
        client = FakeLocalClient(
            output="   "
        )

        model = JarvisQwenMemoryModel(
            client,
            model="qwen3:14b",
        )

        with self.assertRaises(
            QwenMemoryModelError
        ):
            model.generate_memory_json(
                system_prompt="system",
                user_text="text",
                context_json="{}",
            )

    def test_qwen_adapter_does_not_construct_runtime_or_brain(
        self,
    ):
        source = Path(
            "jarvis_core/memory/qwen_model.py"
        ).read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "build_local_client",
            "NativeLlamaRuntime",
            "NativeLlamaClient",
            "OllamaLocalCompatClient",
            "JarvisBrain",
            "CanonicalMemoryStore",
            "CanonicalMemoryTransaction",
            "begin_transaction",
            "MemoryCommitReceipt",
            "personal_cognition",
            "context_store",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )

    def test_qwen_adapter_has_no_regex_language_parser(
        self,
    ):
        tree = ast.parse(
            Path(
                "jarvis_core/memory/qwen_model.py"
            ).read_text(
                encoding="utf-8"
            )
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

    def test_model_client_requires_chat_contract(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            JarvisQwenMemoryModel(
                object(),
                model="qwen3:14b",
            )

    def test_num_ctx_rejects_float_coercion(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            JarvisQwenMemoryModel(
                FakeLocalClient(),
                model="qwen3:14b",
                num_ctx=4096.5,
            )

    def test_num_predict_rejects_string_coercion(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            JarvisQwenMemoryModel(
                FakeLocalClient(),
                model="qwen3:14b",
                num_predict="768",
            )

    def test_token_budgets_reject_bool(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            JarvisQwenMemoryModel(
                FakeLocalClient(),
                model="qwen3:14b",
                num_ctx=True,
            )


if __name__ == "__main__":
    unittest.main()
