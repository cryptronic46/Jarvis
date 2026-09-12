from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, Protocol
import json

from .enums import (
    Cardinality,
    MemoryClass,
    MemoryNamespace,
    ValueType,
)
from .errors import (
    MemoryValidationError,
)
from .validation import (
    require_confidence,
    require_json,
    require_text,
)


MAX_MODEL_OUTPUT_CHARS = 131072
MAX_ENTITIES = 64
MAX_FACTS = 128
MAX_RELATIONS = 128
MAX_QUERY_PREDICATES = 128
MAX_AMBIGUITIES = 32


class MemoryOperation(StrEnum):
    REMEMBER = "REMEMBER"
    RECALL = "RECALL"
    FORGET = "FORGET"
    RESOLVE_CONFLICT = "RESOLVE_CONFLICT"
    NONE = "NONE"


class QueryTemporalMode(StrEnum):
    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    AS_OF_REVISION = "AS_OF_REVISION"


class RecallRetrievalScope(StrEnum):
    SELECTOR_SCOPED = "SELECTOR_SCOPED"
    FULL_SUBJECT_PROFILE = "FULL_SUBJECT_PROFILE"


MEMORY_MODEL_CONTEXT_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class InterpreterContext:
    locale: str = "pt-PT"
    default_subject_ref: str = "owner"
    current_time: datetime | None = None
    known_entity_refs: tuple[str, ...] = ()

    def __post_init__(
        self,
    ) -> None:
        require_text(
            self.locale,
            "InterpreterContext.locale",
        )

        require_text(
            self.default_subject_ref,
            (
                "InterpreterContext."
                "default_subject_ref"
            ),
        )

        if (
            self.current_time
            is not None
        ):
            if (
                self.current_time.tzinfo
                is None
                or self.current_time
                .utcoffset()
                is None
            ):
                raise MemoryValidationError(
                    "InterpreterContext.current_time "
                    "must be timezone-aware"
                )

        if not isinstance(
            self.known_entity_refs,
            tuple,
        ):
            raise MemoryValidationError(
                "InterpreterContext."
                "known_entity_refs must be tuple"
            )

        checked_refs = []

        for local_ref in (
            self.known_entity_refs
        ):
            if not isinstance(
                local_ref,
                str,
            ):
                raise MemoryValidationError(
                    "InterpreterContext."
                    "known_entity_refs values "
                    "must be text"
                )

            require_text(
                local_ref,
                (
                    "InterpreterContext."
                    "known_entity_refs"
                ),
            )

            if (
                local_ref
                != local_ref.strip()
            ):
                raise MemoryValidationError(
                    "InterpreterContext."
                    "known_entity_refs must not "
                    "contain surrounding whitespace"
                )

            checked_refs.append(
                local_ref
            )

        if (
            len(
                set(
                    checked_refs
                )
            )
            != len(
                checked_refs
            )
        ):
            raise MemoryValidationError(
                "InterpreterContext."
                "known_entity_refs must be unique"
            )


@dataclass(frozen=True, slots=True)
class EntityProposal:
    local_ref: str
    canonical_name: str
    entity_type: str
    namespace_hint: MemoryNamespace | None = None
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_text(
            self.local_ref,
            "EntityProposal.local_ref",
        )

        require_text(
            self.canonical_name,
            "EntityProposal.canonical_name",
        )

        require_text(
            self.entity_type,
            "EntityProposal.entity_type",
        )

        if (
            len(
                set(
                    self.aliases
                )
            )
            != len(
                self.aliases
            )
        ):
            raise MemoryValidationError(
                "EntityProposal.aliases "
                "must be unique"
            )



@dataclass(frozen=True, slots=True)
class PropertyProposal:
    local_ref: str
    semantic_labels: tuple[str, ...]
    semantic_type: str
    cardinality: Cardinality
    value_type: ValueType | None = None

    def __post_init__(self) -> None:
        require_text(
            self.local_ref,
            "PropertyProposal.local_ref",
        )

        if (
            self.local_ref
            != self.local_ref.strip()
        ):
            raise MemoryValidationError(
                "PropertyProposal.local_ref "
                "must not contain surrounding whitespace"
            )

        if not isinstance(
            self.semantic_labels,
            tuple,
        ):
            raise MemoryValidationError(
                "PropertyProposal.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise MemoryValidationError(
                "PropertyProposal.semantic_labels "
                "must not be empty"
            )

        checked_labels = []

        for label in self.semantic_labels:
            if not isinstance(
                label,
                str,
            ):
                raise MemoryValidationError(
                    "PropertyProposal.semantic_labels "
                    "values must be text"
                )

            require_text(
                label,
                "PropertyProposal.semantic_labels",
            )

            if (
                label
                != label.strip()
            ):
                raise MemoryValidationError(
                    "PropertyProposal.semantic_labels "
                    "must not contain surrounding whitespace"
                )

            checked_labels.append(
                label
            )

        if (
            len(set(checked_labels))
            != len(checked_labels)
        ):
            raise MemoryValidationError(
                "PropertyProposal.semantic_labels "
                "must be unique"
            )

        require_text(
            self.semantic_type,
            "PropertyProposal.semantic_type",
        )

        if (
            self.semantic_type
            != self.semantic_type.strip()
        ):
            raise MemoryValidationError(
                "PropertyProposal.semantic_type "
                "must not contain surrounding whitespace"
            )

        if not isinstance(
            self.cardinality,
            Cardinality,
        ):
            raise MemoryValidationError(
                "PropertyProposal.cardinality "
                "must be Cardinality"
            )

        if (
            self.value_type
            is not None
            and not isinstance(
                self.value_type,
                ValueType,
            )
        ):
            raise MemoryValidationError(
                "PropertyProposal.value_type "
                "must be ValueType or None"
            )


@dataclass(frozen=True, slots=True)
class FactProposal:
    subject_ref: str
    property_ref: str
    value: Any
    memory_class: MemoryClass
    confidence: float
    unit: str | None = None
    value_entity_ref: str | None = None
    raw_representation: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None

    def __post_init__(self) -> None:
        require_text(
            self.subject_ref,
            "FactProposal.subject_ref",
        )

        require_text(
            self.property_ref,
            "FactProposal.property_ref",
        )

        require_confidence(
            self.confidence
        )

        require_json(
            self.value,
            "FactProposal.value",
        )

        if (
            self.value_entity_ref
            is not None
        ):
            require_text(
                self.value_entity_ref,
                "FactProposal.value_entity_ref",
            )




@dataclass(frozen=True, slots=True)
class RelationProposal:
    source_ref: str
    property_ref: str
    target_ref: str
    memory_class: MemoryClass
    confidence: float
    valid_from: str | None = None
    valid_until: str | None = None

    def __post_init__(self) -> None:
        require_text(
            self.source_ref,
            "RelationProposal.source_ref",
        )

        require_text(
            self.property_ref,
            "RelationProposal.property_ref",
        )

        require_text(
            self.target_ref,
            "RelationProposal.target_ref",
        )

        require_confidence(
            self.confidence
        )




@dataclass(frozen=True, slots=True)
class PropertyQueryProposal:
    semantic_labels: tuple[str, ...]
    semantic_type: str

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.semantic_labels,
            tuple,
        ):
            raise MemoryValidationError(
                "PropertyQueryProposal.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise MemoryValidationError(
                "PropertyQueryProposal.semantic_labels "
                "must not be empty"
            )

        checked_labels = []

        for label in (
            self.semantic_labels
        ):
            if not isinstance(
                label,
                str,
            ):
                raise MemoryValidationError(
                    "PropertyQueryProposal.semantic_labels "
                    "values must be text"
                )

            require_text(
                label,
                (
                    "PropertyQueryProposal."
                    "semantic_labels"
                ),
            )

            if label != label.strip():
                raise MemoryValidationError(
                    "PropertyQueryProposal.semantic_labels "
                    "must not contain surrounding whitespace"
                )

            checked_labels.append(
                label
            )

        if (
            len(
                set(
                    checked_labels
                )
            )
            != len(
                checked_labels
            )
        ):
            raise MemoryValidationError(
                "PropertyQueryProposal.semantic_labels "
                "must be unique"
            )

        require_text(
            self.semantic_type,
            (
                "PropertyQueryProposal."
                "semantic_type"
            ),
        )

        if (
            self.semantic_type
            != self.semantic_type.strip()
        ):
            raise MemoryValidationError(
                "PropertyQueryProposal.semantic_type "
                "must not contain surrounding whitespace"
            )



@dataclass(
    frozen=True,
    slots=True,
)
class EntityQueryProposal:
    local_ref: str
    semantic_labels: tuple[str, ...]
    semantic_type: str

    def __post_init__(
        self,
    ) -> None:
        require_text(
            self.local_ref,
            (
                "EntityQueryProposal."
                "local_ref"
            ),
        )

        if (
            self.local_ref
            != self.local_ref.strip()
        ):
            raise MemoryValidationError(
                "EntityQueryProposal.local_ref "
                "must not contain surrounding whitespace"
            )

        if not isinstance(
            self.semantic_labels,
            tuple,
        ):
            raise MemoryValidationError(
                "EntityQueryProposal.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise MemoryValidationError(
                "EntityQueryProposal.semantic_labels "
                "must not be empty"
            )

        checked_labels = []

        for label in (
            self.semantic_labels
        ):
            if not isinstance(
                label,
                str,
            ):
                raise MemoryValidationError(
                    "EntityQueryProposal.semantic_labels "
                    "values must be text"
                )

            require_text(
                label,
                (
                    "EntityQueryProposal."
                    "semantic_labels"
                ),
            )

            if (
                label
                != label.strip()
            ):
                raise MemoryValidationError(
                    "EntityQueryProposal.semantic_labels "
                    "must not contain surrounding whitespace"
                )

            checked_labels.append(
                label
            )

        if (
            len(
                set(
                    checked_labels
                )
            )
            != len(
                checked_labels
            )
        ):
            raise MemoryValidationError(
                "EntityQueryProposal.semantic_labels "
                "must be unique"
            )

        require_text(
            self.semantic_type,
            (
                "EntityQueryProposal."
                "semantic_type"
            ),
        )

        if (
            self.semantic_type
            != self.semantic_type.strip()
        ):
            raise MemoryValidationError(
                "EntityQueryProposal.semantic_type "
                "must not contain surrounding whitespace"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class MemoryQueryProposal:
    subject_refs: tuple[str, ...] = ()
    entity_queries: tuple[
        EntityQueryProposal,
        ...,
    ] = ()
    fact_properties: tuple[
        PropertyQueryProposal,
        ...,
    ] = ()
    relation_properties: tuple[
        PropertyQueryProposal,
        ...,
    ] = ()
    target_refs: tuple[str, ...] = ()
    retrieval_scope: RecallRetrievalScope = (
        RecallRetrievalScope.FULL_SUBJECT_PROFILE
    )
    temporal_mode: QueryTemporalMode = (
        QueryTemporalMode.CURRENT
    )
    as_of_revision: int | None = None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.entity_queries,
            tuple,
        ):
            raise MemoryValidationError(
                "MemoryQueryProposal.entity_queries "
                "must be tuple"
            )

        seen_entity_refs: set[str] = set()

        for item in (
            self.entity_queries
        ):
            if not isinstance(
                item,
                EntityQueryProposal,
            ):
                raise MemoryValidationError(
                    "MemoryQueryProposal.entity_queries "
                    "contains invalid entity query"
                )

            if (
                item.local_ref
                in seen_entity_refs
            ):
                raise MemoryValidationError(
                    "MemoryQueryProposal.entity_queries "
                    "contains duplicate local_ref"
                )

            seen_entity_refs.add(
                item.local_ref
            )

            if (
                item.local_ref
                not in self.subject_refs
                and item.local_ref
                not in self.target_refs
            ):
                raise MemoryValidationError(
                    "MemoryQueryProposal.entity_queries "
                    "contains unused local_ref"
                )

        for (
            field_name,
            values,
        ) in (
            (
                "fact_properties",
                self.fact_properties,
            ),
            (
                "relation_properties",
                self.relation_properties,
            ),
        ):
            if not isinstance(
                values,
                tuple,
            ):
                raise MemoryValidationError(
                    (
                        "MemoryQueryProposal."
                        f"{field_name} must be tuple"
                    )
                )

            for item in values:
                if not isinstance(
                    item,
                    PropertyQueryProposal,
                ):
                    raise MemoryValidationError(
                        (
                            "MemoryQueryProposal."
                            f"{field_name} contains "
                            "invalid property proposal"
                        )
                    )

        if not isinstance(
            self.retrieval_scope,
            RecallRetrievalScope,
        ):
            raise MemoryValidationError(
                "MemoryQueryProposal.retrieval_scope "
                "must be RecallRetrievalScope"
            )

        if (
            self.retrieval_scope
            is RecallRetrievalScope.SELECTOR_SCOPED
            and not (
                self.fact_properties
                or self.relation_properties
                or self.target_refs
            )
        ):
            raise MemoryValidationError(
                "SELECTOR_SCOPED retrieval_scope "
                "requires at least one selector"
            )

        if (
            self.temporal_mode
            is QueryTemporalMode
            .AS_OF_REVISION
        ):
            if (
                self.as_of_revision
                is None
                or self.as_of_revision
                < 0
            ):
                raise MemoryValidationError(
                    "AS_OF_REVISION requires "
                    "as_of_revision >= 0"
                )

        elif (
            self.as_of_revision
            is not None
        ):
            raise MemoryValidationError(
                "as_of_revision requires "
                "temporal_mode=AS_OF_REVISION"
            )






@dataclass(frozen=True, slots=True)
class MemoryInterpretation:
    operation: MemoryOperation
    confidence: float
    explicit_memory_request: bool
    entities: tuple[EntityProposal, ...] = ()
    fact_properties: tuple[PropertyProposal, ...] = ()
    relation_properties: tuple[PropertyProposal, ...] = ()
    facts: tuple[FactProposal, ...] = ()
    relations: tuple[RelationProposal, ...] = ()
    query: MemoryQueryProposal | None = None
    needs_confirmation: bool = False
    ambiguities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_confidence(
            self.confidence
        )

        fact_property_map = {}
        relation_property_map = {}

        for proposal in self.fact_properties:
            if not isinstance(
                proposal,
                PropertyProposal,
            ):
                raise MemoryValidationError(
                    "fact_properties contains "
                    "invalid PropertyProposal"
                )

            if (
                proposal.value_type
                is None
            ):
                raise MemoryValidationError(
                    "fact property requires value_type"
                )

            if (
                proposal.local_ref
                in fact_property_map
            ):
                raise MemoryValidationError(
                    "duplicate fact property local_ref"
                )

            fact_property_map[
                proposal.local_ref
            ] = proposal

        for proposal in self.relation_properties:
            if not isinstance(
                proposal,
                PropertyProposal,
            ):
                raise MemoryValidationError(
                    "relation_properties contains "
                    "invalid PropertyProposal"
                )

            if (
                proposal.value_type
                is not None
            ):
                raise MemoryValidationError(
                    "relation property forbids value_type"
                )

            if (
                proposal.local_ref
                in relation_property_map
            ):
                raise MemoryValidationError(
                    "duplicate relation property local_ref"
                )

            relation_property_map[
                proposal.local_ref
            ] = proposal

        overlap = (
            set(fact_property_map)
            & set(relation_property_map)
        )

        if overlap:
            raise MemoryValidationError(
                "property local_ref cannot be shared "
                "across fact and relation properties"
            )

        used_fact_properties = set()
        used_relation_properties = set()

        for fact in self.facts:
            if not isinstance(
                fact,
                FactProposal,
            ):
                raise MemoryValidationError(
                    "facts contains invalid FactProposal"
                )

            property_proposal = (
                fact_property_map.get(
                    fact.property_ref
                )
            )

            if property_proposal is None:
                if (
                    fact.property_ref
                    in relation_property_map
                ):
                    raise MemoryValidationError(
                        "fact property_ref resolves "
                        "to relation property"
                    )

                raise MemoryValidationError(
                    "fact property_ref does not resolve"
                )

            used_fact_properties.add(
                fact.property_ref
            )

            if (
                property_proposal.value_type
                is ValueType.ENTITY_REF
            ):
                require_text(
                    fact.value_entity_ref
                    or "",
                    "FactProposal.value_entity_ref",
                )

                if not isinstance(
                    fact.value,
                    str,
                ):
                    raise MemoryValidationError(
                        "ENTITY_REF fact value "
                        "must be text"
                    )

            elif (
                fact.value_entity_ref
                is not None
            ):
                raise MemoryValidationError(
                    "value_entity_ref requires "
                    "ENTITY_REF fact property"
                )

        for relation in self.relations:
            if not isinstance(
                relation,
                RelationProposal,
            ):
                raise MemoryValidationError(
                    "relations contains invalid "
                    "RelationProposal"
                )

            if (
                relation.property_ref
                not in relation_property_map
            ):
                if (
                    relation.property_ref
                    in fact_property_map
                ):
                    raise MemoryValidationError(
                        "relation property_ref resolves "
                        "to fact property"
                    )

                raise MemoryValidationError(
                    "relation property_ref "
                    "does not resolve"
                )

            used_relation_properties.add(
                relation.property_ref
            )

        if (
            set(fact_property_map)
            - used_fact_properties
        ) or (
            set(relation_property_map)
            - used_relation_properties
        ):
            raise MemoryValidationError(
                "unused property proposal"
            )

        if (
            self.operation
            is MemoryOperation.REMEMBER
            and not (
                self.entities
                or self.facts
                or self.relations
            )
        ):
            raise MemoryValidationError(
                "REMEMBER requires at least "
                "one structured proposal"
            )

        if (
            self.operation
            is MemoryOperation.REMEMBER
            and self.query is not None
        ):
            raise MemoryValidationError(
                "REMEMBER cannot carry query"
            )

        if (
            self.operation
            is MemoryOperation.RECALL
            and self.query is None
        ):
            raise MemoryValidationError(
                "RECALL requires query"
            )

        if (
            self.operation
            is MemoryOperation.RECALL
            and (
                self.entities
                or self.fact_properties
                or self.relation_properties
                or self.facts
                or self.relations
            )
        ):
            raise MemoryValidationError(
                "RECALL cannot carry "
                "write proposals"
            )

        if (
            self.operation
            is MemoryOperation.NONE
            and (
                self.entities
                or self.fact_properties
                or self.relation_properties
                or self.facts
                or self.relations
                or self.query
            )
        ):
            raise MemoryValidationError(
                "NONE cannot carry "
                "memory proposals"
            )



class SemanticMemoryModel(Protocol):
    def generate_memory_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
    ) -> str:
        ...


_FORBIDDEN_MODEL_KEYS = frozenset({
    "id",
    "entity_id",
    "fact_id",
    "relation_id",
    "episode_id",
    "transaction_id",
    "actor_entity_id",
    "authority",
    "source_type",
    "source_episode_ids",
    "source_fact_ids",
    "supersedes_fact_ids",
    "supersedes_relation_ids",
    "contradicts_fact_ids",
    "contradicts_relation_ids",
    "canonical_revision",
    "created_revision",
    "status",
    "permission",
    "permissions",
})



_ROOT_KEYS = frozenset({
    "operation",
    "confidence",
    "explicit_memory_request",
    "entities",
    "fact_properties",
    "relation_properties",
    "facts",
    "relations",
    "query",
    "needs_confirmation",
    "ambiguities",
})



_ENTITY_KEYS = frozenset({
    "local_ref",
    "canonical_name",
    "entity_type",
    "namespace_hint",
    "aliases",
})



_FACT_PROPERTY_KEYS = frozenset({
    "local_ref",
    "semantic_labels",
    "semantic_type",
    "cardinality",
    "value_type",
})

_RELATION_PROPERTY_KEYS = frozenset({
    "local_ref",
    "semantic_labels",
    "semantic_type",
    "cardinality",
})

_FACT_KEYS = frozenset({
    "subject_ref",
    "property_ref",
    "value",
    "memory_class",
    "confidence",
    "unit",
    "value_entity_ref",
    "raw_representation",
    "valid_from",
    "valid_until",
})




_RELATION_KEYS = frozenset({
    "source_ref",
    "property_ref",
    "target_ref",
    "memory_class",
    "confidence",
    "valid_from",
    "valid_until",
})



_QUERY_KEYS = frozenset(
    {
        'subject_refs',
        'entity_queries',
        'fact_properties',
        'relation_properties',
        'target_refs',
        'retrieval_scope',
        'temporal_mode',
        'as_of_revision',
    }
)


def _strict_object(
    value: Any,
    *,
    name: str,
    allowed_keys: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(
        value,
        dict,
    ):
        raise MemoryValidationError(
            f"{name} must be an object"
        )

    keys = set(
        value
    )

    forbidden = sorted(
        keys
        & _FORBIDDEN_MODEL_KEYS
    )

    if forbidden:
        raise MemoryValidationError(
            (
                f"{name} contains "
                "forbidden model-controlled keys: "
                + ", ".join(
                    forbidden
                )
            )
        )

    unknown = sorted(
        keys
        - allowed_keys
    )

    if unknown:
        raise MemoryValidationError(
            (
                f"{name} contains unknown keys: "
                + ", ".join(
                    unknown
                )
            )
        )

    return dict(
        value
    )


def _scan_forbidden_keys(
    value: Any,
    *,
    path: str = "$",
) -> None:
    if isinstance(
        value,
        dict,
    ):
        for key, child in value.items():
            key_text = str(
                key
            )

            if (
                key_text
                in _FORBIDDEN_MODEL_KEYS
            ):
                raise MemoryValidationError(
                    (
                        "model attempted to control "
                        f"forbidden field {path}.{key_text}"
                    )
                )

            _scan_forbidden_keys(
                child,
                path=(
                    path
                    + "."
                    + key_text
                ),
            )

    elif isinstance(
        value,
        list,
    ):
        for index, child in enumerate(
            value
        ):
            _scan_forbidden_keys(
                child,
                path=(
                    f"{path}[{index}]"
                ),
            )


def _string_tuple(
    value: Any,
    *,
    name: str,
    limit: int,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if not isinstance(
        value,
        list,
    ):
        raise MemoryValidationError(
            f"{name} must be an array"
        )

    if len(value) > limit:
        raise MemoryValidationError(
            f"{name} exceeds limit {limit}"
        )

    result = tuple(
        str(
            item
        ).strip()
        for item
        in value
    )

    if any(
        not item
        for item
        in result
    ):
        raise MemoryValidationError(
            f"{name} contains empty values"
        )

    if (
        len(
            set(
                result
            )
        )
        != len(
            result
        )
    ):
        raise MemoryValidationError(
            f"{name} must be unique"
        )

    return result


def _enum(
    enum_type,
    value: Any,
    *,
    name: str,
):
    try:
        return enum_type(
            str(
                value
            )
        )

    except ValueError as exc:
        raise MemoryValidationError(
            f"invalid {name}: {value!r}"
        ) from exc


def _bool(
    value: Any,
    *,
    name: str,
) -> bool:
    if not isinstance(
        value,
        bool,
    ):
        raise MemoryValidationError(
            f"{name} must be boolean"
        )

    return value


def _float(
    value: Any,
    *,
    name: str,
) -> float:
    if isinstance(
        value,
        bool,
    ):
        raise MemoryValidationError(
            f"{name} must be numeric"
        )

    try:
        result = float(
            value
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise MemoryValidationError(
            f"{name} must be numeric"
        ) from exc

    require_confidence(
        result
    )

    return result


def _optional_text(
    value: Any,
    *,
    name: str,
) -> str | None:
    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        raise MemoryValidationError(
            f"{name} must not be empty"
        )

    return text


def _parse_entity(
    raw: Any,
) -> EntityProposal:
    data = _strict_object(
        raw,
        name="entity",
        allowed_keys=_ENTITY_KEYS,
    )

    aliases = _string_tuple(
        data.get(
            "aliases",
            [],
        ),
        name="entity.aliases",
        limit=32,
    )

    namespace_raw = data.get(
        "namespace_hint"
    )

    namespace = (
        None
        if namespace_raw is None
        else _enum(
            MemoryNamespace,
            namespace_raw,
            name=(
                "entity.namespace_hint"
            ),
        )
    )

    return EntityProposal(
        local_ref=str(
            data.get(
                "local_ref",
                "",
            )
        ).strip(),
        canonical_name=str(
            data.get(
                "canonical_name",
                "",
            )
        ).strip(),
        entity_type=str(
            data.get(
                "entity_type",
                "",
            )
        ).strip(),
        namespace_hint=namespace,
        aliases=aliases,
    )



def _parse_property_proposal(
    raw: Any,
    *,
    name: str,
    value_type_required: bool,
) -> PropertyProposal:
    allowed_keys = (
        _FACT_PROPERTY_KEYS
        if value_type_required
        else _RELATION_PROPERTY_KEYS
    )

    data = _strict_object(
        raw,
        name=name,
        allowed_keys=allowed_keys,
    )

    required = [
        "local_ref",
        "semantic_labels",
        "semantic_type",
        "cardinality",
    ]

    if value_type_required:
        required.append(
            "value_type"
        )

    for field_name in required:
        if field_name not in data:
            raise MemoryValidationError(
                f"{name}.{field_name} is required"
            )

    local_ref = data[
        "local_ref"
    ]

    semantic_type = data[
        "semantic_type"
    ]

    if not isinstance(
        local_ref,
        str,
    ):
        raise MemoryValidationError(
            f"{name}.local_ref must be text"
        )

    if not isinstance(
        semantic_type,
        str,
    ):
        raise MemoryValidationError(
            f"{name}.semantic_type must be text"
        )

    return PropertyProposal(
        local_ref=local_ref,
        semantic_labels=_string_tuple(
            data[
                "semantic_labels"
            ],
            name=(
                f"{name}.semantic_labels"
            ),
            limit=MAX_QUERY_PREDICATES,
        ),
        semantic_type=semantic_type,
        cardinality=_enum(
            Cardinality,
            data.get(
                "cardinality"
            ),
            name=(
                f"{name}.cardinality"
            ),
        ),
        value_type=(
            _enum(
                ValueType,
                data.get(
                    "value_type"
                ),
                name=(
                    f"{name}.value_type"
                ),
            )
            if value_type_required
            else None
        ),
    )


def _parse_fact(
    raw: Any,
) -> FactProposal:
    data = _strict_object(
        raw,
        name="fact",
        allowed_keys=_FACT_KEYS,
    )

    if "value" not in data:
        raise MemoryValidationError(
            "fact.value is required"
        )

    return FactProposal(
        subject_ref=str(
            data.get(
                "subject_ref",
                "",
            )
        ).strip(),
        property_ref=str(
            data.get(
                "property_ref",
                "",
            )
        ).strip(),
        value=data[
            "value"
        ],
        memory_class=_enum(
            MemoryClass,
            data.get(
                "memory_class"
            ),
            name="fact.memory_class",
        ),
        confidence=_float(
            data.get(
                "confidence"
            ),
            name="fact.confidence",
        ),
        unit=_optional_text(
            data.get(
                "unit"
            ),
            name="fact.unit",
        ),
        value_entity_ref=_optional_text(
            data.get(
                "value_entity_ref"
            ),
            name=(
                "fact.value_entity_ref"
            ),
        ),
        raw_representation=_optional_text(
            data.get(
                "raw_representation"
            ),
            name=(
                "fact.raw_representation"
            ),
        ),
        valid_from=_optional_text(
            data.get(
                "valid_from"
            ),
            name="fact.valid_from",
        ),
        valid_until=_optional_text(
            data.get(
                "valid_until"
            ),
            name="fact.valid_until",
        ),
    )




def _parse_relation(
    raw: Any,
) -> RelationProposal:
    data = _strict_object(
        raw,
        name="relation",
        allowed_keys=_RELATION_KEYS,
    )

    return RelationProposal(
        source_ref=str(
            data.get(
                "source_ref",
                "",
            )
        ).strip(),
        property_ref=str(
            data.get(
                "property_ref",
                "",
            )
        ).strip(),
        target_ref=str(
            data.get(
                "target_ref",
                "",
            )
        ).strip(),
        memory_class=_enum(
            MemoryClass,
            data.get(
                "memory_class"
            ),
            name=(
                "relation.memory_class"
            ),
        ),
        confidence=_float(
            data.get(
                "confidence"
            ),
            name=(
                "relation.confidence"
            ),
        ),
        valid_from=_optional_text(
            data.get(
                "valid_from"
            ),
            name=(
                "relation.valid_from"
            ),
        ),
        valid_until=_optional_text(
            data.get(
                "valid_until"
            ),
            name=(
                "relation.valid_until"
            ),
        ),
    )




def _query_is_structurally_empty(
    raw: Any,
) -> bool:
    """Recognize an optional query carrying no retrieval semantics.

    JSON-schema constrained local decoders may materialize optional
    objects with empty structural collections or the default CURRENT
    temporal mode. Such a shape is equivalent to an omitted optional
    query.

    Malformed, unknown or semantically meaningful fields are never
    normalized away.
    """

    if not isinstance(
        raw,
        dict,
    ):
        return False

    if any(
        key not in _QUERY_KEYS
        for key
        in raw
    ):
        return False

    for key in (
        "subject_refs",
        "fact_properties",
        "relation_properties",
        "target_refs",
    ):
        if key not in raw:
            continue

        value = raw[
            key
        ]

        if (
            not isinstance(
                value,
                list,
            )
            or value
        ):
            return False

    if (
        "temporal_mode"
        in raw
        and raw[
            "temporal_mode"
        ]
        != QueryTemporalMode
        .CURRENT
        .value
    ):
        return False

    if (
        raw.get(
            "as_of_revision"
        )
        is not None
    ):
        return False

    return True





def _parse_entity_query(
    raw: Any,
    *,
    name: str,
) -> EntityQueryProposal:
    data = _strict_object(
        raw,
        name=name,
        allowed_keys=frozenset(
            {
                "local_ref",
                "semantic_labels",
                "semantic_type",
            }
        ),
    )

    for required in (
        "local_ref",
        "semantic_labels",
        "semantic_type",
    ):
        if required not in data:
            raise MemoryValidationError(
                (
                    f"{name}.{required} "
                    "is required"
                )
            )

    local_ref = data[
        "local_ref"
    ]

    semantic_type = data[
        "semantic_type"
    ]

    if not isinstance(
        local_ref,
        str,
    ):
        raise MemoryValidationError(
            f"{name}.local_ref must be text"
        )

    if not isinstance(
        semantic_type,
        str,
    ):
        raise MemoryValidationError(
            f"{name}.semantic_type must be text"
        )

    return EntityQueryProposal(
        local_ref=local_ref,
        semantic_labels=_string_tuple(
            data[
                "semantic_labels"
            ],
            name=(
                f"{name}.semantic_labels"
            ),
            limit=MAX_QUERY_PREDICATES,
        ),
        semantic_type=semantic_type,
    )


def _parse_property_query(
    raw: Any,
    *,
    name: str,
) -> PropertyQueryProposal:
    data = _strict_object(
        raw,
        name=name,
        allowed_keys=frozenset(
            {
                "semantic_labels",
                "semantic_type",
            }
        ),
    )

    if (
        "semantic_labels"
        not in data
    ):
        raise MemoryValidationError(
            (
                f"{name}.semantic_labels "
                "is required"
            )
        )

    if (
        "semantic_type"
        not in data
    ):
        raise MemoryValidationError(
            (
                f"{name}.semantic_type "
                "is required"
            )
        )

    return PropertyQueryProposal(
        semantic_labels=_string_tuple(
            data[
                "semantic_labels"
            ],
            name=(
                f"{name}.semantic_labels"
            ),
            limit=MAX_QUERY_PREDICATES,
        ),
        semantic_type=str(
            data[
                "semantic_type"
            ]
        ),
    )



def _parse_query(
    raw: Any,
) -> MemoryQueryProposal:
    data = _strict_object(
        raw,
        name="query",
        allowed_keys=_QUERY_KEYS,
    )

    retrieval_scope = _enum(
        RecallRetrievalScope,
        data.get(
            "retrieval_scope",
            RecallRetrievalScope
            .FULL_SUBJECT_PROFILE
            .value,
        ),
        name="query.retrieval_scope",
    )

    temporal_mode = _enum(
        QueryTemporalMode,
        data.get(
            "temporal_mode",
            QueryTemporalMode
            .CURRENT
            .value,
        ),
        name="query.temporal_mode",
    )

    revision_raw = data.get(
        "as_of_revision"
    )

    revision = None

    if revision_raw is not None:
        if isinstance(
            revision_raw,
            bool,
        ):
            raise MemoryValidationError(
                "query.as_of_revision "
                "must be integer"
            )

        try:
            revision = int(
                revision_raw
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise MemoryValidationError(
                "query.as_of_revision "
                "must be integer"
            ) from exc

    entity_raw = data.get(
        "entity_queries",
        [],
    )

    fact_raw = data.get(
        "fact_properties",
        [],
    )

    relation_raw = data.get(
        "relation_properties",
        [],
    )

    if not isinstance(
        entity_raw,
        list,
    ):
        raise MemoryValidationError(
            "query.entity_queries "
            "must be an array"
        )

    if not isinstance(
        fact_raw,
        list,
    ):
        raise MemoryValidationError(
            "query.fact_properties "
            "must be an array"
        )

    if not isinstance(
        relation_raw,
        list,
    ):
        raise MemoryValidationError(
            "query.relation_properties "
            "must be an array"
        )

    if (
        len(
            entity_raw
        )
        > 64
    ):
        raise MemoryValidationError(
            "query.entity_queries "
            "exceeds limit"
        )

    if (
        len(
            fact_raw
        )
        > MAX_QUERY_PREDICATES
    ):
        raise MemoryValidationError(
            "query.fact_properties "
            "exceeds limit"
        )

    if (
        len(
            relation_raw
        )
        > MAX_QUERY_PREDICATES
    ):
        raise MemoryValidationError(
            "query.relation_properties "
            "exceeds limit"
        )

    return MemoryQueryProposal(
        subject_refs=_string_tuple(
            data.get(
                "subject_refs",
                [],
            ),
            name=(
                "query.subject_refs"
            ),
            limit=64,
        ),
        entity_queries=tuple(
            _parse_entity_query(
                item,
                name=(
                    "query.entity_queries"
                    f"[{index}]"
                ),
            )
            for index, item
            in enumerate(
                entity_raw
            )
        ),
        fact_properties=tuple(
            _parse_property_query(
                item,
                name=(
                    "query.fact_properties"
                    f"[{index}]"
                ),
            )
            for index, item
            in enumerate(
                fact_raw
            )
        ),
        relation_properties=tuple(
            _parse_property_query(
                item,
                name=(
                    "query.relation_properties"
                    f"[{index}]"
                ),
            )
            for index, item
            in enumerate(
                relation_raw
            )
        ),
        target_refs=_string_tuple(
            data.get(
                "target_refs",
                [],
            ),
            name=(
                "query.target_refs"
            ),
            limit=64,
        ),
        retrieval_scope=retrieval_scope,
        temporal_mode=temporal_mode,
        as_of_revision=revision,
    )





def parse_memory_interpretation(
    raw_output: str,
) -> MemoryInterpretation:
    if not isinstance(
        raw_output,
        str,
    ):
        raise MemoryValidationError(
            "model output must be text"
        )

    if (
        len(raw_output)
        > MAX_MODEL_OUTPUT_CHARS
    ):
        raise MemoryValidationError(
            "model output exceeds size limit"
        )

    try:
        raw = json.loads(
            raw_output
        )

    except json.JSONDecodeError as exc:
        raise MemoryValidationError(
            "model output is not valid JSON"
        ) from exc

    _scan_forbidden_keys(raw)

    data = _strict_object(
        raw,
        name="root",
        allowed_keys=_ROOT_KEYS,
    )

    operation = _enum(
        MemoryOperation,
        data.get(
            "operation"
        ),
        name="operation",
    )

    entities_raw = data.get(
        "entities",
        [],
    )

    fact_properties_raw = data.get(
        "fact_properties",
        [],
    )

    relation_properties_raw = data.get(
        "relation_properties",
        [],
    )

    facts_raw = data.get(
        "facts",
        [],
    )

    relations_raw = data.get(
        "relations",
        [],
    )

    for (
        field_name,
        raw_values,
    ) in (
        (
            "entities",
            entities_raw,
        ),
        (
            "fact_properties",
            fact_properties_raw,
        ),
        (
            "relation_properties",
            relation_properties_raw,
        ),
        (
            "facts",
            facts_raw,
        ),
        (
            "relations",
            relations_raw,
        ),
    ):
        if not isinstance(
            raw_values,
            list,
        ):
            raise MemoryValidationError(
                f"{field_name} must be an array"
            )

    if (
        len(entities_raw)
        > MAX_ENTITIES
    ):
        raise MemoryValidationError(
            "entities exceeds limit"
        )

    if (
        len(fact_properties_raw)
        > MAX_FACTS
    ):
        raise MemoryValidationError(
            "fact_properties exceeds limit"
        )

    if (
        len(relation_properties_raw)
        > MAX_RELATIONS
    ):
        raise MemoryValidationError(
            "relation_properties exceeds limit"
        )

    if (
        len(facts_raw)
        > MAX_FACTS
    ):
        raise MemoryValidationError(
            "facts exceeds limit"
        )

    if (
        len(relations_raw)
        > MAX_RELATIONS
    ):
        raise MemoryValidationError(
            "relations exceeds limit"
        )

    query_raw = data.get(
        "query"
    )

    query = (
        None
        if (
            query_raw is None
            or _query_is_structurally_empty(
                query_raw
            )
        )
        else _parse_query(
            query_raw
        )
    )

    ambiguities = _string_tuple(
        data.get(
            "ambiguities",
            [],
        ),
        name="ambiguities",
        limit=MAX_AMBIGUITIES,
    )

    return MemoryInterpretation(
        operation=operation,
        confidence=_float(
            data.get(
                "confidence"
            ),
            name="confidence",
        ),
        explicit_memory_request=_bool(
            data.get(
                "explicit_memory_request",
                False,
            ),
            name=(
                "explicit_memory_request"
            ),
        ),
        entities=tuple(
            _parse_entity(item)
            for item in entities_raw
        ),
        fact_properties=tuple(
            _parse_property_proposal(
                item,
                name=(
                    "fact_properties"
                    f"[{index}]"
                ),
                value_type_required=True,
            )
            for index, item
            in enumerate(
                fact_properties_raw
            )
        ),
        relation_properties=tuple(
            _parse_property_proposal(
                item,
                name=(
                    "relation_properties"
                    f"[{index}]"
                ),
                value_type_required=False,
            )
            for index, item
            in enumerate(
                relation_properties_raw
            )
        ),
        facts=tuple(
            _parse_fact(item)
            for item in facts_raw
        ),
        relations=tuple(
            _parse_relation(item)
            for item in relations_raw
        ),
        query=query,
        needs_confirmation=_bool(
            data.get(
                "needs_confirmation",
                False,
            ),
            name=(
                "needs_confirmation"
            ),
        ),
        ambiguities=ambiguities,
    )




def memory_interpreter_system_prompt() -> str:
    return (
        "You are the semantic interpretation layer "
        "for JARVIS Memory 1.0. "
        "Interpret the user's meaning and return "
        "exactly one JSON object. "
        "Do not execute actions. "
        "Do not claim that anything was stored. "
        "Do not assign authority, source_type, status, "
        "canonical IDs, transaction IDs, provenance IDs, "
        "supersession IDs, conflict IDs, revisions, "
        "permissions, or security decisions. "
        "Those belong exclusively to the trusted Core. "
        "Use operation REMEMBER, RECALL, FORGET, "
        "RESOLVE_CONFLICT, or NONE. "
        "For semantic entities use temporary local_ref values. "
        "For REMEMBER, predicates are semantic machine-readable "
        "property descriptions and are not canonical IDs. "
        "For RECALL, represent each requested semantic property "
        "as one structured object containing semantic_labels and "
        "semantic_type. Multiple labels describing one property "
        "belong inside that one object; multiple property objects "
        "represent multiple requested properties. "
        "Never return canonical property IDs. "
        "Return JSON only, with no markdown and no prose "
        "outside the JSON object."
    )



class SemanticMemoryInterpreter:
    def __init__(
        self,
        model: SemanticMemoryModel,
    ) -> None:
        self._model = model

    def interpret(
        self,
        text: str,
        *,
        context: InterpreterContext | None = None,
    ) -> MemoryInterpretation:
        require_text(
            text,
            "SemanticMemoryInterpreter.text",
        )

        actual_context = (
            context
            or InterpreterContext()
        )

        context_payload = {
            "locale":
                actual_context.locale,
            "default_subject_ref":
                actual_context
                .default_subject_ref,
            "current_time":
                (
                    None
                    if actual_context
                    .current_time
                    is None
                    else actual_context
                    .current_time
                    .isoformat()
                ),
            "model_context_contract_version":
                MEMORY_MODEL_CONTEXT_CONTRACT_VERSION,
            "known_entity_refs":
                list(
                    actual_context
                    .known_entity_refs
                ),
        }

        raw_output = (
            self._model
            .generate_memory_json(
                system_prompt=(
                    memory_interpreter_system_prompt()
                ),
                user_text=text,
                context_json=json.dumps(
                    context_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(
                        ",",
                        ":",
                    ),
                ),
            )
        )

        return parse_memory_interpretation(
            raw_output
        )
