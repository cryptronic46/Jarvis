from __future__ import annotations

import json
import unittest


from jarvis_core.memory.interpreter import (
    InterpreterContext,
    MemoryOperation,
)

from jarvis_core.memory.model_adapter import (
    MemoryModelContractError,
    MemoryModelInvocationError,
    TrustedTwoStageSemanticMemoryAdapter,
)

from jarvis_core.memory.qwen_model import (
    JarvisQwenMemoryModel,
    QwenMemoryModelError,
    QwenMemoryModelMalformedOutputError,
)


OPERATION_JSON = json.dumps(
    {
        "operation": "REMEMBER",
        "confidence": 1.0,
    }
)


VALID_REMEMBER_JSON = json.dumps(
    {
        "entities": [],
        "fact_properties": [
            {
                "local_ref": "memory_test_code",
                "semantic_labels": [
                    "memory_test_code",
                ],
                "semantic_type": "string",
                "cardinality": "SINGLE_CURRENT",
                "value_type": "STRING",
            }
        ],
        "relation_properties": [],
        "facts": [
            {
                "subject_ref": "owner",
                "property_ref": "memory_test_code",
                "value": "ORBITA-7391",
                "memory_class": "FACTUAL",
                "confidence": 1.0,
            }
        ],
        "relations": [],
    }
)


class FakeMessage:
    def __init__(
        self,
        *,
        content="{}",
        tool_calls=None,
    ):
        self.content = content
        self.tool_calls = tool_calls


class FakeResponse:
    def __init__(
        self,
        message,
    ):
        self.message = message


class FakeClient:
    def __init__(
        self,
        *,
        response=None,
        error=None,
    ):
        self.response = response
        self.error = error
        self.calls = 0

    def chat(
        self,
        **kwargs,
    ):
        self.calls += 1

        if self.error is not None:
            raise self.error

        return self.response


class SequenceMemoryModel:
    def __init__(
        self,
        outputs,
    ):
        self.outputs = list(
            outputs
        )
        self.calls = 0

    def generate_constrained_json(
        self,
        **kwargs,
    ):
        if self.calls >= len(
            self.outputs
        ):
            raise AssertionError(
                "unexpected extra generation call"
            )

        item = self.outputs[
            self.calls
        ]

        self.calls += 1

        if isinstance(
            item,
            BaseException,
        ):
            raise item

        return item


def qwen_call(
    response,
):
    client = FakeClient(
        response=response,
    )

    model = JarvisQwenMemoryModel(
        client,
        model="qwen-test",
    )

    return (
        client,
        model,
    )


def invoke_qwen(
    model,
    *,
    context_json="{}",
):
    return model.generate_constrained_json(
        system_prompt="system",
        user_text="user",
        context_json=context_json,
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        num_predict=64,
    )


def make_adapter(
    outputs,
):
    model = SequenceMemoryModel(
        outputs
    )

    adapter = TrustedTwoStageSemanticMemoryAdapter(
        model,
        model_id="qwen-test",
    )

    return (
        model,
        adapter,
    )


def interpret_remember(
    adapter,
):
    return adapter.interpret(
        (
            "Lembra-te de que o meu código "
            "de teste da memória é ORBITA-7391."
        ),
        context=InterpreterContext(
            known_entity_refs=(
                "owner",
            ),
            default_subject_ref="owner",
            locale="pt-PT",
        ),
    )


class QwenMalformedOutputClassificationTests(
    unittest.TestCase
):
    def test_missing_assistant_message_is_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                None
            )
        )

        with self.assertRaises(
            QwenMemoryModelMalformedOutputError
        ):
            invoke_qwen(
                model
            )

        self.assertEqual(
            client.calls,
            1,
        )

    def test_unexpected_tool_calls_are_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                FakeMessage(
                    content="{}",
                    tool_calls=[
                        object(),
                    ],
                )
            )
        )

        with self.assertRaises(
            QwenMemoryModelMalformedOutputError
        ):
            invoke_qwen(
                model
            )

        self.assertEqual(
            client.calls,
            1,
        )

    def test_non_text_content_is_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                FakeMessage(
                    content=123,
                )
            )
        )

        with self.assertRaises(
            QwenMemoryModelMalformedOutputError
        ):
            invoke_qwen(
                model
            )

        self.assertEqual(
            client.calls,
            1,
        )

    def test_empty_content_is_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                FakeMessage(
                    content="   ",
                )
            )
        )

        with self.assertRaises(
            QwenMemoryModelMalformedOutputError
        ):
            invoke_qwen(
                model
            )

        self.assertEqual(
            client.calls,
            1,
        )

    def test_invalid_generated_json_is_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                FakeMessage(
                    content="{not-valid-json",
                )
            )
        )

        with self.assertRaises(
            QwenMemoryModelMalformedOutputError
        ):
            invoke_qwen(
                model
            )

        self.assertEqual(
            client.calls,
            1,
        )

    def test_invalid_trusted_context_is_not_generation_malformed_output(
        self,
    ):
        client, model = qwen_call(
            FakeResponse(
                FakeMessage(
                    content="{}",
                )
            )
        )

        with self.assertRaises(
            QwenMemoryModelError
        ) as captured:
            invoke_qwen(
                model,
                context_json="{not-valid-context",
            )

        self.assertNotIsInstance(
            captured.exception,
            QwenMemoryModelMalformedOutputError,
        )

        self.assertEqual(
            client.calls,
            0,
        )


class RememberGenerationRetryPolicyTests(
    unittest.TestCase
):
    def test_malformed_generation_output_is_retried_once(
        self,
    ):
        model, adapter = make_adapter(
            [
                OPERATION_JSON,
                QwenMemoryModelMalformedOutputError(
                    "malformed generation"
                ),
                VALID_REMEMBER_JSON,
            ]
        )

        envelope = interpret_remember(
            adapter
        )

        self.assertEqual(
            model.calls,
            3,
        )

        self.assertIs(
            envelope.interpretation.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            envelope.interpretation.facts[0].value,
            "ORBITA-7391",
        )

    def test_second_malformed_generation_failure_is_not_retried_again(
        self,
    ):
        model, adapter = make_adapter(
            [
                OPERATION_JSON,
                QwenMemoryModelMalformedOutputError(
                    "first malformed generation"
                ),
                QwenMemoryModelMalformedOutputError(
                    "second malformed generation"
                ),
            ]
        )

        with self.assertRaises(
            MemoryModelContractError
        ) as captured:
            interpret_remember(
                adapter
            )

        self.assertEqual(
            model.calls,
            3,
        )

        self.assertIs(
            captured.exception.selected_operation,
            MemoryOperation.REMEMBER,
        )

        self.assertIsInstance(
            captured.exception.__cause__,
            QwenMemoryModelMalformedOutputError,
        )

    def test_invocation_error_is_never_retried(
        self,
    ):
        model, adapter = make_adapter(
            [
                OPERATION_JSON,
                QwenMemoryModelError(
                    "invocation failed"
                ),
            ]
        )

        with self.assertRaises(
            MemoryModelInvocationError
        ):
            interpret_remember(
                adapter
            )

        self.assertEqual(
            model.calls,
            2,
        )


if __name__ == "__main__":
    unittest.main()
