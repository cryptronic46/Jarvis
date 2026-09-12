from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json

from .enums import (
    MEMORY_CONTRACT_VERSION,
)
from .errors import (
    MemoryAvailabilityError,
    MemoryValidationError,
)
from .interpreter import MEMORY_MODEL_CONTEXT_CONTRACT_VERSION
from .qwen_model import (
    QwenMemoryModelAvailabilityError,
    QwenMemoryModelMalformedOutputError,
)
from .interpreter import (
    InterpreterContext,
    MemoryInterpretation,
    SemanticMemoryModel,
    memory_interpreter_system_prompt,
    parse_memory_interpretation,
)
from .models import (
    utc_now,
)
from .validation import (
    require_text,
)
from typing import Protocol
from .enums import Cardinality, MemoryClass, ValueType
from .interpreter import MemoryOperation, QueryTemporalMode
from .validation import require_confidence



MEMORY_INTERPRETER_SCHEMA_VERSION = 4

MEMORY_INTERPRETER_CONTRACT_VERSION = "1.0"


class MemoryInterpretationAdapterError(
    MemoryValidationError
):
    pass


class MemoryModelInvocationError(
    MemoryInterpretationAdapterError
):
    """Invocation failure with request-local operation control metadata."""

    def __init__(
        self,
        message: str,
        *,
        selected_operation: MemoryOperation | None = None,
    ) -> None:
        super().__init__(message)
        if (
            selected_operation is not None
            and not isinstance(selected_operation, MemoryOperation)
        ):
            raise TypeError(
                "selected_operation must be MemoryOperation or None"
            )
        self._selected_operation = selected_operation

    @property
    def selected_operation(self) -> MemoryOperation | None:
        return self._selected_operation


class MemoryModelAvailabilityError(
    MemoryAvailabilityError
):
    """Availability failure with request-local operation control metadata."""

    def __init__(
        self,
        message: str,
        *,
        selected_operation: MemoryOperation | None = None,
    ) -> None:
        super().__init__(message)
        if (
            selected_operation is not None
            and not isinstance(selected_operation, MemoryOperation)
        ):
            raise TypeError(
                "selected_operation must be MemoryOperation or None"
            )
        self._selected_operation = selected_operation

    @property
    def selected_operation(self) -> MemoryOperation | None:
        return self._selected_operation


class MemoryModelContractError(
    MemoryInterpretationAdapterError
):
    """Model-contract failure with a request-local control hint.

    selected_operation is control metadata only. It never makes a
    failed interpretation valid, is never canonical evidence, and
    may only select deterministic fail-closed runtime handling.
    """

    def __init__(
        self,
        message: str,
        *,
        selected_operation: (
            MemoryOperation
            | None
        ) = None,
    ) -> None:
        super().__init__(
            message
        )

        if (
            selected_operation
            is not None
            and not isinstance(
                selected_operation,
                MemoryOperation,
            )
        ):
            raise TypeError(
                "selected_operation must be MemoryOperation or None"
            )

        self._selected_operation = (
            selected_operation
        )

    @property
    def selected_operation(
        self,
    ) -> MemoryOperation | None:
        return self._selected_operation

    def bind_selected_operation(
        self,
        selected_operation: MemoryOperation,
    ) -> None:
        if not isinstance(
            selected_operation,
            MemoryOperation,
        ):
            raise TypeError(
                "selected_operation must be MemoryOperation"
            )

        if (
            self._selected_operation
            is not None
            and self._selected_operation
            is not selected_operation
        ):
            raise RuntimeError(
                "selected_operation control hint is already bound"
            )

        self._selected_operation = (
            selected_operation
        )


def _sha256_text(
    value: str,
) -> str:
    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


def _require_sha256(
    value: str,
    name: str,
) -> None:
    require_text(
        value,
        name,
    )

    if len(
        value
    ) != 64:
        raise MemoryValidationError(
            f"{name} must be SHA-256 hex"
        )

    if value.lower() != value:
        raise MemoryValidationError(
            f"{name} must be lowercase SHA-256 hex"
        )

    try:
        int(
            value,
            16,
        )

    except ValueError as exc:
        raise MemoryValidationError(
            f"{name} must be SHA-256 hex"
        ) from exc


@dataclass(frozen=True, slots=True)
class MemoryInterpretationEnvelope:
    interpreter_schema_version: int
    interpreter_contract_version: str
    memory_contract_version: str
    model_id: str
    generated_at: datetime
    request_sha256: str
    system_prompt_sha256: str
    context_sha256: str
    raw_output_sha256: str
    interpretation: MemoryInterpretation

    def __post_init__(
        self,
    ) -> None:
        if (
            self.interpreter_schema_version
            != MEMORY_INTERPRETER_SCHEMA_VERSION
        ):
            raise MemoryValidationError(
                "unsupported interpreter schema version"
            )

        if (
            self.interpreter_contract_version
            != MEMORY_INTERPRETER_CONTRACT_VERSION
        ):
            raise MemoryValidationError(
                "unsupported interpreter contract version"
            )

        if (
            self.memory_contract_version
            != MEMORY_CONTRACT_VERSION
        ):
            raise MemoryValidationError(
                "memory contract version mismatch"
            )

        require_text(
            self.model_id,
            "MemoryInterpretationEnvelope.model_id",
        )

        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset()
            is None
        ):
            raise MemoryValidationError(
                "generated_at must be timezone-aware"
            )

        _require_sha256(
            self.request_sha256,
            "request_sha256",
        )

        _require_sha256(
            self.system_prompt_sha256,
            "system_prompt_sha256",
        )

        _require_sha256(
            self.context_sha256,
            "context_sha256",
        )

        _require_sha256(
            self.raw_output_sha256,
            "raw_output_sha256",
        )

        if not isinstance(
            self.interpretation,
            MemoryInterpretation,
        ):
            raise MemoryValidationError(
                "interpretation must be "
                "MemoryInterpretation"
            )


def trusted_memory_interpreter_system_prompt() -> str:
    return (
        "JARVIS Memory 1.0 trusted semantic boundary. "
        f"model_context_contract_version="
        f"{MEMORY_MODEL_CONTEXT_CONTRACT_VERSION}; "
        f"interpreter_schema_version="
        f"{MEMORY_INTERPRETER_SCHEMA_VERSION}; "
        f"interpreter_contract_version="
        f"{MEMORY_INTERPRETER_CONTRACT_VERSION}; "
        f"memory_contract_version="
        f"{MEMORY_CONTRACT_VERSION}. "
        "These versions and all envelope metadata are "
        "assigned by the trusted Core, never by the model. "
        + memory_interpreter_system_prompt()
    )


def _context_json(
    context: InterpreterContext,
) -> str:
    payload = {
        "locale":
            context.locale,
        "default_subject_ref":
            context.default_subject_ref,
        "current_time":
            (
                None
                if context.current_time
                is None
                else context
                .current_time
                .isoformat()
            ),
        "model_context_contract_version":
            MEMORY_MODEL_CONTEXT_CONTRACT_VERSION,
        "known_entity_refs":
            list(
                context.known_entity_refs
            ),
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


class TrustedSemanticMemoryAdapter:
    def __init__(
        self,
        model: SemanticMemoryModel,
        *,
        model_id: str,
        clock: Callable[
            [],
            datetime,
        ] = utc_now,
    ) -> None:
        require_text(
            model_id,
            "TrustedSemanticMemoryAdapter.model_id",
        )

        if not callable(
            clock
        ):
            raise MemoryValidationError(
                "clock must be callable"
            )

        self._model = model
        self._model_id = model_id
        self._clock = clock

    @property
    def model_id(
        self,
    ) -> str:
        return self._model_id

    def interpret(
        self,
        text: str,
        *,
        context: InterpreterContext | None = None,
    ) -> MemoryInterpretationEnvelope:
        require_text(
            text,
            "TrustedSemanticMemoryAdapter.text",
        )

        actual_context = (
            context
            or InterpreterContext()
        )

        system_prompt = (
            trusted_memory_interpreter_system_prompt()
        )

        context_json = (
            _context_json(
                actual_context
            )
        )

        try:
            raw_output = (
                self._model
                .generate_memory_json(
                    system_prompt=system_prompt,
                    user_text=text,
                    context_json=context_json,
                )
            )

        except Exception as exc:
            raise MemoryModelInvocationError(
                "semantic memory model invocation failed"
            ) from exc

        if not isinstance(
            raw_output,
            str,
        ):
            raise MemoryModelContractError(
                "semantic memory model returned "
                "non-text output"
            )

        try:
            interpretation = (
                parse_memory_interpretation(
                    raw_output
                )
            )

        except MemoryValidationError as exc:
            raise MemoryModelContractError(
                "semantic memory model output "
                "was rejected by trusted Core"
            ) from exc

        generated_at = (
            self._clock()
        )

        if not isinstance(
            generated_at,
            datetime,
        ):
            raise MemoryInterpretationAdapterError(
                "trusted clock returned "
                "non-datetime value"
            )

        if (
            generated_at.tzinfo is None
            or generated_at.utcoffset()
            is None
        ):
            raise MemoryInterpretationAdapterError(
                "trusted clock returned "
                "timezone-naive datetime"
            )

        return MemoryInterpretationEnvelope(
            interpreter_schema_version=(
                MEMORY_INTERPRETER_SCHEMA_VERSION
            ),
            interpreter_contract_version=(
                MEMORY_INTERPRETER_CONTRACT_VERSION
            ),
            memory_contract_version=(
                MEMORY_CONTRACT_VERSION
            ),
            model_id=self._model_id,
            generated_at=generated_at,
            request_sha256=(
                _sha256_text(
                    text
                )
            ),
            system_prompt_sha256=(
                _sha256_text(
                    system_prompt
                )
            ),
            context_sha256=(
                _sha256_text(
                    context_json
                )
            ),
            raw_output_sha256=(
                _sha256_text(
                    raw_output
                )
            ),
            interpretation=interpretation,
        )


MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION = "1.0"

_OPERATION_STAGE = "operation_selection"
_REMEMBER_STAGE = "remember_extraction"
_RECALL_STAGE = "recall_extraction"

_OPERATION_NUM_PREDICT = 64
_REMEMBER_NUM_PREDICT = 768
_RECALL_NUM_PREDICT = 256


class TwoStageSemanticMemoryModel(
    Protocol
):
    def generate_constrained_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
        schema: dict,
        num_predict: int | None = None,
    ) -> str:
        ...


def memory_operation_selection_json_schema(
) -> dict:
    return {
        "type":
            "object",

        "properties": {
            "operation": {
                "type":
                    "string",

                "enum": [
                    "NONE",
                    "REMEMBER",
                    "RECALL",
                ],
            },

            "confidence": {
                "type":
                    "number",
            },
        },

        "required": [
            "operation",
            "confidence",
        ],

        "additionalProperties":
            False,
    }


def _entity_extraction_schema(
) -> dict:
    return {
        "type":
            "object",

        "properties": {
            "local_ref": {
                "type":
                    "string",
            },

            "canonical_name": {
                "type":
                    "string",
            },

            "entity_type": {
                "type":
                    "string",
            },
        },

        "required": [
            "local_ref",
            "canonical_name",
            "entity_type",
        ],

        "additionalProperties":
            False,
    }



def _fact_property_extraction_schema(
) -> dict:
    return {
        "type": "object",
        "properties": {
            "local_ref": {
                "type": "string",
            },
            "semantic_labels": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
            "semantic_type": {
                "type": "string",
            },
            "cardinality": {
                "type": "string",
                "enum": [
                    item.value
                    for item in Cardinality
                ],
            },
            "value_type": {
                "type": "string",
                "enum": [
                    item.value
                    for item in ValueType
                ],
            },
        },
        "required": [
            "local_ref",
            "semantic_labels",
            "semantic_type",
            "cardinality",
            "value_type",
        ],
        "additionalProperties": False,
    }


def _relation_property_extraction_schema(
) -> dict:
    return {
        "type": "object",
        "properties": {
            "local_ref": {
                "type": "string",
            },
            "semantic_labels": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
            "semantic_type": {
                "type": "string",
            },
            "cardinality": {
                "type": "string",
                "enum": [
                    item.value
                    for item in Cardinality
                ],
            },
        },
        "required": [
            "local_ref",
            "semantic_labels",
            "semantic_type",
            "cardinality",
        ],
        "additionalProperties": False,
    }


def _fact_extraction_schema(
) -> dict:
    return {
        "type": "object",
        "properties": {
            "subject_ref": {
                "type": "string",
            },
            "property_ref": {
                "type": "string",
            },
            "value": {
                "description":
                    "Semantic fact value",
            },
            "memory_class": {
                "type": "string",
                "enum": [
                    item.value
                    for item in MemoryClass
                ],
            },
            "confidence": {
                "type": "number",
            },
            "unit": {
                "type": "string",
            },
            "value_entity_ref": {
                "type": "string",
            },
            "raw_representation": {
                "type": "string",
            },
            "valid_from": {
                "type": "string",
            },
            "valid_until": {
                "type": "string",
            },
        },
        "required": [
            "subject_ref",
            "property_ref",
            "value",
            "memory_class",
            "confidence",
        ],
        "additionalProperties": False,
    }




def _relation_extraction_schema(
) -> dict:
    return {
        "type": "object",
        "properties": {
            "source_ref": {
                "type": "string",
            },
            "property_ref": {
                "type": "string",
            },
            "target_ref": {
                "type": "string",
            },
            "memory_class": {
                "type": "string",
                "enum": [
                    item.value
                    for item in MemoryClass
                ],
            },
            "confidence": {
                "type": "number",
            },
            "valid_from": {
                "type": "string",
            },
            "valid_until": {
                "type": "string",
            },
        },
        "required": [
            "source_ref",
            "property_ref",
            "target_ref",
            "memory_class",
            "confidence",
        ],
        "additionalProperties": False,
    }




def memory_remember_extraction_json_schema(
) -> dict:
    return {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items":
                    _entity_extraction_schema(),
            },
            "fact_properties": {
                "type": "array",
                "items":
                    _fact_property_extraction_schema(),
            },
            "relation_properties": {
                "type": "array",
                "items":
                    _relation_property_extraction_schema(),
            },
            "facts": {
                "type": "array",
                "items":
                    _fact_extraction_schema(),
            },
            "relations": {
                "type": "array",
                "items":
                    _relation_extraction_schema(),
            },
            "needs_confirmation": {
                "type": "boolean",
            },
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
        },
        "required": [
            "entities",
            "fact_properties",
            "relation_properties",
            "facts",
            "relations",
        ],
        "additionalProperties": False,
    }





def _recall_query_extraction_schema() -> dict:
    property_query_schema = {'type': 'object', 'properties': {'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}}, 'required': ['semantic_labels', 'semantic_type'], 'additionalProperties': False}
    entity_query_schema = {'type': 'object', 'properties': {'local_ref': {'type': 'string'}, 'semantic_labels': {'type': 'array', 'items': {'type': 'string'}}, 'semantic_type': {'type': 'string'}}, 'required': ['local_ref', 'semantic_labels', 'semantic_type'], 'additionalProperties': False}
    return {'type': 'object', 'properties': {'subject_refs': {'type': 'array', 'items': {'type': 'string'}}, 'entity_queries': {'type': 'array', 'items': entity_query_schema}, 'fact_properties': {'type': 'array', 'items': property_query_schema}, 'relation_properties': {'type': 'array', 'items': property_query_schema}, 'target_refs': {'type': 'array', 'items': {'type': 'string'}}, 'temporal_mode': {'type': 'string', 'enum': [item.value for item in QueryTemporalMode]}, 'as_of_revision': {'type': 'integer'}, 'retrieval_scope': {'type': 'string', 'enum': ['SELECTOR_SCOPED', 'FULL_SUBJECT_PROFILE']}}, 'additionalProperties': False, 'required': ['retrieval_scope']}





def memory_recall_extraction_json_schema(
) -> dict:
    return {
        "type":
            "object",

        "properties": {
            "query":
                _recall_query_extraction_schema(),

            "needs_confirmation": {
                "type":
                    "boolean",
            },

            "ambiguities": {
                "type":
                    "array",

                "items": {
                    "type":
                        "string",
                },
            },
        },

        "required": [
            "query",
        ],

        "additionalProperties":
            False,
    }


def trusted_memory_operation_selector_system_prompt(
) -> str:
    return (
        "JARVIS Memory 1.0 trusted operation-selection stage. "
        f"interpreter_schema_version="
        f"{MEMORY_INTERPRETER_SCHEMA_VERSION}; "
        f"interpreter_contract_version="
        f"{MEMORY_INTERPRETER_CONTRACT_VERSION}; "
        f"memory_contract_version="
        f"{MEMORY_CONTRACT_VERSION}; "
        f"two_stage_execution_contract_version="
        f"{MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION}. "
        "Classify only whether the current user turn invokes "
        "persistent-memory behaviour. "
        "REMEMBER means the current turn directly requests "
        "persistent retention of information. "
        "RECALL means the current turn asks for information "
        "whose answer depends on persistent memory. "
        "NONE means the current turn is neither. "
        "Personal information by itself does not create a "
        "persistence request. "
        "Do not extract entities, facts, relations, queries, "
        "actions, answers, values, predicates, memory classes "
        "or persistence results. "
        "All authority, persistence and security decisions "
        "belong exclusively to the trusted Core. "
        "Return only JSON matching the supplied schema."
    )



def trusted_memory_remember_extractor_system_prompt(
) -> str:
    return (
        "JARVIS Memory 1.0 trusted REMEMBER extraction stage. "
        f"model_context_contract_version="
        f"{MEMORY_MODEL_CONTEXT_CONTRACT_VERSION}; "
        f"interpreter_schema_version="
        f"{MEMORY_INTERPRETER_SCHEMA_VERSION}; "
        f"interpreter_contract_version="
        f"{MEMORY_INTERPRETER_CONTRACT_VERSION}; "
        f"memory_contract_version="
        f"{MEMORY_CONTRACT_VERSION}; "
        f"two_stage_execution_contract_version="
        f"{MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION}. "
        "A previous trusted semantic stage has already "
        "selected REMEMBER. "
        "Do not reconsider or classify the operation. "
        "The selected MemoryOperation is control-plane metadata only; "
        "it is not semantic content proposed for retention. "
        "semantic_labels and semantic_type must describe only the "
        "semantic identity of the retained property or assertion. "
        "Never use the memory operation token or the storage/recall "
        "command itself as the semantic identity of a property. "
        "For a literal subject attribute, extract the content property "
        "and its literal value rather than the memory instruction. "
        "Extract only semantic information proposed for retention. "
        "Reuse default_subject_ref and known entity references "
        "when they already identify a subject or entity. "
        "Do not redeclare resolved references as new entities. "
        # D417E2K6E1C3B4D_R2_F2_GENERIC_ENTITY_CROSS_REFERENCE_PROMPT
        "Create an entity only when an independently referable "
        "entity is required by a fact or relation. "
        "Every entities[].local_ref must be referenced by at least "
        "one facts[].subject_ref, facts[].value_entity_ref, "
        "relations[].source_ref or relations[].target_ref. "
        "Known references supplied by trusted context must be reused "
        "without redeclaring them as new entities. "
        "Do not create an entity merely to represent a property, "
        "preference category, attribute or literal value. "
        "Do not fabricate value_entity_ref, subject_ref or relation "
        "references merely to make an entity proposal appear used. "
        "If a proposed entity would only wrap a literal value, omit "
        "that entity and use the narrowest literal ValueType with a "
        "coherent non-RELATIONAL MemoryClass. "
        "If no genuinely new independently referable entity is "
        "required, return entities as an empty array. "
        "Represent property identity explicitly through "
        "fact_properties and relation_properties. "
        "Each property proposal has an opaque local_ref, "
        "semantic_labels, semantic_type and cardinality. "
        "Fact properties additionally carry value_type. "
        "Relation properties do not carry value_type. "
        "Facts and relations refer to property proposals only "
        "through property_ref. "
        "A property proposal may be reused by multiple atomic "
        "assertions that share that property. "
        "Use the narrowest ValueType that preserves a fact value. "
        "ENTITY_REF is only for an entity-valued fact property "
        "and the corresponding fact must carry value_entity_ref. "
        "For facts, ENTITY_REF requires memory_class=RELATIONAL, "
        "and memory_class=RELATIONAL requires ENTITY_REF. "
        "Literal fact ValueTypes must use a non-RELATIONAL "
        "MemoryClass appropriate to the assertion. "
        "MemoryClass describes the semantic nature of the assertion. "
        "Do not emit predicates or canonical entity/property IDs. "
        "Do not assign authority, source type, transactions, "
        "revisions, permissions, commit status, supersession "
        "or persistence claims. "
        "Return only JSON matching the supplied schema."
    )


def _remember_structural_retry_prompt(
    extraction_prompt: str,
    *,
    validation_reason: str,
) -> str:
    require_text(
        extraction_prompt,
        "_remember_structural_retry_prompt.extraction_prompt",
    )

    require_text(
        validation_reason,
        "_remember_structural_retry_prompt.validation_reason",
    )

    return (
        extraction_prompt
        + " The previous REMEMBER extraction violated "
        "a structural Memory 1.0 contract. "
        "Trusted Core validation reason: "
        + validation_reason
        + ". Regenerate the complete Stage-2 payload "
        "from the original user turn and trusted context. "
        "Before satisfying cross-reference requirements, "
        "first reconsider whether each proposed entity "
        "should exist independently. "
        "Do not fabricate value_entity_ref, subject_ref "
        "or relation references merely to make an entity "
        "proposal appear used. "
        "If a proposed entity only wraps a literal value, "
        "remove the entity and use the narrowest literal "
        "ValueType with a coherent non-RELATIONAL "
        "MemoryClass. "
        "For facts, preserve ENTITY_REF if and only if "
        "memory_class=RELATIONAL. "
        "Do not use the selected MemoryOperation token or the memory "
        "command itself as semantic_labels or semantic_type. "
        "Rebuild the complete payload from the original "
        "semantic intent. Do not reuse, prune, patch or "
        "locally repair the previous payload."
    )





def trusted_memory_recall_extractor_system_prompt(
) -> str:
    return (
        "JARVIS Memory 1.0 trusted RECALL extraction stage. "
        f"model_context_contract_version="
        f"{MEMORY_MODEL_CONTEXT_CONTRACT_VERSION}; "
        f"interpreter_schema_version="
        f"{MEMORY_INTERPRETER_SCHEMA_VERSION}; "
        f"interpreter_contract_version="
        f"{MEMORY_INTERPRETER_CONTRACT_VERSION}; "
        f"memory_contract_version="
        f"{MEMORY_CONTRACT_VERSION}; "
        f"two_stage_execution_contract_version="
        f"{MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION}. "
        "A previous trusted semantic stage has already "
        "selected RECALL. "
        "Do not reconsider or classify the operation. "
        "Extract only retrieval semantics required to query "
        "persistent memory. "
        "Do not answer the question and do not emit REMEMBER "
        "write proposals. "
        "Reuse default_subject_ref and known entity references "
        "when appropriate. "
        "When a requested entity is already represented by a "
        "known entity reference, use that reference directly "
        "inside subject_refs or target_refs and do not add an "
        "entity query for it. "
        "For a requested entity that is not represented by a "
        "known entity reference, create an opaque local_ref, "
        "use that same local_ref inside subject_refs or "
        "target_refs, and add exactly one object for it inside "
        "entity_queries. "
        "Each entity query contains only local_ref, "
        "semantic_labels and semantic_type. "
        "Treat requested attributes, preferences, categories and "
        "literal-valued characteristics of a subject as fact-property "
        "semantics, not as target entities. "
        "When the request asks for the value of such a characteristic, "
        "emit one matching fact_properties object and do not copy the "
        "subject into target_refs. "
        "Use target_refs only for entities that are semantic targets "
        "of requested relations. "
        "Represent every requested fact property as one object "
        "inside fact_properties and every requested relation "
        "property as one object inside relation_properties. "
        "Each property object contains semantic_labels and "
        "semantic_type. Group multiple semantic labels that "
        "describe the same property inside one object. "
        "Use multiple objects only when multiple distinct "
        "properties are requested. "
        "Set retrieval_scope=SELECTOR_SCOPED when the request asks "
        "for one or more specific fact properties, relation properties "
        "or target entities. For SELECTOR_SCOPED, at least one of "
        "fact_properties, relation_properties or target_refs must be "
        "non-empty. Set retrieval_scope=FULL_SUBJECT_PROFILE only when "
        "the semantic intent is to retrieve the subject profile broadly "
        "rather than a specific selector. Empty selectors are legitimate "
        "for FULL_SUBJECT_PROFILE. Never use FULL_SUBJECT_PROFILE merely "
        "to hide a missing selector. "
        "For present or default retrieval, use temporal_mode=CURRENT "
        "and omit as_of_revision. "
        "For historical retrieval without an explicit canonical "
        "revision, use temporal_mode=HISTORICAL and omit "
        "as_of_revision. "
        "Use temporal_mode=AS_OF_REVISION only when the request "
        "explicitly specifies a canonical revision; then include a "
        "non-negative as_of_revision. "
        "Never emit as_of_revision as a placeholder or default value; "
        "revision 0 is valid only when canonical revision 0 is "
        "explicitly requested. "
        "Do not emit canonical entity or property IDs. "
        "Do not assign authority, source type, canonical IDs, "
        "transactions, revisions, permissions, commit status, "
        "supersession or persistence claims. "
        "Return only JSON matching the supplied schema."
    )





def _canonical_schema_json(
    schema: dict,
) -> str:
    return json.dumps(
        schema,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _decode_stage_object(
    raw_output: str,
    *,
    name: str,
    allowed_keys: frozenset[str],
    required_keys: frozenset[str],
) -> dict:
    if not isinstance(
        raw_output,
        str,
    ):
        raise MemoryModelContractError(
            f"{name} returned non-text output"
        )

    try:
        value = json.loads(
            raw_output
        )

    except json.JSONDecodeError as exc:
        raise MemoryModelContractError(
            f"{name} output is not valid JSON"
        ) from exc

    if not isinstance(
        value,
        dict,
    ):
        raise MemoryModelContractError(
            f"{name} output must be an object"
        )

    keys = set(
        value
    )

    unknown = sorted(
        keys
        - allowed_keys
    )

    if unknown:
        raise MemoryModelContractError(
            (
                f"{name} contains unknown keys: "
                + ", ".join(
                    unknown
                )
            )
        )

    missing = sorted(
        required_keys
        - keys
    )

    if missing:
        raise MemoryModelContractError(
            (
                f"{name} missing required keys: "
                + ", ".join(
                    missing
                )
            )
        )

    return dict(
        value
    )


def _operation_confidence(
    value,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise MemoryModelContractError(
            "operation confidence must be numeric"
        )

    try:
        result = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise MemoryModelContractError(
            "operation confidence must be numeric"
        ) from exc

    try:
        require_confidence(
            result
        )

    except MemoryValidationError as exc:
        raise MemoryModelContractError(
            "operation confidence is invalid"
        ) from exc

    return result


def _parse_operation_stage(
    raw_output: str,
) -> tuple[
    MemoryOperation,
    float,
]:
    data = _decode_stage_object(
        raw_output,
        name=_OPERATION_STAGE,
        allowed_keys=frozenset(
            {
                "operation",
                "confidence",
            }
        ),
        required_keys=frozenset(
            {
                "operation",
                "confidence",
            }
        ),
    )

    try:
        operation = MemoryOperation(
            str(
                data[
                    "operation"
                ]
            )
        )

    except ValueError as exc:
        raise MemoryModelContractError(
            "operation stage returned invalid operation"
        ) from exc

    if operation not in {
        MemoryOperation.NONE,
        MemoryOperation.REMEMBER,
        MemoryOperation.RECALL,
    }:
        raise MemoryModelContractError(
            "operation stage returned unsupported operation"
        )

    return (
        operation,
        _operation_confidence(
            data[
                "confidence"
            ]
        ),
    )


def _compose_none_interpretation(
    confidence: float,
) -> MemoryInterpretation:
    return parse_memory_interpretation(
        json.dumps(
            {
                "operation":
                    "NONE",

                "confidence":
                    confidence,

                "explicit_memory_request":
                    False,

                "entities":
                    [],

                "facts":
                    [],

                "relations":
                    [],
            },
            ensure_ascii=False,
        )
    )



def _compose_remember_interpretation(
    raw_output: str,
    *,
    confidence: float,
) -> MemoryInterpretation:
    data = _decode_stage_object(
        raw_output,
        name=_REMEMBER_STAGE,
        allowed_keys=frozenset(
            {
                "entities",
                "fact_properties",
                "relation_properties",
                "facts",
                "relations",
                "needs_confirmation",
                "ambiguities",
            }
        ),
        required_keys=frozenset(
            {
                "entities",
                "fact_properties",
                "relation_properties",
                "facts",
                "relations",
            }
        ),
    )

    payload = {
        "operation":
            "REMEMBER",

        "confidence":
            confidence,

        "explicit_memory_request":
            True,

        "entities":
            data[
                "entities"
            ],

        "fact_properties":
            data[
                "fact_properties"
            ],

        "relation_properties":
            data[
                "relation_properties"
            ],

        "facts":
            data[
                "facts"
            ],

        "relations":
            data[
                "relations"
            ],

        "needs_confirmation":
            data.get(
                "needs_confirmation",
                False,
            ),

        "ambiguities":
            data.get(
                "ambiguities",
                [],
            ),
    }

    try:
        return parse_memory_interpretation(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )

    except MemoryValidationError as exc:
        raise MemoryModelContractError(
            (
                "REMEMBER extraction was "
                "rejected by trusted Core"
            )
        ) from exc



def _compose_validated_remember_interpretation(
    raw_output: str,
    *,
    confidence: float,
) -> MemoryInterpretation:
    try:
        interpretation = (
            _compose_remember_interpretation(
                raw_output,
                confidence=confidence,
            )
        )

    except MemoryModelContractError as exc:
        exc.bind_selected_operation(
            MemoryOperation.REMEMBER
        )
        raise

    from .proposal_validation import (
        validate_remember_entity_proposal_usage,
    )

    try:
        validate_remember_entity_proposal_usage(
            interpretation
        )

    except MemoryValidationError as exc:
        raise MemoryModelContractError(
            (
                "REMEMBER extraction violated "
                "structural resolution-input contract"
            ),
            selected_operation=(
                MemoryOperation.REMEMBER
            ),
        ) from exc

    return interpretation


def _compose_recall_interpretation(
    raw_output: str,
    *,
    confidence: float,
) -> MemoryInterpretation:
    data = _decode_stage_object(
        raw_output,
        name=_RECALL_STAGE,
        allowed_keys=frozenset(
            {
                "query",
                "needs_confirmation",
                "ambiguities",
            }
        ),
        required_keys=frozenset(
            {
                "query",
            }
        ),
    )

    payload = {
        "operation":
            "RECALL",

        "confidence":
            confidence,

        "explicit_memory_request":
            True,

        "entities":
            [],

        "facts":
            [],

        "relations":
            [],

        "query":
            data[
                "query"
            ],

        "needs_confirmation":
            data.get(
                "needs_confirmation",
                False,
            ),

        "ambiguities":
            data.get(
                "ambiguities",
                [],
            ),
    }

    try:
        query_payload = data["query"]
        if not isinstance(query_payload, dict):
            raise MemoryValidationError(
                "RECALL query must be an object"
            )
        if "retrieval_scope" not in query_payload:
            raise MemoryValidationError(
                "RECALL query requires retrieval_scope"
            )

        return parse_memory_interpretation(
            json.dumps(
                payload,
                ensure_ascii=False,
            )
        )

    except MemoryValidationError as exc:
        raise MemoryModelContractError(
            (
                "RECALL extraction was "
                "rejected by trusted Core"
            )
        ) from exc


def _compose_validated_recall_interpretation(
    raw_output: str,
    *,
    confidence: float,
) -> MemoryInterpretation:
    try:
        return _compose_recall_interpretation(
            raw_output,
            confidence=confidence,
        )
    except MemoryModelContractError as exc:
        exc.bind_selected_operation(MemoryOperation.RECALL)
        raise


def _recall_structural_retry_prompt(
    extraction_prompt: str,
    *,
    validation_reason: str,
) -> str:
    require_text(
        extraction_prompt,
        "_recall_structural_retry_prompt.extraction_prompt",
    )
    require_text(
        validation_reason,
        "_recall_structural_retry_prompt.validation_reason",
    )
    return (
        extraction_prompt
        + " The previous RECALL extraction violated "
        "a structural Memory 1.0 contract. "
        "Trusted Core validation reason: "
        + validation_reason
        + ". Regenerate the complete Stage-2 payload "
        "from the original user turn and trusted context. "
        "Preserve the semantic retrieval intent, but do not "
        "reuse, prune, patch or locally repair the previous payload. "
        "If retrieval_scope=SELECTOR_SCOPED, emit at least one "
        "fact_properties, relation_properties or target_refs selector. "
        "Use FULL_SUBJECT_PROFILE only when the original request "
        "semantically asks for the subject profile broadly. "
        "For CURRENT or HISTORICAL retrieval omit as_of_revision. "
        "Use AS_OF_REVISION only when the original request explicitly "
        "asks for a canonical revision. Do not invent revision 0 or "
        "any other placeholder revision."
    )



@dataclass(
    frozen=True,
    slots=True,
)
class MemoryInterpretationStageReceipt:
    stage: str
    model_id: str
    system_prompt_sha256: str
    schema_sha256: str
    raw_output_sha256: str
    selected_operation: MemoryOperation | None = None
    operation_confidence: float | None = None

    def __post_init__(
        self,
    ) -> None:
        if self.stage not in {
            _OPERATION_STAGE,
            _REMEMBER_STAGE,
            _RECALL_STAGE,
        }:
            raise MemoryValidationError(
                "invalid interpretation stage"
            )

        require_text(
            self.model_id,
            "MemoryInterpretationStageReceipt.model_id",
        )

        _require_sha256(
            self.system_prompt_sha256,
            "stage.system_prompt_sha256",
        )

        _require_sha256(
            self.schema_sha256,
            "stage.schema_sha256",
        )

        _require_sha256(
            self.raw_output_sha256,
            "stage.raw_output_sha256",
        )

        if self.stage == _OPERATION_STAGE:
            if self.selected_operation is None:
                raise MemoryValidationError(
                    (
                        "operation stage requires "
                        "selected_operation"
                    )
                )

            if self.operation_confidence is None:
                raise MemoryValidationError(
                    (
                        "operation stage requires "
                        "operation_confidence"
                    )
                )

            require_confidence(
                self.operation_confidence
            )

        else:
            if self.selected_operation is not None:
                raise MemoryValidationError(
                    (
                        "extraction stage cannot own "
                        "selected_operation"
                    )
                )

            if self.operation_confidence is not None:
                raise MemoryValidationError(
                    (
                        "extraction stage cannot own "
                        "operation confidence"
                    )
                )


@dataclass(
    frozen=True,
    slots=True,
)
class TwoStageMemoryInterpretationEnvelope:
    interpreter_schema_version: int
    interpreter_contract_version: str
    memory_contract_version: str
    execution_contract_version: str
    model_id: str
    generated_at: datetime
    request_sha256: str
    context_sha256: str
    operation_stage: MemoryInterpretationStageReceipt
    extraction_stage: (
        MemoryInterpretationStageReceipt
        | None
    )
    interpretation: MemoryInterpretation

    def __post_init__(
        self,
    ) -> None:
        if (
            self.interpreter_schema_version
            != MEMORY_INTERPRETER_SCHEMA_VERSION
        ):
            raise MemoryValidationError(
                "unsupported interpreter schema version"
            )

        if (
            self.interpreter_contract_version
            != MEMORY_INTERPRETER_CONTRACT_VERSION
        ):
            raise MemoryValidationError(
                "unsupported interpreter contract version"
            )

        if (
            self.memory_contract_version
            != MEMORY_CONTRACT_VERSION
        ):
            raise MemoryValidationError(
                "memory contract version mismatch"
            )

        if (
            self.execution_contract_version
            != MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION
        ):
            raise MemoryValidationError(
                "two-stage execution contract mismatch"
            )

        require_text(
            self.model_id,
            "TwoStageMemoryInterpretationEnvelope.model_id",
        )

        if (
            self.generated_at.tzinfo is None
            or self.generated_at.utcoffset()
            is None
        ):
            raise MemoryValidationError(
                "generated_at must be timezone-aware"
            )

        _require_sha256(
            self.request_sha256,
            "request_sha256",
        )

        _require_sha256(
            self.context_sha256,
            "context_sha256",
        )

        if not isinstance(
            self.operation_stage,
            MemoryInterpretationStageReceipt,
        ):
            raise MemoryValidationError(
                "operation_stage must be stage receipt"
            )

        if (
            self.operation_stage.stage
            != _OPERATION_STAGE
        ):
            raise MemoryValidationError(
                "operation_stage has wrong stage"
            )

        if (
            self.operation_stage.model_id
            != self.model_id
        ):
            raise MemoryValidationError(
                "operation stage model mismatch"
            )

        if (
            self.operation_stage.selected_operation
            is not self.interpretation.operation
        ):
            raise MemoryValidationError(
                (
                    "operation receipt disagrees "
                    "with final interpretation"
                )
            )

        if (
            self.operation_stage.operation_confidence
            != self.interpretation.confidence
        ):
            raise MemoryValidationError(
                (
                    "operation confidence disagrees "
                    "with final interpretation"
                )
            )

        if (
            self.interpretation.operation
            is MemoryOperation.NONE
        ):
            if self.extraction_stage is not None:
                raise MemoryValidationError(
                    "NONE cannot have extraction stage"
                )

        elif (
            self.interpretation.operation
            is MemoryOperation.REMEMBER
        ):
            if (
                self.extraction_stage is None
                or self.extraction_stage.stage
                != _REMEMBER_STAGE
            ):
                raise MemoryValidationError(
                    (
                        "REMEMBER requires "
                        "REMEMBER extraction receipt"
                    )
                )

        elif (
            self.interpretation.operation
            is MemoryOperation.RECALL
        ):
            if (
                self.extraction_stage is None
                or self.extraction_stage.stage
                != _RECALL_STAGE
            ):
                raise MemoryValidationError(
                    (
                        "RECALL requires "
                        "RECALL extraction receipt"
                    )
                )

        else:
            raise MemoryValidationError(
                (
                    "two-stage envelope does not yet "
                    "support this operation"
                )
            )

        if (
            self.extraction_stage is not None
            and self.extraction_stage.model_id
            != self.model_id
        ):
            raise MemoryValidationError(
                "extraction stage model mismatch"
            )


class TrustedTwoStageSemanticMemoryAdapter:
    def __init__(
        self,
        model: TwoStageSemanticMemoryModel,
        *,
        model_id: str,
        clock: Callable[
            [],
            datetime,
        ] = utc_now,
    ) -> None:
        require_text(
            model_id,
            (
                "TrustedTwoStageSemanticMemoryAdapter."
                "model_id"
            ),
        )

        if not callable(
            getattr(
                model,
                "generate_constrained_json",
                None,
            )
        ):
            raise MemoryValidationError(
                (
                    "two-stage model must expose "
                    "generate_constrained_json()"
                )
            )

        if not callable(
            clock
        ):
            raise MemoryValidationError(
                "clock must be callable"
            )

        self._model = model
        self._model_id = model_id
        self._clock = clock

    @property
    def model_id(
        self,
    ) -> str:
        return self._model_id

    def _invoke_stage(
        self,
        *,
        stage: str,
        selected_operation: (
            MemoryOperation
            | None
        ) = None,
        system_prompt: str,
        schema: dict,
        text: str,
        context_json: str,
        num_predict: int,
    ) -> str:
        try:
            output = (
                self._model
                .generate_constrained_json(
                    system_prompt=system_prompt,
                    user_text=text,
                    context_json=context_json,
                    schema=schema,
                    num_predict=num_predict,
                )
            )

        except QwenMemoryModelMalformedOutputError as exc:
            raise MemoryModelContractError(
                f"{stage} returned malformed model output",
                selected_operation=(
                    selected_operation
                ),
            ) from exc

        except QwenMemoryModelAvailabilityError as exc:
            raise MemoryModelAvailabilityError(
                f"{stage} model unavailable",
                selected_operation=selected_operation,
            ) from exc

        except MemoryAvailabilityError as exc:
            raise MemoryModelAvailabilityError(
                f"{stage} model unavailable",
                selected_operation=selected_operation,
            ) from exc

        except Exception as exc:
            raise MemoryModelInvocationError(
                f"{stage} model invocation failed",
                selected_operation=selected_operation,
            ) from exc

        if not isinstance(
            output,
            str,
        ):
            raise MemoryModelContractError(
                f"{stage} returned non-text output",
                selected_operation=(
                    selected_operation
                ),
            )

        if not output.strip():
            raise MemoryModelContractError(
                f"{stage} returned empty output",
                selected_operation=(
                    selected_operation
                ),
            )

        return output

    def _stage_receipt(
        self,
        *,
        stage: str,
        system_prompt: str,
        schema: dict,
        raw_output: str,
        selected_operation: (
            MemoryOperation
            | None
        ) = None,
        operation_confidence: (
            float
            | None
        ) = None,
    ) -> MemoryInterpretationStageReceipt:
        return MemoryInterpretationStageReceipt(
            stage=stage,
            model_id=self._model_id,
            system_prompt_sha256=(
                _sha256_text(
                    system_prompt
                )
            ),
            schema_sha256=(
                _sha256_text(
                    _canonical_schema_json(
                        schema
                    )
                )
            ),
            raw_output_sha256=(
                _sha256_text(
                    raw_output
                )
            ),
            selected_operation=(
                selected_operation
            ),
            operation_confidence=(
                operation_confidence
            ),
        )

    def interpret(
        self,
        text: str,
        *,
        context: InterpreterContext | None = None,
    ) -> TwoStageMemoryInterpretationEnvelope:
        require_text(
            text,
            (
                "TrustedTwoStageSemanticMemoryAdapter."
                "text"
            ),
        )

        actual_context = (
            context
            or InterpreterContext()
        )

        context_json = _context_json(
            actual_context
        )

        operation_prompt = (
            trusted_memory_operation_selector_system_prompt()
        )

        operation_schema = (
            memory_operation_selection_json_schema()
        )

        operation_raw = self._invoke_stage(
            stage=_OPERATION_STAGE,
            system_prompt=operation_prompt,
            schema=operation_schema,
            text=text,
            context_json=context_json,
            num_predict=_OPERATION_NUM_PREDICT,
        )

        (
            operation,
            operation_confidence,
        ) = _parse_operation_stage(
            operation_raw
        )

        operation_receipt = (
            self._stage_receipt(
                stage=_OPERATION_STAGE,
                system_prompt=operation_prompt,
                schema=operation_schema,
                raw_output=operation_raw,
                selected_operation=operation,
                operation_confidence=(
                    operation_confidence
                ),
            )
        )

        extraction_receipt = None

        if (
            operation
            is MemoryOperation.NONE
        ):
            interpretation = (
                _compose_none_interpretation(
                    operation_confidence
                )
            )

        elif (
            operation
            is MemoryOperation.REMEMBER
        ):
            extraction_prompt = (
                trusted_memory_remember_extractor_system_prompt()
            )

            extraction_schema = (
                memory_remember_extraction_json_schema()
            )

            # D417E2K6E1C3B4E4N_E4P_R4_BOUNDED_STAGE2_REGENERATION
            try:
                extraction_raw = (
                    self._invoke_stage(
                        stage=_REMEMBER_STAGE,
                        selected_operation=operation,
                        system_prompt=(
                            extraction_prompt
                        ),
                        schema=(
                            extraction_schema
                        ),
                        text=text,
                        context_json=(
                            context_json
                        ),
                        num_predict=(
                            _REMEMBER_NUM_PREDICT
                        ),
                    )
                )

                interpretation = (
                    _compose_validated_remember_interpretation(
                        extraction_raw,
                        confidence=(
                            operation_confidence
                        ),
                    )
                )

            except MemoryModelContractError as exc:
                if not isinstance(
                    exc.__cause__,
                    (
                        MemoryValidationError,
                        QwenMemoryModelMalformedOutputError,
                    ),
                ):
                    raise

                retry_prompt = (
                    _remember_structural_retry_prompt(
                        extraction_prompt,
                        validation_reason=(
                            str(exc.__cause__)
                        ),
                    )
                )

                extraction_raw = (
                    self._invoke_stage(
                        stage=_REMEMBER_STAGE,
                        selected_operation=operation,
                        system_prompt=(
                            retry_prompt
                        ),
                        schema=(
                            extraction_schema
                        ),
                        text=text,
                        context_json=(
                            context_json
                        ),
                        num_predict=(
                            _REMEMBER_NUM_PREDICT
                        ),
                    )
                )

                extraction_prompt = (
                    retry_prompt
                )

                interpretation = (
                    _compose_validated_remember_interpretation(
                        extraction_raw,
                        confidence=(
                            operation_confidence
                        ),
                    )
                )

            extraction_receipt = (
                self._stage_receipt(
                    stage=_REMEMBER_STAGE,
                    system_prompt=(
                        extraction_prompt
                    ),
                    schema=(
                        extraction_schema
                    ),
                    raw_output=(
                        extraction_raw
                    ),
                )
            )

        elif (
            operation
            is MemoryOperation.RECALL
        ):
            extraction_prompt = (
                trusted_memory_recall_extractor_system_prompt()
            )

            extraction_schema = (
                memory_recall_extraction_json_schema()
            )

            try:
                extraction_raw = (
                    self._invoke_stage(
                        stage=_RECALL_STAGE,
                        selected_operation=operation,
                        system_prompt=extraction_prompt,
                        schema=extraction_schema,
                        text=text,
                        context_json=context_json,
                        num_predict=_RECALL_NUM_PREDICT,
                    )
                )
                interpretation = (
                    _compose_validated_recall_interpretation(
                        extraction_raw,
                        confidence=operation_confidence,
                    )
                )
            except MemoryModelContractError as exc:
                if not isinstance(
                    exc.__cause__,
                    (
                        MemoryValidationError,
                        QwenMemoryModelMalformedOutputError,
                    ),
                ):
                    raise

                retry_prompt = _recall_structural_retry_prompt(
                    extraction_prompt,
                    validation_reason=str(exc.__cause__),
                )
                extraction_raw = self._invoke_stage(
                    stage=_RECALL_STAGE,
                    selected_operation=operation,
                    system_prompt=retry_prompt,
                    schema=extraction_schema,
                    text=text,
                    context_json=context_json,
                    num_predict=_RECALL_NUM_PREDICT,
                )
                extraction_prompt = retry_prompt
                interpretation = (
                    _compose_validated_recall_interpretation(
                        extraction_raw,
                        confidence=operation_confidence,
                    )
                )

            extraction_receipt = (
                self._stage_receipt(
                    stage=_RECALL_STAGE,
                    system_prompt=(
                        extraction_prompt
                    ),
                    schema=(
                        extraction_schema
                    ),
                    raw_output=(
                        extraction_raw
                    ),
                )
            )

        else:
            raise MemoryModelContractError(
                "unsupported two-stage operation"
            )

        generated_at = (
            self._clock()
        )

        if not isinstance(
            generated_at,
            datetime,
        ):
            raise MemoryInterpretationAdapterError(
                (
                    "trusted clock returned "
                    "non-datetime value"
                )
            )

        if (
            generated_at.tzinfo is None
            or generated_at.utcoffset()
            is None
        ):
            raise MemoryInterpretationAdapterError(
                (
                    "trusted clock returned "
                    "timezone-naive datetime"
                )
            )

        return TwoStageMemoryInterpretationEnvelope(
            interpreter_schema_version=(
                MEMORY_INTERPRETER_SCHEMA_VERSION
            ),
            interpreter_contract_version=(
                MEMORY_INTERPRETER_CONTRACT_VERSION
            ),
            memory_contract_version=(
                MEMORY_CONTRACT_VERSION
            ),
            execution_contract_version=(
                MEMORY_TWO_STAGE_EXECUTION_CONTRACT_VERSION
            ),
            model_id=self._model_id,
            generated_at=generated_at,
            request_sha256=(
                _sha256_text(
                    text
                )
            ),
            context_sha256=(
                _sha256_text(
                    context_json
                )
            ),
            operation_stage=(
                operation_receipt
            ),
            extraction_stage=(
                extraction_receipt
            ),
            interpretation=(
                interpretation
            ),
        )
