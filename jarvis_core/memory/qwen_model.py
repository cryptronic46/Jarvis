from __future__ import annotations

from typing import Any, Protocol
import json

from jarvis_core.core.local_llm import LocalLLMAvailabilityError

from .enums import (
    Cardinality,
    MemoryClass,
    MemoryNamespace,
    ValueType,
)
from .errors import MemoryValidationError
from .interpreter import (
    MemoryOperation,
    QueryTemporalMode,
)
from .validation import require_text


DEFAULT_MEMORY_INTERPRETER_NUM_CTX = 4096
DEFAULT_MEMORY_INTERPRETER_NUM_PREDICT = 768


class QwenMemoryModelError(
    RuntimeError
):
    pass


class QwenMemoryModelAvailabilityError(
    QwenMemoryModelError
):
    pass


class LocalChatClient(
    Protocol
):
    def chat(
        self,
        **kwargs: Any,
    ) -> Any:
        ...


def memory_interpretation_json_schema() -> dict[str, Any]:

    def common_properties() -> dict[str, Any]:
        return {'confidence': {'type': 'number'}, 'explicit_memory_request': {'type': 'boolean'}, 'needs_confirmation': {'type': 'boolean'}, 'ambiguities': {'type': 'array', 'items': {'type': 'string'}}}

    def entity_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'local_ref': {'type': 'string'}, 'canonical_name': {'type': 'string'}, 'entity_type': {'type': 'string'}, 'namespace_hint': {'type': 'string', 'enum': [item.value for item in MemoryNamespace]}, 'aliases': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['local_ref', 'canonical_name', 'entity_type']}

    def fact_property_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'local_ref': {'type': 'string'}, 'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}, 'cardinality': {'type': 'string', 'enum': [item.value for item in Cardinality]}, 'value_type': {'type': 'string', 'enum': [item.value for item in ValueType]}}, 'required': ['local_ref', 'semantic_labels', 'semantic_type', 'cardinality', 'value_type'], 'additionalProperties': False}

    def relation_property_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'local_ref': {'type': 'string'}, 'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}, 'cardinality': {'type': 'string', 'enum': [item.value for item in Cardinality]}}, 'required': ['local_ref', 'semantic_labels', 'semantic_type', 'cardinality'], 'additionalProperties': False}

    def fact_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'subject_ref': {'type': 'string'}, 'property_ref': {'type': 'string'}, 'value': {'description': 'JSON value carrying the proposed fact value'}, 'memory_class': {'type': 'string', 'enum': [item.value for item in MemoryClass]}, 'confidence': {'type': 'number'}, 'unit': {'type': 'string'}, 'value_entity_ref': {'type': 'string'}, 'raw_representation': {'type': 'string'}, 'valid_from': {'type': 'string'}, 'valid_until': {'type': 'string'}}, 'required': ['subject_ref', 'property_ref', 'value', 'memory_class', 'confidence'], 'additionalProperties': False}

    def relation_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'source_ref': {'type': 'string'}, 'property_ref': {'type': 'string'}, 'target_ref': {'type': 'string'}, 'memory_class': {'type': 'string', 'enum': [item.value for item in MemoryClass]}, 'confidence': {'type': 'number'}, 'valid_from': {'type': 'string'}, 'valid_until': {'type': 'string'}}, 'required': ['source_ref', 'property_ref', 'target_ref', 'memory_class', 'confidence'], 'additionalProperties': False}

    def entity_query_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'local_ref': {'type': 'string'}, 'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}}, 'required': ['local_ref', 'semantic_labels', 'semantic_type'], 'additionalProperties': False}

    def property_query_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}}, 'required': ['semantic_labels', 'semantic_type'], 'additionalProperties': False}

    def query_schema() -> dict[str, Any]:
        return {'type': 'object', 'properties': {'subject_refs': {'type': 'array', 'items': {'type': 'string'}}, 'entity_queries': {'type': 'array', 'items': entity_query_schema()}, 'fact_properties': {'type': 'array', 'items': property_query_schema()}, 'relation_properties': {'type': 'array', 'items': property_query_schema()}, 'target_refs': {'type': 'array', 'items': {'type': 'string'}}, 'temporal_mode': {'type': 'string', 'enum': [item.value for item in QueryTemporalMode]}, 'as_of_revision': {'type': 'integer'}, 'retrieval_scope': {'type': 'string', 'enum': ['SELECTOR_SCOPED', 'FULL_SUBJECT_PROFILE']}}, 'additionalProperties': False, 'required': ['retrieval_scope']}
    none_properties = {'operation': {'const': 'NONE'}, **common_properties()}
    remember_properties = {'operation': {'const': 'REMEMBER'}, **common_properties(), 'entities': {'type': 'array', 'items': entity_schema()}, 'fact_properties': {'type': 'array', 'items': fact_property_schema()}, 'relation_properties': {'type': 'array', 'items': relation_property_schema()}, 'facts': {'type': 'array', 'items': fact_schema()}, 'relations': {'type': 'array', 'items': relation_schema()}}
    recall_properties = {'operation': {'const': 'RECALL'}, **common_properties(), 'query': query_schema()}
    return {'oneOf': [{'type': 'object', 'properties': none_properties, 'required': ['operation', 'confidence', 'explicit_memory_request'], 'additionalProperties': False}, {'type': 'object', 'properties': remember_properties, 'required': ['operation', 'confidence', 'explicit_memory_request', 'entities', 'fact_properties', 'relation_properties', 'facts', 'relations'], 'additionalProperties': False}, {'type': 'object', 'properties': recall_properties, 'required': ['operation', 'confidence', 'explicit_memory_request', 'query'], 'additionalProperties': False}]}



class QwenMemoryModelMalformedOutputError(
    QwenMemoryModelError
):
    """The model call succeeded but returned unusable generated content."""

class JarvisQwenMemoryModel:
    def __init__(
        self,
        client: LocalChatClient,
        *,
        model: str,
        keep_alive: Any = None,
        num_ctx: int = (
            DEFAULT_MEMORY_INTERPRETER_NUM_CTX
        ),
        num_predict: int = (
            DEFAULT_MEMORY_INTERPRETER_NUM_PREDICT
        ),
    ) -> None:
        if not callable(
            getattr(
                client,
                "chat",
                None,
            )
        ):
            raise MemoryValidationError(
                (
                    "JarvisQwenMemoryModel.client "
                    "must expose callable chat()"
                )
            )

        require_text(
            model,
            "JarvisQwenMemoryModel.model",
        )

        if (
            not isinstance(
                num_ctx,
                int,
            )
            or isinstance(
                num_ctx,
                bool,
            )
            or num_ctx <= 0
        ):
            raise MemoryValidationError(
                (
                    "JarvisQwenMemoryModel.num_ctx "
                    "must be a positive integer"
                )
            )

        if (
            not isinstance(
                num_predict,
                int,
            )
            or isinstance(
                num_predict,
                bool,
            )
            or num_predict <= 0
        ):
            raise MemoryValidationError(
                (
                    "JarvisQwenMemoryModel.num_predict "
                    "must be a positive integer"
                )
            )

        self._client = client
        self._model = model
        self._keep_alive = keep_alive
        self._num_ctx = num_ctx
        self._num_predict = num_predict

    @property
    def model(
        self,
    ) -> str:
        return self._model

    def _generate_with_schema(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
        schema: dict[str, Any],
        num_predict: int,
    ) -> str:
        require_text(
            system_prompt,
            (
                "JarvisQwenMemoryModel."
                "system_prompt"
            ),
        )

        require_text(
            user_text,
            (
                "JarvisQwenMemoryModel."
                "user_text"
            ),
        )

        require_text(
            context_json,
            (
                "JarvisQwenMemoryModel."
                "context_json"
            ),
        )

        if (
            not isinstance(
                schema,
                dict,
            )
            or not schema
        ):
            raise MemoryValidationError(
                (
                    "JarvisQwenMemoryModel.schema "
                    "must be a non-empty object"
                )
            )

        if (
            not isinstance(
                num_predict,
                int,
            )
            or isinstance(
                num_predict,
                bool,
            )
            or num_predict <= 0
        ):
            raise MemoryValidationError(
                (
                    "JarvisQwenMemoryModel."
                    "stage num_predict "
                    "must be a positive integer"
                )
            )

        try:
            trusted_context = json.loads(
                context_json
            )

        except json.JSONDecodeError as exc:
            raise QwenMemoryModelError(
                (
                    "trusted interpreter context "
                    "is not valid JSON"
                )
            ) from exc

        if not isinstance(
            trusted_context,
            dict,
        ):
            raise QwenMemoryModelError(
                (
                    "trusted interpreter context "
                    "must be a JSON object"
                )
            )

        request_content = json.dumps(
            {
                "context":
                    trusted_context,

                "user_text":
                    user_text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

        try:
            response = self._client.chat(
                model=self._model,

                messages=[
                    {
                        "role":
                            "system",

                        "content":
                            system_prompt,
                    },

                    {
                        "role":
                            "user",

                        "content":
                            request_content,
                    },
                ],

                think=False,

                keep_alive=(
                    self._keep_alive
                ),

                options={
                    "num_ctx":
                        self._num_ctx,

                    "num_predict":
                        num_predict,

                    "temperature":
                        0.0,
                },

                tools=None,

                format=schema,

                stream=False,
            )

        except LocalLLMAvailabilityError as exc:
            raise QwenMemoryModelAvailabilityError(
                (
                    "local Qwen constrained "
                    "JSON call unavailable"
                )
            ) from exc

        except Exception as exc:
            raise QwenMemoryModelError(
                (
                    "local Qwen constrained "
                    "JSON call failed"
                )
            ) from exc

        message = getattr(
            response,
            "message",
            None,
        )

        if message is None:
            raise QwenMemoryModelMalformedOutputError(
                (
                    "local Qwen returned "
                    "no assistant message"
                )
            )

        tool_calls = (
            getattr(
                message,
                "tool_calls",
                None,
            )
            or []
        )

        if tool_calls:
            raise QwenMemoryModelMalformedOutputError(
                (
                    "local Qwen returned "
                    "unexpected tool calls"
                )
            )

        content = getattr(
            message,
            "content",
            None,
        )

        if not isinstance(
            content,
            str,
        ):
            raise QwenMemoryModelMalformedOutputError(
                (
                    "local Qwen returned "
                    "non-text constrained content"
                )
            )

        content = content.strip()

        if not content:
            raise QwenMemoryModelMalformedOutputError(
                (
                    "local Qwen returned "
                    "empty constrained content"
                )
            )

        try:
            json.loads(
                content
            )

        except json.JSONDecodeError as exc:
            raise QwenMemoryModelMalformedOutputError(
                (
                    "local Qwen returned invalid "
                    "constrained JSON"
                )
            ) from exc

        return content

    def generate_constrained_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
        schema: dict[str, Any],
        num_predict: int | None = None,
    ) -> str:
        effective_num_predict = (
            self._num_predict
            if num_predict is None
            else num_predict
        )

        return self._generate_with_schema(
            system_prompt=system_prompt,
            user_text=user_text,
            context_json=context_json,
            schema=schema,
            num_predict=effective_num_predict,
        )

    def generate_memory_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
    ) -> str:
        return self._generate_with_schema(
            system_prompt=system_prompt,
            user_text=user_text,
            context_json=context_json,
            schema=(
                memory_interpretation_json_schema()
            ),
            num_predict=self._num_predict,
        )
