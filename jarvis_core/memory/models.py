from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .enums import (
    Cardinality,
    CommitStatus,
    MemoryAuthority,
    MemoryClass,
    MemoryNamespace,
    MemoryStatus,
    PropertyKind,
    SCHEMA_VERSION,
    SourceType,
    ValueType,
)
from .ids import new_memory_id
from .validation import (
    freeze_metadata,
    require_aware,
    require_confidence,
    require_json,
    require_predicate,
    require_text,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class MemoryValue:
    value_type: ValueType
    value: Any = None
    unit: str | None = None
    entity_id: str | None = None
    raw_representation: str | None = None

    def __post_init__(self) -> None:
        require_json(
            self.value,
            "MemoryValue.value",
        )

        if self.value_type is ValueType.ENTITY_REF:
            require_text(
                self.entity_id or "",
                "MemoryValue.entity_id",
            )

        elif self.entity_id is not None:
            raise ValueError(
                "entity_id requires value_type=ENTITY_REF"
            )


@dataclass(frozen=True, slots=True)
class CanonicalProperty:
    id: str
    kind: PropertyKind
    semantic_labels: tuple[str, ...]
    semantic_type: str
    cardinality: Cardinality
    value_type: ValueType | None
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: datetime = field(
        default_factory=utc_now
    )
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_predicate(
            self.id
        )

        if not isinstance(
            self.kind,
            PropertyKind,
        ):
            raise ValueError(
                "CanonicalProperty.kind "
                "must be PropertyKind"
            )

        require_text(
            self.semantic_type,
            "CanonicalProperty.semantic_type",
        )

        if not isinstance(
            self.semantic_labels,
            tuple,
        ):
            raise ValueError(
                "CanonicalProperty.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise ValueError(
                "CanonicalProperty.semantic_labels "
                "must not be empty"
            )

        for label in self.semantic_labels:
            require_text(
                label,
                "CanonicalProperty.semantic_labels",
            )

            if label != label.strip():
                raise ValueError(
                    "CanonicalProperty.semantic_labels "
                    "must not contain surrounding whitespace"
                )

        if (
            len(set(self.semantic_labels))
            != len(self.semantic_labels)
        ):
            raise ValueError(
                "CanonicalProperty.semantic_labels "
                "must be unique"
            )

        if not isinstance(
            self.cardinality,
            Cardinality,
        ):
            raise ValueError(
                "CanonicalProperty.cardinality "
                "must be Cardinality"
            )

        if self.kind is PropertyKind.FACT:
            if not isinstance(
                self.value_type,
                ValueType,
            ):
                raise ValueError(
                    "FACT property requires ValueType"
                )

        elif self.value_type is not None:
            raise ValueError(
                "RELATION property forbids value_type"
            )

        if not isinstance(
            self.status,
            MemoryStatus,
        ):
            raise ValueError(
                "CanonicalProperty.status "
                "must be MemoryStatus"
            )

        require_aware(
            self.created_at,
            "CanonicalProperty.created_at",
        )

@dataclass(frozen=True, slots=True)
class Entity:
    id: str
    namespace: MemoryNamespace
    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...] = ()
    status: MemoryStatus = MemoryStatus.ACTIVE
    created_at: datetime = field(
        default_factory=utc_now
    )
    updated_at: datetime = field(
        default_factory=utc_now
    )
    source_episode_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(
            self.id,
            "Entity.id",
        )
        require_text(
            self.canonical_name,
            "Entity.canonical_name",
        )
        require_text(
            self.entity_type,
            "Entity.entity_type",
        )
        require_aware(
            self.created_at,
            "Entity.created_at",
        )
        require_aware(
            self.updated_at,
            "Entity.updated_at",
        )
        require_confidence(
            self.confidence
        )

        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError(
                "Entity aliases must be unique"
            )

        if (
            len(set(self.source_episode_ids))
            != len(self.source_episode_ids)
        ):
            raise ValueError(
                "Entity source_episode_ids must be unique"
            )

        object.__setattr__(
            self,
            "metadata",
            freeze_metadata(
                self.metadata
            ),
        )

    @classmethod
    def create(
        cls,
        *,
        namespace: MemoryNamespace,
        canonical_name: str,
        entity_type: str,
        aliases: tuple[str, ...] = (),
        source_episode_ids: tuple[str, ...] = (),
        confidence: float = 1.0,
    ) -> "Entity":
        now = utc_now()

        return cls(
            id=new_memory_id(),
            namespace=namespace,
            canonical_name=canonical_name,
            entity_type=entity_type,
            aliases=aliases,
            created_at=now,
            updated_at=now,
            source_episode_ids=source_episode_ids,
            confidence=confidence,
        )


@dataclass(frozen=True, slots=True)
class MemoryEpisode:
    id: str
    occurred_at: datetime
    recorded_at: datetime
    source_type: SourceType
    raw_text: str
    content_hash: str
    conversation_id: str | None = None
    sequence: int | None = None
    speaker_entity_id: str | None = None
    normalized_text: str | None = None
    explicit_memory_request: bool = False
    subject_hints: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(
            self.id,
            "MemoryEpisode.id",
        )
        require_aware(
            self.occurred_at,
            "MemoryEpisode.occurred_at",
        )
        require_aware(
            self.recorded_at,
            "MemoryEpisode.recorded_at",
        )
        require_text(
            self.raw_text,
            "MemoryEpisode.raw_text",
        )
        require_text(
            self.content_hash,
            "MemoryEpisode.content_hash",
        )

        if (
            len(set(self.subject_hints))
            != len(self.subject_hints)
        ):
            raise ValueError(
                "MemoryEpisode subject_hints must be unique"
            )

        object.__setattr__(
            self,
            "metadata",
            freeze_metadata(
                self.metadata
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryFact:
    id: str
    subject_entity_id: str
    property_id: str
    value: MemoryValue
    memory_class: MemoryClass
    authority: MemoryAuthority
    confidence: float
    status: MemoryStatus
    recorded_at: datetime
    canonical_key: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_episode_ids: tuple[str, ...] = ()
    source_fact_ids: tuple[str, ...] = ()
    supersedes_fact_ids: tuple[str, ...] = ()
    contradicts_fact_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(
            self.id,
            "MemoryFact.id",
        )
        require_text(
            self.subject_entity_id,
            "MemoryFact.subject_entity_id",
        )
        require_predicate(
            self.property_id
        )
        require_confidence(
            self.confidence
        )
        require_aware(
            self.recorded_at,
            "MemoryFact.recorded_at",
        )
        require_aware(
            self.valid_from,
            "MemoryFact.valid_from",
        )
        require_aware(
            self.valid_until,
            "MemoryFact.valid_until",
        )

        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until
            < self.valid_from
        ):
            raise ValueError(
                "MemoryFact valid_until "
                "precedes valid_from"
            )

        require_text(
            self.canonical_key,
            "MemoryFact.canonical_key",
        )

        for field_name, values in (
            (
                "source_episode_ids",
                self.source_episode_ids,
            ),
            (
                "source_fact_ids",
                self.source_fact_ids,
            ),
            (
                "supersedes_fact_ids",
                self.supersedes_fact_ids,
            ),
            (
                "contradicts_fact_ids",
                self.contradicts_fact_ids,
            ),
        ):
            if (
                len(set(values))
                != len(values)
            ):
                raise ValueError(
                    f"MemoryFact "
                    f"{field_name} "
                    "must be unique"
                )

        object.__setattr__(
            self,
            "metadata",
            freeze_metadata(
                self.metadata
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryRelation:
    id: str
    source_entity_id: str
    property_id: str
    target_entity_id: str
    memory_class: MemoryClass
    authority: MemoryAuthority
    confidence: float
    status: MemoryStatus
    recorded_at: datetime
    canonical_key: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_episode_ids: tuple[str, ...] = ()
    supersedes_relation_ids: tuple[str, ...] = ()
    contradicts_relation_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(
        default_factory=dict
    )
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(
            self.id,
            "MemoryRelation.id",
        )
        require_text(
            self.source_entity_id,
            "MemoryRelation.source_entity_id",
        )
        require_text(
            self.target_entity_id,
            "MemoryRelation.target_entity_id",
        )
        require_predicate(
            self.property_id
        )
        require_confidence(
            self.confidence
        )
        require_aware(
            self.recorded_at,
            "MemoryRelation.recorded_at",
        )
        require_aware(
            self.valid_from,
            "MemoryRelation.valid_from",
        )
        require_aware(
            self.valid_until,
            "MemoryRelation.valid_until",
        )
        require_text(
            self.canonical_key,
            "MemoryRelation.canonical_key",
        )

        for field_name, values in (
            (
                "source_episode_ids",
                self.source_episode_ids,
            ),
            (
                "supersedes_relation_ids",
                self.supersedes_relation_ids,
            ),
            (
                "contradicts_relation_ids",
                self.contradicts_relation_ids,
            ),
        ):
            if (
                len(set(values))
                != len(values)
            ):
                raise ValueError(
                    f"MemoryRelation "
                    f"{field_name} "
                    "must be unique"
                )

        object.__setattr__(
            self,
            "metadata",
            freeze_metadata(
                self.metadata
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryAuditEvent:
    id: str
    transaction_id: str
    event_type: str
    timestamp: datetime
    canonical_revision: int
    details: Mapping[str, Any]
    previous_hash: str
    event_hash: str
    record_id: str | None = None
    record_type: str | None = None
    actor_entity_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        require_text(
            self.id,
            "MemoryAuditEvent.id",
        )
        require_text(
            self.transaction_id,
            "MemoryAuditEvent.transaction_id",
        )
        require_text(
            self.event_type,
            "MemoryAuditEvent.event_type",
        )
        require_aware(
            self.timestamp,
            "MemoryAuditEvent.timestamp",
        )

        if self.canonical_revision < 1:
            raise ValueError(
                "MemoryAuditEvent canonical_revision must be >= 1"
            )

        require_text(
            self.previous_hash,
            "MemoryAuditEvent.previous_hash",
        )
        require_text(
            self.event_hash,
            "MemoryAuditEvent.event_hash",
        )

        object.__setattr__(
            self,
            "details",
            freeze_metadata(
                self.details
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryCommitReceipt:
    transaction_id: str
    status: CommitStatus
    episode_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    superseded_fact_ids: tuple[str, ...]
    superseded_relation_ids: tuple[str, ...]
    conflicts_created: tuple[str, ...]
    recorded_at: datetime
    canonical_revision: int
    projection_revision: int | None
    message_code: str

    def __post_init__(self) -> None:
        require_text(
            self.transaction_id,
            "MemoryCommitReceipt.transaction_id",
        )
        require_aware(
            self.recorded_at,
            "MemoryCommitReceipt.recorded_at",
        )

        if self.canonical_revision < 0:
            raise ValueError(
                "canonical_revision must be >= 0"
            )

        require_text(
            self.message_code,
            "MemoryCommitReceipt.message_code",
        )
