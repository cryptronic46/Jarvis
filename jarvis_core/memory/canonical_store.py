from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
import hashlib
import json
import sqlite3

from .enums import (
    AuditEventType,
    Cardinality,
    CommitStatus,
    MemoryAuthority,
    MemoryClass,
    MemoryNamespace,
    MemoryStatus,
    PropertyKind,
    MEMORY_CONTRACT_VERSION,
    SCHEMA_VERSION,
    SourceType,
    TransactionStatus,
    ValueType,
)
from .availability import is_sqlite_availability_error
from .errors import (
    MemoryAvailabilityError,
    MemoryIntegrityError,
    MemorySchemaError,
)
from .ids import new_memory_id
from .models import (
    CanonicalProperty,
    Entity,
    MemoryAuditEvent,
    MemoryCommitReceipt,
    MemoryEpisode,
    MemoryFact,
    MemoryRelation,
    MemoryValue,
    utc_now,
)
from .validation import (
    stable_json,
    utc_text,
)


_GENESIS_AUDIT_HASH = "0" * 64


_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions(
    transaction_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL,
    actor_entity_id TEXT,
    started_at TEXT NOT NULL,
    committed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities(
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    namespace TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    aliases_json TEXT NOT NULL,
    initial_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK(
            confidence >= 0
            AND confidence <= 1
        ),
    metadata_json TEXT NOT NULL,
    created_transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes(
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    conversation_id TEXT,
    sequence INTEGER,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    speaker_entity_id TEXT
        REFERENCES entities(id),
    source_type TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_text TEXT,
    content_hash TEXT NOT NULL,
    explicit_memory_request INTEGER NOT NULL
        CHECK(
            explicit_memory_request
            IN (0, 1)
        ),
    metadata_json TEXT NOT NULL,
    created_transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_subject_hints(
    episode_id TEXT NOT NULL
        REFERENCES episodes(id),
    entity_id TEXT NOT NULL
        REFERENCES entities(id),
    PRIMARY KEY(
        episode_id,
        entity_id
    )
);

CREATE TABLE IF NOT EXISTS facts(
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    subject_entity_id TEXT NOT NULL
        REFERENCES entities(id),
    property_id TEXT NOT NULL
        REFERENCES properties(id),
    value_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    unit TEXT,
    value_entity_id TEXT
        REFERENCES entities(id),
    raw_representation TEXT,
    memory_class TEXT NOT NULL,
    authority TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK(
            confidence >= 0
            AND confidence <= 1
        ),
    initial_status TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    recorded_at TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS relations(
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    source_entity_id TEXT NOT NULL
        REFERENCES entities(id),
    property_id TEXT NOT NULL
        REFERENCES properties(id),
    target_entity_id TEXT NOT NULL
        REFERENCES entities(id),
    memory_class TEXT NOT NULL,
    authority TEXT NOT NULL,
    confidence REAL NOT NULL
        CHECK(
            confidence >= 0
            AND confidence <= 1
        ),
    initial_status TEXT NOT NULL,
    valid_from TEXT,
    valid_until TEXT,
    recorded_at TEXT NOT NULL,
    canonical_key TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_episode_sources(
    entity_id TEXT NOT NULL
        REFERENCES entities(id),
    episode_id TEXT NOT NULL
        REFERENCES episodes(id),
    PRIMARY KEY(
        entity_id,
        episode_id
    )
);

CREATE TABLE IF NOT EXISTS fact_episode_sources(
    fact_id TEXT NOT NULL
        REFERENCES facts(id),
    episode_id TEXT NOT NULL
        REFERENCES episodes(id),
    PRIMARY KEY(
        fact_id,
        episode_id
    )
);

CREATE TABLE IF NOT EXISTS fact_fact_sources(
    fact_id TEXT NOT NULL
        REFERENCES facts(id),
    source_fact_id TEXT NOT NULL
        REFERENCES facts(id),
    PRIMARY KEY(
        fact_id,
        source_fact_id
    ),
    CHECK(
        fact_id <> source_fact_id
    )
);

CREATE TABLE IF NOT EXISTS relation_episode_sources(
    relation_id TEXT NOT NULL
        REFERENCES relations(id),
    episode_id TEXT NOT NULL
        REFERENCES episodes(id),
    PRIMARY KEY(
        relation_id,
        episode_id
    )
);

CREATE TABLE IF NOT EXISTS fact_supersessions(
    old_fact_id TEXT NOT NULL
        REFERENCES facts(id),
    new_fact_id TEXT NOT NULL
        REFERENCES facts(id),
    transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(
        old_fact_id,
        new_fact_id
    ),
    CHECK(
        old_fact_id <> new_fact_id
    )
);

CREATE TABLE IF NOT EXISTS relation_supersessions(
    old_relation_id TEXT NOT NULL
        REFERENCES relations(id),
    new_relation_id TEXT NOT NULL
        REFERENCES relations(id),
    transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(
        old_relation_id,
        new_relation_id
    ),
    CHECK(
        old_relation_id <> new_relation_id
    )
);

CREATE TABLE IF NOT EXISTS fact_contradictions(
    fact_id TEXT NOT NULL
        REFERENCES facts(id),
    contradicting_fact_id TEXT NOT NULL
        REFERENCES facts(id),
    transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(
        fact_id,
        contradicting_fact_id
    ),
    CHECK(
        fact_id <> contradicting_fact_id
    )
);

CREATE TABLE IF NOT EXISTS relation_contradictions(
    relation_id TEXT NOT NULL
        REFERENCES relations(id),
    contradicting_relation_id TEXT NOT NULL
        REFERENCES relations(id),
    transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(
        relation_id,
        contradicting_relation_id
    ),
    CHECK(
        relation_id <> contradicting_relation_id
    )
);

CREATE TABLE IF NOT EXISTS audit_events(
    id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    revision INTEGER NOT NULL,
    event_index INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    record_id TEXT,
    record_type TEXT,
    actor_entity_id TEXT,
    timestamp TEXT NOT NULL,
    details_json TEXT NOT NULL,
    previous_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    schema_version INTEGER NOT NULL,
    UNIQUE(
        transaction_id,
        event_index
    )
);

CREATE TABLE IF NOT EXISTS projection_cursors(
    name TEXT PRIMARY KEY,
    last_applied_revision INTEGER NOT NULL
        CHECK(
            last_applied_revision >= 0
        ),
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS
idx_memory1_entities_namespace
    ON entities(namespace);

CREATE INDEX IF NOT EXISTS
idx_memory1_episodes_recorded
    ON episodes(recorded_at);

CREATE INDEX IF NOT EXISTS
idx_memory1_episodes_content_hash
    ON episodes(content_hash);

CREATE INDEX IF NOT EXISTS
idx_memory1_facts_subject_property
    ON facts(
        subject_entity_id,
        property_id
    );

CREATE INDEX IF NOT EXISTS
idx_memory1_facts_canonical_key
    ON facts(canonical_key);

CREATE INDEX IF NOT EXISTS
idx_memory1_relations_source_property
    ON relations(
        source_entity_id,
        property_id
    );

CREATE INDEX IF NOT EXISTS
idx_memory1_relations_target_property
    ON relations(
        target_entity_id,
        property_id
    );

CREATE INDEX IF NOT EXISTS
idx_memory1_relations_canonical_key
    ON relations(canonical_key);

CREATE INDEX IF NOT EXISTS
idx_memory1_audit_revision
    ON audit_events(
        revision,
        event_index
    );
"""

_PROPERTY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS properties(
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    semantic_labels_json TEXT NOT NULL,
    semantic_type TEXT NOT NULL,
    cardinality TEXT NOT NULL,
    value_type TEXT,
    initial_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_transaction_id TEXT NOT NULL
        REFERENCES transactions(
            transaction_id
        ),
    created_revision INTEGER NOT NULL,
    CHECK(
        (
            kind = 'FACT'
            AND value_type IS NOT NULL
        )
        OR
        (
            kind = 'RELATION'
            AND value_type IS NULL
        )
    )
)
"""

_PROPERTY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS
idx_memory1_properties_kind
    ON properties(kind)
"""

_SCHEMA_SQL = (
    _SCHEMA_SQL
    + "\n"
    + _PROPERTY_TABLE_SQL
    + ";\n"
    + _PROPERTY_INDEX_SQL
    + ";\n"
)


def _audit_digest(
    previous_hash: str,
    payload: Mapping[str, Any],
) -> str:
    material = (
        previous_hash
        + "\n"
        + stable_json(
            dict(payload)
        )
    )

    return hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()


def _parse_utc(
    value: str | None,
) -> datetime | None:
    if value is None:
        return None

    text = str(
        value
    ).strip()

    if not text:
        return None

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    parsed = datetime.fromisoformat(
        text
    )

    if (
        parsed.tzinfo is None
        or parsed.utcoffset()
        is None
    ):
        raise MemoryIntegrityError(
            "canonical timestamp is not timezone-aware"
        )

    return parsed


class CanonicalMemoryTransaction:
    """One fail-closed canonical write transaction."""

    def __init__(
        self,
        store: "CanonicalMemoryStore",
        *,
        actor_entity_id: str | None = None,
    ) -> None:
        self._store = store
        self._conn = store._connect()
        self._active = False
        self._event_index = 0
        self._mutation_count = 0

        self.transaction_id = (
            new_memory_id()
        )
        self.actor_entity_id = (
            actor_entity_id
        )
        self.started_at = utc_now()

        self.property_ids: list[str] = []
        self.episode_ids: list[str] = []
        self.fact_ids: list[str] = []
        self.relation_ids: list[str] = []
        self.superseded_fact_ids: list[str] = []
        self.superseded_relation_ids: list[str] = []
        self.conflicts_created: list[str] = []

        try:
            self._conn.execute(
                "BEGIN IMMEDIATE"
            )

            row = self._conn.execute(
                """
                SELECT value
                FROM meta
                WHERE key =
                    'canonical_revision'
                """
            ).fetchone()

            if row is None:
                raise MemorySchemaError(
                    "canonical_revision missing"
                )

            self._previous_revision = int(
                row["value"]
            )

            self.revision = (
                self._previous_revision
                + 1
            )

            last = self._conn.execute(
                """
                SELECT event_hash
                FROM audit_events
                ORDER BY
                    revision DESC,
                    event_index DESC
                LIMIT 1
                """
            ).fetchone()

            self._previous_audit_hash = (
                str(
                    last["event_hash"]
                )
                if last is not None
                else _GENESIS_AUDIT_HASH
            )

            started = utc_text(
                self.started_at
            )

            self._conn.execute(
                """
                INSERT INTO transactions(
                    transaction_id,
                    revision,
                    status,
                    actor_entity_id,
                    started_at,
                    committed_at
                )
                VALUES(
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    self.transaction_id,
                    self.revision,
                    TransactionStatus
                    .IN_PROGRESS
                    .value,
                    self.actor_entity_id,
                    started,
                    started,
                ),
            )

            self._active = True

        except Exception:
            self._conn.rollback()
            self._conn.close()
            raise

    def __enter__(
        self,
    ) -> "CanonicalMemoryTransaction":
        self._require_active()
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ) -> bool:
        if self._active:
            self.rollback()

        return False

    def _require_active(
        self,
    ) -> None:
        if not self._active:
            raise MemoryIntegrityError(
                "canonical transaction is not active"
            )

    def _append_audit(
        self,
        event_type: AuditEventType | str,
        *,
        record_id: str | None = None,
        record_type: str | None = None,
        details: Mapping[
            str,
            Any,
        ] | None = None,
        timestamp: datetime | None = None,
    ) -> MemoryAuditEvent:
        self._require_active()

        event_time = (
            timestamp
            or utc_now()
        )

        event_type_text = (
            event_type.value
            if isinstance(
                event_type,
                AuditEventType,
            )
            else str(
                event_type
            ).strip()
        )

        if not event_type_text:
            raise MemoryIntegrityError(
                "audit event_type must not be empty"
            )

        details_dict = dict(
            details or {}
        )

        event_id = new_memory_id()
        event_index = self._event_index

        payload = {
            "id": event_id,
            "transaction_id":
                self.transaction_id,
            "revision":
                self.revision,
            "event_index":
                event_index,
            "event_type":
                event_type_text,
            "record_id":
                record_id,
            "record_type":
                record_type,
            "actor_entity_id":
                self.actor_entity_id,
            "timestamp":
                utc_text(
                    event_time
                ),
            "details":
                details_dict,
            "schema_version":
                SCHEMA_VERSION,
        }

        event_hash = _audit_digest(
            self._previous_audit_hash,
            payload,
        )

        self._conn.execute(
            """
            INSERT INTO audit_events(
                id,
                transaction_id,
                revision,
                event_index,
                event_type,
                record_id,
                record_type,
                actor_entity_id,
                timestamp,
                details_json,
                previous_hash,
                event_hash,
                schema_version
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                event_id,
                self.transaction_id,
                self.revision,
                event_index,
                event_type_text,
                record_id,
                record_type,
                self.actor_entity_id,
                utc_text(
                    event_time
                ),
                stable_json(
                    details_dict
                ),
                self._previous_audit_hash,
                event_hash,
                SCHEMA_VERSION,
            ),
        )

        event = MemoryAuditEvent(
            id=event_id,
            transaction_id=(
                self.transaction_id
            ),
            event_type=(
                event_type_text
            ),
            timestamp=event_time,
            canonical_revision=(
                self.revision
            ),
            details=details_dict,
            previous_hash=(
                self._previous_audit_hash
            ),
            event_hash=event_hash,
            record_id=record_id,
            record_type=record_type,
            actor_entity_id=(
                self.actor_entity_id
            ),
        )

        self._previous_audit_hash = (
            event_hash
        )

        self._event_index += 1

        return event

    def append_audit(
        self,
        event_type: AuditEventType | str,
        *,
        record_id: str | None = None,
        record_type: str | None = None,
        details: Mapping[
            str,
            Any,
        ] | None = None,
    ) -> MemoryAuditEvent:
        return self._append_audit(
            event_type,
            record_id=record_id,
            record_type=record_type,
            details=details,
        )


    def create_property(
        self,
        property: CanonicalProperty,
    ) -> str:
        self._require_active()

        if not isinstance(
            property,
            CanonicalProperty,
        ):
            raise MemoryIntegrityError(
                "create_property requires "
                "CanonicalProperty"
            )

        self._conn.execute(
            """
            INSERT INTO properties(
                id,
                schema_version,
                kind,
                semantic_labels_json,
                semantic_type,
                cardinality,
                value_type,
                initial_status,
                created_at,
                created_transaction_id,
                created_revision
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                property.id,
                property.schema_version,
                property.kind.value,
                stable_json(
                    list(
                        property.semantic_labels
                    )
                ),
                property.semantic_type,
                property.cardinality.value,
                (
                    None
                    if property.value_type is None
                    else property.value_type.value
                ),
                property.status.value,
                utc_text(
                    property.created_at
                ),
                self.transaction_id,
                self.revision,
            ),
        )

        self._append_audit(
            AuditEventType.PROPERTY_CREATED,
            record_id=property.id,
            record_type="PROPERTY",
            details={
                "kind":
                    property.kind.value,
                "semantic_type":
                    property.semantic_type,
                "cardinality":
                    property.cardinality.value,
                "value_type":
                    (
                        None
                        if property.value_type is None
                        else property.value_type.value
                    ),
            },
        )

        self.property_ids.append(
            property.id
        )

        self._mutation_count += 1

        return property.id

    def create_entity(
        self,
        entity: Entity,
    ) -> str:
        self._require_active()

        self._conn.execute(
            """
            INSERT INTO entities(
                id,
                schema_version,
                namespace,
                canonical_name,
                entity_type,
                aliases_json,
                initial_status,
                created_at,
                updated_at,
                confidence,
                metadata_json,
                created_transaction_id,
                created_revision
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                entity.id,
                entity.schema_version,
                entity.namespace.value,
                entity.canonical_name,
                entity.entity_type,
                stable_json(
                    list(
                        entity.aliases
                    )
                ),
                entity.status.value,
                utc_text(
                    entity.created_at
                ),
                utc_text(
                    entity.updated_at
                ),
                entity.confidence,
                stable_json(
                    dict(
                        entity.metadata
                    )
                ),
                self.transaction_id,
                self.revision,
            ),
        )

        for episode_id in (
            entity.source_episode_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                entity_episode_sources(
                    entity_id,
                    episode_id
                )
                VALUES(?, ?)
                """,
                (
                    entity.id,
                    episode_id,
                ),
            )

        self._append_audit(
            AuditEventType
            .ENTITY_CREATED,
            record_id=entity.id,
            record_type="ENTITY",
            details={
                "namespace":
                    entity
                    .namespace
                    .value,
                "entity_type":
                    entity.entity_type,
            },
        )

        self._mutation_count += 1

        return entity.id

    def append_episode(
        self,
        episode: MemoryEpisode,
    ) -> str:
        self._require_active()

        self._conn.execute(
            """
            INSERT INTO episodes(
                id,
                schema_version,
                conversation_id,
                sequence,
                occurred_at,
                recorded_at,
                speaker_entity_id,
                source_type,
                raw_text,
                normalized_text,
                content_hash,
                explicit_memory_request,
                metadata_json,
                created_transaction_id,
                created_revision
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                episode.id,
                episode.schema_version,
                episode.conversation_id,
                episode.sequence,
                utc_text(
                    episode.occurred_at
                ),
                utc_text(
                    episode.recorded_at
                ),
                episode.speaker_entity_id,
                episode.source_type.value,
                episode.raw_text,
                episode.normalized_text,
                episode.content_hash,
                int(
                    episode
                    .explicit_memory_request
                ),
                stable_json(
                    dict(
                        episode.metadata
                    )
                ),
                self.transaction_id,
                self.revision,
            ),
        )

        for entity_id in (
            episode.subject_hints
        ):
            self._conn.execute(
                """
                INSERT INTO
                episode_subject_hints(
                    episode_id,
                    entity_id
                )
                VALUES(?, ?)
                """,
                (
                    episode.id,
                    entity_id,
                ),
            )

        self._append_audit(
            AuditEventType
            .EPISODE_RECORDED,
            record_id=episode.id,
            record_type="EPISODE",
            details={
                "source_type":
                    episode
                    .source_type
                    .value,
                "content_hash":
                    episode.content_hash,
                "explicit_memory_request":
                    episode
                    .explicit_memory_request,
            },
        )

        self.episode_ids.append(
            episode.id
        )

        self._mutation_count += 1

        return episode.id

    def create_fact(
        self,
        fact: MemoryFact,
    ) -> str:
        self._require_active()

        if not isinstance(
            fact,
            MemoryFact,
        ):
            raise MemoryIntegrityError(
                "create_fact requires "
                "MemoryFact"
            )

        if (
            not fact.source_episode_ids
            and not fact.source_fact_ids
        ):
            raise MemoryIntegrityError(
                "canonical facts require "
                "provenance"
            )

        property_row = (
            self._conn.execute(
                """
                SELECT
                    kind,
                    value_type
                FROM properties
                WHERE id = ?
                """,
                (
                    fact.property_id,
                ),
            ).fetchone()
        )

        if property_row is None:
            raise MemoryIntegrityError(
                "fact property does not exist"
            )

        if (
            str(
                property_row["kind"]
            )
            != PropertyKind.FACT.value
        ):
            raise MemoryIntegrityError(
                "fact property kind must "
                "be FACT"
            )

        declared_value_type = (
            property_row[
                "value_type"
            ]
        )

        if (
            declared_value_type is None
            or str(
                declared_value_type
            )
            != fact.value
            .value_type
            .value
        ):
            raise MemoryIntegrityError(
                "fact value type does "
                "not match canonical "
                "property"
            )

        expected_key = (
            f"{fact.subject_entity_id}"
            f"|{fact.property_id}"
        )

        if (
            fact.canonical_key
            != expected_key
        ):
            raise MemoryIntegrityError(
                "fact canonical_key does "
                "not match property "
                "identity"
            )

        self._conn.execute(
            """
            INSERT INTO facts(
                id,
                schema_version,
                subject_entity_id,
                property_id,
                value_type,
                value_json,
                unit,
                value_entity_id,
                raw_representation,
                memory_class,
                authority,
                confidence,
                initial_status,
                valid_from,
                valid_until,
                recorded_at,
                canonical_key,
                metadata_json,
                created_transaction_id,
                created_revision
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            (
                fact.id,
                fact.schema_version,
                fact.subject_entity_id,
                fact.property_id,
                fact.value
                .value_type
                .value,
                stable_json(
                    fact.value.value
                ),
                fact.value.unit,
                fact.value.entity_id,
                fact.value
                .raw_representation,
                fact.memory_class.value,
                fact.authority.value,
                fact.confidence,
                fact.status.value,
                utc_text(
                    fact.valid_from
                ),
                utc_text(
                    fact.valid_until
                ),
                utc_text(
                    fact.recorded_at
                ),
                fact.canonical_key,
                stable_json(
                    dict(
                        fact.metadata
                    )
                ),
                self.transaction_id,
                self.revision,
            ),
        )

        for episode_id in (
            fact.source_episode_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                fact_episode_sources(
                    fact_id,
                    episode_id
                )
                VALUES(?, ?)
                """,
                (
                    fact.id,
                    episode_id,
                ),
            )

        for source_fact_id in (
            fact.source_fact_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                fact_fact_sources(
                    fact_id,
                    source_fact_id
                )
                VALUES(?, ?)
                """,
                (
                    fact.id,
                    source_fact_id,
                ),
            )

        now_text = utc_text(
            utc_now()
        )

        for old_fact_id in (
            fact.supersedes_fact_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                fact_supersessions(
                    old_fact_id,
                    new_fact_id,
                    transaction_id,
                    created_revision,
                    created_at
                )
                VALUES(
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    old_fact_id,
                    fact.id,
                    self.transaction_id,
                    self.revision,
                    now_text,
                ),
            )

            self.superseded_fact_ids.append(
                old_fact_id
            )

            self._append_audit(
                AuditEventType
                .FACT_SUPERSEDED,
                record_id=(
                    old_fact_id
                ),
                record_type="FACT",
                details={
                    "new_fact_id":
                        fact.id,
                },
            )

        for other_fact_id in (
            fact.contradicts_fact_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                fact_contradictions(
                    fact_id,
                    contradicting_fact_id,
                    transaction_id,
                    created_revision,
                    created_at
                )
                VALUES(
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    fact.id,
                    other_fact_id,
                    self.transaction_id,
                    self.revision,
                    now_text,
                ),
            )

        self._append_audit(
            AuditEventType
            .FACT_CREATED,
            record_id=fact.id,
            record_type="FACT",
            details={
                "subject_entity_id":
                    fact.subject_entity_id,
                "property_id":
                    fact.property_id,
                "authority":
                    fact.authority.value,
                "memory_class":
                    fact.memory_class.value,
            },
        )

        self.fact_ids.append(
            fact.id
        )

        self._mutation_count += 1

        return fact.id

    def create_relation(
        self,
        relation: MemoryRelation,
    ) -> str:
        self._require_active()

        if not isinstance(
            relation,
            MemoryRelation,
        ):
            raise MemoryIntegrityError(
                "create_relation requires "
                "MemoryRelation"
            )

        if not relation.source_episode_ids:
            raise MemoryIntegrityError(
                "canonical relations require "
                "provenance"
            )

        property_row = (
            self._conn.execute(
                """
                SELECT
                    kind,
                    value_type
                FROM properties
                WHERE id = ?
                """,
                (
                    relation.property_id,
                ),
            ).fetchone()
        )

        if property_row is None:
            raise MemoryIntegrityError(
                "relation property "
                "does not exist"
            )

        if (
            str(
                property_row["kind"]
            )
            != PropertyKind
            .RELATION
            .value
        ):
            raise MemoryIntegrityError(
                "relation property kind "
                "must be RELATION"
            )

        if (
            property_row[
                "value_type"
            ]
            is not None
        ):
            raise MemoryIntegrityError(
                "RELATION canonical "
                "property must not "
                "declare value_type"
            )

        expected_key = (
            f"{relation.source_entity_id}"
            f"|{relation.property_id}"
        )

        if (
            relation.canonical_key
            != expected_key
        ):
            raise MemoryIntegrityError(
                "relation canonical_key "
                "does not match property "
                "identity"
            )

        self._conn.execute(
            """
            INSERT INTO relations(
                id,
                schema_version,
                source_entity_id,
                property_id,
                target_entity_id,
                memory_class,
                authority,
                confidence,
                initial_status,
                valid_from,
                valid_until,
                recorded_at,
                canonical_key,
                metadata_json,
                created_transaction_id,
                created_revision
            )
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                relation.id,
                relation.schema_version,
                relation.source_entity_id,
                relation.property_id,
                relation.target_entity_id,
                relation.memory_class.value,
                relation.authority.value,
                relation.confidence,
                relation.status.value,
                utc_text(
                    relation.valid_from
                ),
                utc_text(
                    relation.valid_until
                ),
                utc_text(
                    relation.recorded_at
                ),
                relation.canonical_key,
                stable_json(
                    dict(
                        relation.metadata
                    )
                ),
                self.transaction_id,
                self.revision,
            ),
        )

        for episode_id in (
            relation.source_episode_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                relation_episode_sources(
                    relation_id,
                    episode_id
                )
                VALUES(?, ?)
                """,
                (
                    relation.id,
                    episode_id,
                ),
            )

        now_text = utc_text(
            utc_now()
        )

        for old_relation_id in (
            relation
            .supersedes_relation_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                relation_supersessions(
                    old_relation_id,
                    new_relation_id,
                    transaction_id,
                    created_revision,
                    created_at
                )
                VALUES(
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    old_relation_id,
                    relation.id,
                    self.transaction_id,
                    self.revision,
                    now_text,
                ),
            )

            self.superseded_relation_ids.append(
                old_relation_id
            )

            self._append_audit(
                AuditEventType
                .RELATION_SUPERSEDED,
                record_id=(
                    old_relation_id
                ),
                record_type="RELATION",
                details={
                    "new_relation_id":
                        relation.id,
                },
            )

        for other_relation_id in (
            relation
            .contradicts_relation_ids
        ):
            self._conn.execute(
                """
                INSERT INTO
                relation_contradictions(
                    relation_id,
                    contradicting_relation_id,
                    transaction_id,
                    created_revision,
                    created_at
                )
                VALUES(
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    relation.id,
                    other_relation_id,
                    self.transaction_id,
                    self.revision,
                    now_text,
                ),
            )

        self._append_audit(
            AuditEventType
            .RELATION_CREATED,
            record_id=relation.id,
            record_type="RELATION",
            details={
                "source_entity_id":
                    relation
                    .source_entity_id,
                "property_id":
                    relation.property_id,
                "target_entity_id":
                    relation
                    .target_entity_id,
                "authority":
                    relation
                    .authority
                    .value,
            },
        )

        self.relation_ids.append(
            relation.id
        )

        self._mutation_count += 1

        return relation.id

    def commit(
        self,
    ) -> MemoryCommitReceipt:
        self._require_active()

        if self._mutation_count == 0:
            receipt = MemoryCommitReceipt(
                transaction_id=(
                    self.transaction_id
                ),
                status=(
                    CommitStatus.NO_CHANGE
                ),
                episode_ids=(),
                fact_ids=(),
                relation_ids=(),
                superseded_fact_ids=(),
                superseded_relation_ids=(),
                conflicts_created=(),
                recorded_at=utc_now(),
                canonical_revision=(
                    self._previous_revision
                ),
                projection_revision=None,
                message_code=(
                    "MEMORY_NO_CHANGE"
                ),
            )

            self.rollback()

            return receipt

        committed_at = utc_now()

        try:
            self._append_audit(
                AuditEventType
                .TRANSACTION_COMMITTED,
                record_id=(
                    self.transaction_id
                ),
                record_type=(
                    "TRANSACTION"
                ),
                details={
                    "property_count":
                        len(
                            self.property_ids
                        ),
                    "episode_count":
                        len(
                            self.episode_ids
                        ),
                    "fact_count":
                        len(
                            self.fact_ids
                        ),
                    "relation_count":
                        len(
                            self.relation_ids
                        ),
                    "canonical_revision":
                        self.revision,
                },
                timestamp=(
                    committed_at
                ),
            )

            self._conn.execute(
                """
                UPDATE transactions
                SET
                    status = ?,
                    committed_at = ?
                WHERE
                    transaction_id = ?
                """,
                (
                    TransactionStatus
                    .COMMITTED
                    .value,
                    utc_text(
                        committed_at
                    ),
                    self.transaction_id,
                ),
            )

            cursor = self._conn.execute(
                """
                UPDATE meta
                SET value = ?
                WHERE
                    key =
                        'canonical_revision'
                    AND value = ?
                """,
                (
                    str(
                        self.revision
                    ),
                    str(
                        self._previous_revision
                    ),
                ),
            )

            if cursor.rowcount != 1:
                raise MemoryIntegrityError(
                    (
                        "canonical revision "
                        "changed during transaction"
                    )
                )

            self._conn.commit()

        except Exception:
            self._conn.rollback()
            self._active = False
            self._conn.close()
            raise

        self._active = False
        self._conn.close()

        return MemoryCommitReceipt(
            transaction_id=(
                self.transaction_id
            ),
            status=(
                CommitStatus.COMMITTED
            ),
            episode_ids=tuple(
                self.episode_ids
            ),
            fact_ids=tuple(
                self.fact_ids
            ),
            relation_ids=tuple(
                self.relation_ids
            ),
            superseded_fact_ids=tuple(
                dict.fromkeys(
                    self
                    .superseded_fact_ids
                )
            ),
            superseded_relation_ids=tuple(
                dict.fromkeys(
                    self
                    .superseded_relation_ids
                )
            ),
            conflicts_created=tuple(
                self.conflicts_created
            ),
            recorded_at=(
                committed_at
            ),
            canonical_revision=(
                self.revision
            ),
            projection_revision=None,
            message_code=(
                "MEMORY_COMMITTED"
            ),
        )

    def rollback(
        self,
    ) -> None:
        if not self._active:
            return

        try:
            self._conn.rollback()

        finally:
            self._active = False
            self._conn.close()


class CanonicalMemoryStore:
    """Canonical SQLite source of truth for JARVIS Memory 1.0."""

    REQUIRED_TABLES = frozenset({
        "meta",
        "transactions",
        "entities",
        "properties",
        "episodes",
        "episode_subject_hints",
        "facts",
        "relations",
        "entity_episode_sources",
        "fact_episode_sources",
        "fact_fact_sources",
        "relation_episode_sources",
        "fact_supersessions",
        "relation_supersessions",
        "fact_contradictions",
        "relation_contradictions",
        "audit_events",
        "projection_cursors",
    })

    def __init__(
        self,
        path: str | Path = (
            "memory/"
            "memory1_canonical.sqlite3"
        ),
    ) -> None:
        self.path = Path(
            path
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize()

    def _connect(
        self,
    ) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(
                self.path
            ),
            timeout=5.0,
            isolation_level=None,
        )

        conn.row_factory = (
            sqlite3.Row
        )

        conn.execute(
            "PRAGMA foreign_keys = ON"
        )

        conn.execute(
            "PRAGMA busy_timeout = 5000"
        )

        conn.execute(
            "PRAGMA synchronous = FULL"
        )

        return conn

    def assert_readable(
        self,
    ) -> None:
        """Fail fast when the canonical SQLite store is not readable now."""

        try:
            conn = self._connect()
        except sqlite3.OperationalError as exc:
            if is_sqlite_availability_error(exc):
                raise MemoryAvailabilityError(
                    "canonical memory store is unavailable"
                ) from exc
            raise

        try:
            conn.execute("SELECT 1").fetchone()
        except sqlite3.OperationalError as exc:
            if is_sqlite_availability_error(exc):
                raise MemoryAvailabilityError(
                    "canonical memory store is unavailable"
                ) from exc
            raise
        finally:
            conn.close()

    def _inspect_existing_schema_version(
        self,
        conn: sqlite3.Connection,
    ) -> int | None:
        tables = {
            str(
                row["name"]
            )
            for row
            in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE
                    type = 'table'
                    AND name NOT LIKE
                        'sqlite_%'
                """
            )
        }

        if not tables:
            return None

        if "meta" not in tables:
            raise MemorySchemaError(
                "existing database has no "
                "Memory1 meta table"
            )

        row = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key =
                'schema_version'
            """
        ).fetchone()

        if row is None:
            raise MemorySchemaError(
                "existing database has no "
                "schema_version"
            )

        try:
            version = int(
                row["value"]
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise MemorySchemaError(
                "invalid existing "
                "schema_version"
            ) from exc

        if version < 1:
            raise MemorySchemaError(
                "invalid existing "
                "schema_version"
            )

        contract = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key =
                'memory_contract_version'
            """
        ).fetchone()

        if contract is None:
            raise MemorySchemaError(
                "existing database has no "
                "memory_contract_version"
            )

        if (
            str(
                contract["value"]
            )
            != MEMORY_CONTRACT_VERSION
        ):
            raise MemorySchemaError(
                "memory_contract_version "
                "mismatch"
            )

        user_version = int(
            conn.execute(
                "PRAGMA user_version"
            ).fetchone()[0]
        )

        if user_version not in (
            0,
            version,
        ):
            raise MemorySchemaError(
                "PRAGMA user_version "
                "does not match "
                "schema_version"
            )

        return version

    def _create_latest_schema(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        conn.executescript(
            _SCHEMA_SQL
        )

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        try:
            self._ensure_meta(
                conn,
                "schema_version",
                str(
                    SCHEMA_VERSION
                ),
            )

            self._ensure_meta(
                conn,
                (
                    "memory_"
                    "contract_version"
                ),
                MEMORY_CONTRACT_VERSION,
            )

            conn.execute(
                """
                INSERT INTO meta(
                    key,
                    value
                )
                VALUES(
                    'canonical_revision',
                    '0'
                )
                ON CONFLICT(key)
                DO NOTHING
                """
            )

            conn.execute(
                (
                    "PRAGMA "
                    "user_version = "
                    f"{SCHEMA_VERSION}"
                )
            )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        target_version = 2
        tables = {str(row['name']) for row in conn.execute("\n            SELECT name\n            FROM sqlite_master\n            WHERE\n                type = 'table'\n                AND name NOT LIKE\n                    'sqlite_%'\n            ")}
        required_v1 = self.REQUIRED_TABLES - {'properties'}
        missing = sorted(required_v1 - tables)
        if missing:
            raise MemorySchemaError('v1 schema missing tables: ' + ', '.join(missing))
        revision_row = conn.execute("\n        SELECT value\n        FROM meta\n        WHERE key =\n            'canonical_revision'\n        ").fetchone()
        if revision_row is None:
            raise MemorySchemaError('v1 canonical_revision missing')
        revision_before = int(revision_row['value'])
        transaction_count_before = int(conn.execute('\n            SELECT COUNT(*)\n            FROM transactions\n            ').fetchone()[0])
        audit_count_before = int(conn.execute('\n            SELECT COUNT(*)\n            FROM audit_events\n            ').fetchone()[0])
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute(_PROPERTY_TABLE_SQL)
            conn.execute(_PROPERTY_INDEX_SQL)
            cursor = conn.execute("\n            UPDATE meta\n            SET value = ?\n            WHERE\n                key =\n                    'schema_version'\n                AND value = '1'\n            ", (str(target_version),))
            if cursor.rowcount != 1:
                raise MemorySchemaError('v1 schema_version changed during migration')
            conn.execute(f'PRAGMA user_version = {target_version}')
            revision_after = int(conn.execute("\n                SELECT value\n                FROM meta\n                WHERE key =\n                    'canonical_revision'\n                ").fetchone()['value'])
            if revision_after != revision_before:
                raise MemoryIntegrityError('schema migration changed canonical_revision')
            transaction_count_after = int(conn.execute('\n                SELECT COUNT(*)\n                FROM transactions\n                ').fetchone()[0])
            audit_count_after = int(conn.execute('\n                SELECT COUNT(*)\n                FROM audit_events\n                ').fetchone()[0])
            if transaction_count_after != transaction_count_before:
                raise MemoryIntegrityError('schema migration created memory transaction')
            if audit_count_after != audit_count_before:
                raise MemoryIntegrityError('schema migration created memory audit event')
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _migrate_v2_to_v3(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        source_version = 2
        target_version = 3

        version_row = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key = 'schema_version'
            """
        ).fetchone()

        if (
            version_row is None
            or int(
                version_row["value"]
            )
            != source_version
        ):
            raise MemorySchemaError(
                "v2->v3 migration "
                "requires schema "
                "version 2"
            )

        required_columns = {
            "facts": {
                "id",
                "schema_version",
                "subject_entity_id",
                "predicate",
                "value_type",
                "value_json",
                "unit",
                "value_entity_id",
                "raw_representation",
                "memory_class",
                "cardinality",
                "authority",
                "confidence",
                "initial_status",
                "valid_from",
                "valid_until",
                "recorded_at",
                "canonical_key",
                "metadata_json",
                "created_transaction_id",
                "created_revision",
            },
            "relations": {
                "id",
                "schema_version",
                "source_entity_id",
                "predicate",
                "target_entity_id",
                "memory_class",
                "cardinality",
                "authority",
                "confidence",
                "initial_status",
                "valid_from",
                "valid_until",
                "recorded_at",
                "canonical_key",
                "metadata_json",
                "created_transaction_id",
                "created_revision",
            },
            "properties": {
                "id",
                "schema_version",
                "kind",
                "semantic_labels_json",
                "semantic_type",
                "cardinality",
                "value_type",
                "initial_status",
                "created_at",
                "created_transaction_id",
                "created_revision",
            },
        }

        for table, required in (
            required_columns.items()
        ):
            actual = {
                str(row["name"])
                for row in conn.execute(
                    f'PRAGMA '
                    f'table_info("{table}")'
                )
            }

            missing = sorted(
                required - actual
            )

            if missing:
                raise MemorySchemaError(
                    "v2->v3 migration "
                    f"missing {table} "
                    "columns: "
                    + ", ".join(
                        missing
                    )
                )

        foreign_keys_before = int(
            conn.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0]
        )

        if (
            foreign_keys_before
            != 1
        ):
            raise MemorySchemaError(
                "v2->v3 migration "
                "requires "
                "foreign_keys=ON"
            )

        conn.execute(
            "PRAGMA foreign_keys = OFF"
        )

        if int(
            conn.execute(
                "PRAGMA foreign_keys"
            ).fetchone()[0]
        ) != 0:
            raise MemorySchemaError(
                "unable to suspend "
                "foreign keys for "
                "table rebuild"
            )

        try:
            conn.execute(
                "BEGIN IMMEDIATE"
            )

            revision_before = str(
                conn.execute(
                    """
                    SELECT value
                    FROM meta
                    WHERE key =
                        'canonical_revision'
                    """
                ).fetchone()[
                    "value"
                ]
            )

            transactions_before = (
                tuple(
                    tuple(row)
                    for row
                    in conn.execute(
                        """
                        SELECT *
                        FROM transactions
                        ORDER BY
                            revision,
                            transaction_id
                        """
                    )
                )
            )

            audit_before = tuple(
                tuple(row)
                for row
                in conn.execute(
                    """
                    SELECT *
                    FROM audit_events
                    ORDER BY
                        revision,
                        event_index,
                        id
                    """
                )
            )

            properties = tuple(
                self._hydrate_property(
                    row
                )
                for row
                in conn.execute(
                    """
                    SELECT *
                    FROM properties
                    ORDER BY id
                    """
                )
            )

            fact_rows = tuple(
                conn.execute(
                    """
                    SELECT *
                    FROM facts
                    ORDER BY id
                    """
                )
            )

            relation_rows = tuple(
                conn.execute(
                    """
                    SELECT *
                    FROM relations
                    ORDER BY id
                    """
                )
            )

            fact_property_ids = {}

            for row in fact_rows:
                matches = tuple(
                    property
                    for property
                    in properties
                    if (
                        property.kind
                        is PropertyKind.FACT
                        and str(
                            row[
                                "predicate"
                            ]
                        )
                        in property
                        .semantic_labels
                        and str(
                            row[
                                "cardinality"
                            ]
                        )
                        == property
                        .cardinality
                        .value
                        and property
                        .value_type
                        is not None
                        and str(
                            row[
                                "value_type"
                            ]
                        )
                        == property
                        .value_type
                        .value
                    )
                )

                if len(matches) != 1:
                    raise MemorySchemaError(
                        "v2 fact property "
                        "mapping is not "
                        "uniquely resolvable"
                    )

                fact_property_ids[
                    str(
                        row["id"]
                    )
                ] = matches[0].id

            relation_property_ids = {}

            for row in relation_rows:
                matches = tuple(
                    property
                    for property
                    in properties
                    if (
                        property.kind
                        is PropertyKind
                        .RELATION
                        and str(
                            row[
                                "predicate"
                            ]
                        )
                        in property
                        .semantic_labels
                        and str(
                            row[
                                "cardinality"
                            ]
                        )
                        == property
                        .cardinality
                        .value
                        and property
                        .value_type
                        is None
                    )
                )

                if len(matches) != 1:
                    raise MemorySchemaError(
                        "v2 relation property "
                        "mapping is not "
                        "uniquely resolvable"
                    )

                relation_property_ids[
                    str(
                        row["id"]
                    )
                ] = matches[0].id

            conn.execute(
                """
                CREATE TABLE
                facts_v3_migration(
                    id TEXT PRIMARY KEY,
                    schema_version
                        INTEGER NOT NULL,
                    subject_entity_id
                        TEXT NOT NULL
                        REFERENCES
                            entities(id),
                    property_id
                        TEXT NOT NULL
                        REFERENCES
                            properties(id),
                    value_type
                        TEXT NOT NULL,
                    value_json
                        TEXT NOT NULL,
                    unit TEXT,
                    value_entity_id TEXT
                        REFERENCES
                            entities(id),
                    raw_representation
                        TEXT,
                    memory_class
                        TEXT NOT NULL,
                    authority
                        TEXT NOT NULL,
                    confidence
                        REAL NOT NULL
                        CHECK(
                            confidence >= 0
                            AND
                            confidence <= 1
                        ),
                    initial_status
                        TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    recorded_at
                        TEXT NOT NULL,
                    canonical_key
                        TEXT NOT NULL,
                    metadata_json
                        TEXT NOT NULL,
                    created_transaction_id
                        TEXT NOT NULL
                        REFERENCES
                            transactions(
                                transaction_id
                            ),
                    created_revision
                        INTEGER NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE
                relations_v3_migration(
                    id TEXT PRIMARY KEY,
                    schema_version
                        INTEGER NOT NULL,
                    source_entity_id
                        TEXT NOT NULL
                        REFERENCES
                            entities(id),
                    property_id
                        TEXT NOT NULL
                        REFERENCES
                            properties(id),
                    target_entity_id
                        TEXT NOT NULL
                        REFERENCES
                            entities(id),
                    memory_class
                        TEXT NOT NULL,
                    authority
                        TEXT NOT NULL,
                    confidence
                        REAL NOT NULL
                        CHECK(
                            confidence >= 0
                            AND
                            confidence <= 1
                        ),
                    initial_status
                        TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    recorded_at
                        TEXT NOT NULL,
                    canonical_key
                        TEXT NOT NULL,
                    metadata_json
                        TEXT NOT NULL,
                    created_transaction_id
                        TEXT NOT NULL
                        REFERENCES
                            transactions(
                                transaction_id
                            ),
                    created_revision
                        INTEGER NOT NULL
                )
                """
            )

            for row in fact_rows:
                property_id = (
                    fact_property_ids[
                        str(
                            row["id"]
                        )
                    ]
                )

                conn.execute(
                    """
                    INSERT INTO
                    facts_v3_migration(
                        id,
                        schema_version,
                        subject_entity_id,
                        property_id,
                        value_type,
                        value_json,
                        unit,
                        value_entity_id,
                        raw_representation,
                        memory_class,
                        authority,
                        confidence,
                        initial_status,
                        valid_from,
                        valid_until,
                        recorded_at,
                        canonical_key,
                        metadata_json,
                        created_transaction_id,
                        created_revision
                    )
                    VALUES(
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?
                    )
                    """,
                    (
                        row["id"],
                        target_version,
                        row[
                            "subject_entity_id"
                        ],
                        property_id,
                        row[
                            "value_type"
                        ],
                        row[
                            "value_json"
                        ],
                        row["unit"],
                        row[
                            "value_entity_id"
                        ],
                        row[
                            "raw_representation"
                        ],
                        row[
                            "memory_class"
                        ],
                        row[
                            "authority"
                        ],
                        row[
                            "confidence"
                        ],
                        row[
                            "initial_status"
                        ],
                        row[
                            "valid_from"
                        ],
                        row[
                            "valid_until"
                        ],
                        row[
                            "recorded_at"
                        ],
                        (
                            f"{row['subject_entity_id']}"
                            f"|{property_id}"
                        ),
                        row[
                            "metadata_json"
                        ],
                        row[
                            "created_transaction_id"
                        ],
                        row[
                            "created_revision"
                        ],
                    ),
                )

            for row in relation_rows:
                property_id = (
                    relation_property_ids[
                        str(
                            row["id"]
                        )
                    ]
                )

                conn.execute(
                    """
                    INSERT INTO
                    relations_v3_migration(
                        id,
                        schema_version,
                        source_entity_id,
                        property_id,
                        target_entity_id,
                        memory_class,
                        authority,
                        confidence,
                        initial_status,
                        valid_from,
                        valid_until,
                        recorded_at,
                        canonical_key,
                        metadata_json,
                        created_transaction_id,
                        created_revision
                    )
                    VALUES(
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        row["id"],
                        target_version,
                        row[
                            "source_entity_id"
                        ],
                        property_id,
                        row[
                            "target_entity_id"
                        ],
                        row[
                            "memory_class"
                        ],
                        row[
                            "authority"
                        ],
                        row[
                            "confidence"
                        ],
                        row[
                            "initial_status"
                        ],
                        row[
                            "valid_from"
                        ],
                        row[
                            "valid_until"
                        ],
                        row[
                            "recorded_at"
                        ],
                        (
                            f"{row['source_entity_id']}"
                            f"|{property_id}"
                        ),
                        row[
                            "metadata_json"
                        ],
                        row[
                            "created_transaction_id"
                        ],
                        row[
                            "created_revision"
                        ],
                    ),
                )

            conn.execute(
                "DROP TABLE facts"
            )

            conn.execute(
                "DROP TABLE relations"
            )

            conn.execute(
                """
                ALTER TABLE
                    facts_v3_migration
                RENAME TO facts
                """
            )

            conn.execute(
                """
                ALTER TABLE
                    relations_v3_migration
                RENAME TO relations
                """
            )

            conn.execute(
                """
                CREATE INDEX
                idx_memory1_facts_subject_property
                ON facts(
                    subject_entity_id,
                    property_id
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX
                idx_memory1_facts_canonical_key
                ON facts(
                    canonical_key
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX
                idx_memory1_relations_source_property
                ON relations(
                    source_entity_id,
                    property_id
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX
                idx_memory1_relations_target_property
                ON relations(
                    target_entity_id,
                    property_id
                )
                """
            )

            conn.execute(
                """
                CREATE INDEX
                idx_memory1_relations_canonical_key
                ON relations(
                    canonical_key
                )
                """
            )

            cursor = conn.execute(
                """
                UPDATE meta
                SET value = ?
                WHERE
                    key =
                        'schema_version'
                    AND value = '2'
                """,
                (
                    str(
                        target_version
                    ),
                ),
            )

            if cursor.rowcount != 1:
                raise MemorySchemaError(
                    "v2 schema_version "
                    "changed during "
                    "migration"
                )

            conn.execute(
                (
                    "PRAGMA "
                    "user_version = "
                    f"{target_version}"
                )
            )

            revision_after = str(
                conn.execute(
                    """
                    SELECT value
                    FROM meta
                    WHERE key =
                        'canonical_revision'
                    """
                ).fetchone()[
                    "value"
                ]
            )

            transactions_after = (
                tuple(
                    tuple(row)
                    for row
                    in conn.execute(
                        """
                        SELECT *
                        FROM transactions
                        ORDER BY
                            revision,
                            transaction_id
                        """
                    )
                )
            )

            audit_after = tuple(
                tuple(row)
                for row
                in conn.execute(
                    """
                    SELECT *
                    FROM audit_events
                    ORDER BY
                        revision,
                        event_index,
                        id
                    """
                )
            )

            if (
                revision_after
                != revision_before
            ):
                raise MemoryIntegrityError(
                    "v2->v3 migration "
                    "changed "
                    "canonical_revision"
                )

            if (
                transactions_after
                != transactions_before
            ):
                raise MemoryIntegrityError(
                    "v2->v3 migration "
                    "changed memory "
                    "transactions"
                )

            if (
                audit_after
                != audit_before
            ):
                raise MemoryIntegrityError(
                    "v2->v3 migration "
                    "changed audit "
                    "chain rows"
                )

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            if int(
                conn.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0]
            ) != 1:
                raise MemorySchemaError(
                    "foreign key "
                    "enforcement was "
                    "not restored"
                )

        violations = tuple(
            conn.execute(
                "PRAGMA foreign_key_check"
            )
        )

        if violations:
            raise MemoryIntegrityError(
                "v2->v3 migration "
                "produced foreign-key "
                "violations"
            )

    def _initialize(
        self,
    ) -> None:
        conn = self._connect()

        try:
            mode = str(
                conn.execute(
                    "PRAGMA journal_mode = WAL"
                ).fetchone()[0]
            ).lower()

            if mode != "wal":
                raise MemorySchemaError(
                    (
                        "canonical store "
                        "requires WAL mode, "
                        f"got {mode}"
                    )
                )

            existing_version = (
                self
                ._inspect_existing_schema_version(
                    conn
                )
            )

            if existing_version is None:
                self._create_latest_schema(
                    conn
                )

            elif (
                existing_version
                > SCHEMA_VERSION
            ):
                raise MemorySchemaError(
                    (
                        "future canonical "
                        "schema version: "
                        f"{existing_version}"
                    )
                )

            else:
                current_version = (
                    existing_version
                )

                while (
                    current_version
                    < SCHEMA_VERSION
                ):
                    if (
                        current_version
                        == 1
                    ):
                        self._migrate_v1_to_v2(
                            conn
                        )

                        current_version = 2

                    elif (
                        current_version
                        == 2
                    ):
                        self._migrate_v2_to_v3(
                            conn
                        )

                        current_version = 3

                    else:
                        raise MemorySchemaError(
                            (
                                "unsupported "
                                "canonical schema "
                                "migration step: "
                                f"{current_version}"
                            )
                        )

            self._validate_schema(
                conn
            )

        finally:
            conn.close()

    @staticmethod
    def _ensure_meta(
        conn: sqlite3.Connection,
        key: str,
        expected: str,
    ) -> None:
        row = conn.execute(
            (
                "SELECT value "
                "FROM meta "
                "WHERE key = ?"
            ),
            (
                key,
            ),
        ).fetchone()

        if (
            row is not None
            and str(
                row["value"]
            )
            != expected
        ):
            raise MemorySchemaError(
                (
                    f"{key} mismatch: "
                    f"{row['value']} "
                    f"!= {expected}"
                )
            )

        conn.execute(
            """
            INSERT INTO meta(
                key,
                value
            )
            VALUES(?, ?)
            ON CONFLICT(key)
            DO NOTHING
            """,
            (
                key,
                expected,
            ),
        )

    def _validate_schema(self, conn: sqlite3.Connection) -> None:
        tables = {str(row['name']) for row in conn.execute("\n            SELECT name\n            FROM sqlite_master\n            WHERE type = 'table'\n            ")}
        missing = sorted(self.REQUIRED_TABLES - tables)
        if missing:
            raise MemorySchemaError('canonical schema missing tables: ' + ', '.join(missing))
        schema_row = conn.execute("\n        SELECT value\n        FROM meta\n        WHERE key =\n            'schema_version'\n        ").fetchone()
        if schema_row is None:
            raise MemorySchemaError('schema_version missing')
        try:
            schema_version = int(schema_row['value'])
        except (TypeError, ValueError) as exc:
            raise MemorySchemaError('schema_version invalid') from exc
        if schema_version != SCHEMA_VERSION:
            raise MemorySchemaError(f'schema_version mismatch: {schema_version} != {SCHEMA_VERSION}')
        contract_row = conn.execute("\n        SELECT value\n        FROM meta\n        WHERE key =\n            'memory_contract_version'\n        ").fetchone()
        if contract_row is None:
            raise MemorySchemaError('memory_contract_version missing')
        if str(contract_row['value']) != MEMORY_CONTRACT_VERSION:
            raise MemorySchemaError('memory_contract_version mismatch')
        user_version = int(conn.execute('PRAGMA user_version').fetchone()[0])
        if user_version != SCHEMA_VERSION:
            raise MemorySchemaError(f'PRAGMA user_version mismatch: {user_version} != {SCHEMA_VERSION}')
        revision = conn.execute("\n        SELECT value\n        FROM meta\n        WHERE key =\n            'canonical_revision'\n        ").fetchone()
        if revision is None:
            raise MemorySchemaError('canonical_revision missing')
        try:
            canonical_revision = int(revision['value'])
        except (TypeError, ValueError) as exc:
            raise MemorySchemaError('canonical_revision invalid') from exc
        if canonical_revision < 0:
            raise MemorySchemaError('canonical_revision is negative')
        expected_assertion_columns = {'facts': {'id', 'schema_version', 'subject_entity_id', 'property_id', 'value_type', 'value_json', 'unit', 'value_entity_id', 'raw_representation', 'memory_class', 'authority', 'confidence', 'initial_status', 'valid_from', 'valid_until', 'recorded_at', 'canonical_key', 'metadata_json', 'created_transaction_id', 'created_revision'}, 'relations': {'id', 'schema_version', 'source_entity_id', 'property_id', 'target_entity_id', 'memory_class', 'authority', 'confidence', 'initial_status', 'valid_from', 'valid_until', 'recorded_at', 'canonical_key', 'metadata_json', 'created_transaction_id', 'created_revision'}}
        for table, expected in expected_assertion_columns.items():
            actual = {str(row['name']) for row in conn.execute(f'PRAGMA table_info("{table}")')}
            if actual != expected:
                raise MemorySchemaError(f'canonical schema column mismatch for {table}')
        required_property_fks = {'facts': ('property_id', 'properties', 'id'), 'relations': ('property_id', 'properties', 'id')}
        for table, required in required_property_fks.items():
            found = {(str(row['from']), str(row['table']), str(row['to'])) for row in conn.execute(f'PRAGMA foreign_key_list("{table}")')}
            if required not in found:
                raise MemorySchemaError(f'canonical schema missing property FK for {table}')

    def idempotent_no_change_receipt(
        self,
        *,
        fact_ids: tuple[str, ...] = (),
        relation_ids: tuple[str, ...] = (),
        recorded_at: datetime | None = None,
    ) -> MemoryCommitReceipt:
        if not isinstance(fact_ids, tuple):
            raise MemoryValidationError(
                "fact_ids must be tuple"
            )

        if not isinstance(relation_ids, tuple):
            raise MemoryValidationError(
                "relation_ids must be tuple"
            )

        if not fact_ids and not relation_ids:
            raise MemoryValidationError(
                "idempotent no-change receipt requires an existing assertion"
            )

        for name, values in (
            ("fact_ids", fact_ids),
            ("relation_ids", relation_ids),
        ):
            if len(set(values)) != len(values):
                raise MemoryValidationError(
                    f"{name} must be unique"
                )

            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise MemoryValidationError(
                        f"{name} must contain non-empty text"
                    )

        return MemoryCommitReceipt(
            transaction_id=new_memory_id(),
            status=CommitStatus.NO_CHANGE,
            episode_ids=(),
            fact_ids=fact_ids,
            relation_ids=relation_ids,
            superseded_fact_ids=(),
            superseded_relation_ids=(),
            conflicts_created=(),
            recorded_at=(
                recorded_at
                if recorded_at is not None
                else utc_now()
            ),
            canonical_revision=self.canonical_revision(),
            projection_revision=None,
            message_code="MEMORY_NO_CHANGE_IDEMPOTENT",
        )

    def begin_transaction(
        self,
        *,
        actor_entity_id: str | None = None,
    ) -> CanonicalMemoryTransaction:
        return CanonicalMemoryTransaction(
            self,
            actor_entity_id=(
                actor_entity_id
            ),
        )

    def schema_version(
        self,
    ) -> int:
        return int(
            self.meta_value(
                "schema_version"
            )
        )

    def contract_version(
        self,
    ) -> str:
        return self.meta_value(
            (
                "memory_"
                "contract_version"
            )
        )

    def canonical_revision(
        self,
    ) -> int:
        return int(
            self.meta_value(
                "canonical_revision"
            )
        )

    def meta_value(
        self,
        key: str,
    ) -> str:
        conn = self._connect()

        try:
            row = conn.execute(
                (
                    "SELECT value "
                    "FROM meta "
                    "WHERE key = ?"
                ),
                (
                    str(
                        key
                    ),
                ),
            ).fetchone()

            if row is None:
                raise MemorySchemaError(
                    (
                        "missing meta "
                        f"key: {key}"
                    )
                )

            return str(
                row["value"]
            )

        finally:
            conn.close()

    def journal_mode(
        self,
    ) -> str:
        conn = self._connect()

        try:
            return str(
                conn.execute(
                    (
                        "PRAGMA "
                        "journal_mode"
                    )
                ).fetchone()[0]
            ).lower()

        finally:
            conn.close()

    def synchronous_mode(
        self,
    ) -> int:
        conn = self._connect()

        try:
            return int(
                conn.execute(
                    (
                        "PRAGMA "
                        "synchronous"
                    )
                ).fetchone()[0]
            )

        finally:
            conn.close()

    def foreign_keys_enabled(
        self,
    ) -> bool:
        conn = self._connect()

        try:
            return bool(
                int(
                    conn.execute(
                        (
                            "PRAGMA "
                            "foreign_keys"
                        )
                    ).fetchone()[0]
                )
            )

        finally:
            conn.close()

    def table_names(
        self,
    ) -> tuple[str, ...]:
        conn = self._connect()

        try:
            return tuple(
                sorted(
                    str(
                        row["name"]
                    )
                    for row
                    in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE
                            type = 'table'
                            AND name
                                NOT LIKE
                                'sqlite_%'
                        """
                    )
                )
            )

        finally:
            conn.close()


    @staticmethod
    def _string_tuple(
        conn: sqlite3.Connection,
        sql: str,
        params: tuple[Any, ...],
        column: str,
    ) -> tuple[str, ...]:
        return tuple(
            str(
                row[column]
            )
            for row
            in conn.execute(
                sql,
                params,
            )
        )

    @staticmethod
    def _metadata(
        raw: str,
    ) -> dict[str, Any]:
        try:
            value = json.loads(
                str(
                    raw
                )
            )

        except json.JSONDecodeError as exc:
            raise MemoryIntegrityError(
                "invalid canonical metadata JSON"
            ) from exc

        if not isinstance(
            value,
            dict,
        ):
            raise MemoryIntegrityError(
                "canonical metadata must be an object"
            )

        return value

    def _fact_status(
        self,
        conn: sqlite3.Connection,
        *,
        fact_id: str,
        initial_status: str,
        as_of_revision: int | None,
    ) -> MemoryStatus:
        sql = """
            SELECT 1
            FROM fact_supersessions
            WHERE old_fact_id = ?
        """

        params: list[Any] = [
            fact_id,
        ]

        if (
            as_of_revision
            is not None
        ):
            sql += """
                AND created_revision <= ?
            """

            params.append(
                as_of_revision
            )

        sql += """
            LIMIT 1
        """

        superseded = (
            conn.execute(
                sql,
                tuple(
                    params
                ),
            ).fetchone()
            is not None
        )

        if superseded:
            return (
                MemoryStatus
                .SUPERSEDED
            )

        return MemoryStatus(
            initial_status
        )

    def _relation_status(
        self,
        conn: sqlite3.Connection,
        *,
        relation_id: str,
        initial_status: str,
        as_of_revision: int | None,
    ) -> MemoryStatus:
        sql = """
            SELECT 1
            FROM relation_supersessions
            WHERE old_relation_id = ?
        """

        params: list[Any] = [
            relation_id,
        ]

        if (
            as_of_revision
            is not None
        ):
            sql += """
                AND created_revision <= ?
            """

            params.append(
                as_of_revision
            )

        sql += """
            LIMIT 1
        """

        superseded = (
            conn.execute(
                sql,
                tuple(
                    params
                ),
            ).fetchone()
            is not None
        )

        if superseded:
            return (
                MemoryStatus
                .SUPERSEDED
            )

        return MemoryStatus(
            initial_status
        )

    def _hydrate_property(
        self,
        row: sqlite3.Row,
    ) -> CanonicalProperty:
        try:
            labels_raw = json.loads(
                str(
                    row[
                        "semantic_labels_json"
                    ]
                )
            )

        except json.JSONDecodeError as exc:
            raise MemoryIntegrityError(
                "invalid property "
                "semantic_labels JSON"
            ) from exc

        if not isinstance(
            labels_raw,
            list,
        ):
            raise MemoryIntegrityError(
                "property semantic_labels "
                "must be JSON array"
            )

        value_type = (
            None
            if row[
                "value_type"
            ]
            is None
            else ValueType(
                str(
                    row[
                        "value_type"
                    ]
                )
            )
        )

        return CanonicalProperty(
            id=str(
                row["id"]
            ),
            kind=PropertyKind(
                str(
                    row["kind"]
                )
            ),
            semantic_labels=tuple(
                str(
                    item
                )
                for item
                in labels_raw
            ),
            semantic_type=str(
                row[
                    "semantic_type"
                ]
            ),
            cardinality=Cardinality(
                str(
                    row[
                        "cardinality"
                    ]
                )
            ),
            value_type=value_type,
            status=MemoryStatus(
                str(
                    row[
                        "initial_status"
                    ]
                )
            ),
            created_at=_parse_utc(
                str(
                    row[
                        "created_at"
                    ]
                )
            ),
            schema_version=int(
                row[
                    "schema_version"
                ]
            ),
        )

    def _hydrate_entity(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> Entity:
        try:
            aliases_raw = json.loads(
                str(
                    row[
                        "aliases_json"
                    ]
                )
            )

        except json.JSONDecodeError as exc:
            raise MemoryIntegrityError(
                "invalid entity aliases JSON"
            ) from exc

        if not isinstance(
            aliases_raw,
            list,
        ):
            raise MemoryIntegrityError(
                "entity aliases must be a JSON array"
            )

        sources = self._string_tuple(
            conn,
            """
            SELECT episode_id
            FROM entity_episode_sources
            WHERE entity_id = ?
            ORDER BY episode_id
            """,
            (
                str(
                    row["id"]
                ),
            ),
            "episode_id",
        )

        return Entity(
            id=str(
                row["id"]
            ),
            namespace=MemoryNamespace(
                str(
                    row[
                        "namespace"
                    ]
                )
            ),
            canonical_name=str(
                row[
                    "canonical_name"
                ]
            ),
            entity_type=str(
                row[
                    "entity_type"
                ]
            ),
            aliases=tuple(
                str(
                    item
                )
                for item
                in aliases_raw
            ),
            status=MemoryStatus(
                str(
                    row[
                        "initial_status"
                    ]
                )
            ),
            created_at=_parse_utc(
                str(
                    row[
                        "created_at"
                    ]
                )
            ),
            updated_at=_parse_utc(
                str(
                    row[
                        "updated_at"
                    ]
                )
            ),
            source_episode_ids=(
                sources
            ),
            confidence=float(
                row[
                    "confidence"
                ]
            ),
            metadata=self._metadata(
                str(
                    row[
                        "metadata_json"
                    ]
                )
            ),
            schema_version=int(
                row[
                    "schema_version"
                ]
            ),
        )

    def _hydrate_episode(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> MemoryEpisode:
        subject_hints = (
            self._string_tuple(
                conn,
                """
                SELECT entity_id
                FROM episode_subject_hints
                WHERE episode_id = ?
                ORDER BY entity_id
                """,
                (
                    str(
                        row["id"]
                    ),
                ),
                "entity_id",
            )
        )

        return MemoryEpisode(
            id=str(
                row["id"]
            ),
            conversation_id=(
                None
                if row[
                    "conversation_id"
                ]
                is None
                else str(
                    row[
                        "conversation_id"
                    ]
                )
            ),
            sequence=(
                None
                if row[
                    "sequence"
                ]
                is None
                else int(
                    row[
                        "sequence"
                    ]
                )
            ),
            occurred_at=_parse_utc(
                str(
                    row[
                        "occurred_at"
                    ]
                )
            ),
            recorded_at=_parse_utc(
                str(
                    row[
                        "recorded_at"
                    ]
                )
            ),
            speaker_entity_id=(
                None
                if row[
                    "speaker_entity_id"
                ]
                is None
                else str(
                    row[
                        "speaker_entity_id"
                    ]
                )
            ),
            source_type=SourceType(
                str(
                    row[
                        "source_type"
                    ]
                )
            ),
            raw_text=str(
                row[
                    "raw_text"
                ]
            ),
            normalized_text=(
                None
                if row[
                    "normalized_text"
                ]
                is None
                else str(
                    row[
                        "normalized_text"
                    ]
                )
            ),
            content_hash=str(
                row[
                    "content_hash"
                ]
            ),
            explicit_memory_request=bool(
                int(
                    row[
                        "explicit_memory_request"
                    ]
                )
            ),
            subject_hints=(
                subject_hints
            ),
            metadata=self._metadata(
                str(
                    row[
                        "metadata_json"
                    ]
                )
            ),
            schema_version=int(
                row[
                    "schema_version"
                ]
            ),
        )

    def _hydrate_fact(self, conn: sqlite3.Connection, row: sqlite3.Row, *, as_of_revision: int | None=None) -> MemoryFact:
        fact_id = str(row['id'])
        source_episodes = self._string_tuple(conn, '\n            SELECT episode_id\n            FROM fact_episode_sources\n            WHERE fact_id = ?\n            ORDER BY episode_id\n            ', (fact_id,), 'episode_id')
        source_facts = self._string_tuple(conn, '\n            SELECT source_fact_id\n            FROM fact_fact_sources\n            WHERE fact_id = ?\n            ORDER BY source_fact_id\n            ', (fact_id,), 'source_fact_id')
        supersedes = self._string_tuple(conn, '\n            SELECT old_fact_id\n            FROM fact_supersessions\n            WHERE new_fact_id = ?\n            ORDER BY created_revision, old_fact_id\n            ', (fact_id,), 'old_fact_id')
        contradicts = self._string_tuple(conn, '\n            SELECT contradicting_fact_id\n            FROM fact_contradictions\n            WHERE fact_id = ?\n            ORDER BY created_revision, contradicting_fact_id\n            ', (fact_id,), 'contradicting_fact_id')
        try:
            value = json.loads(str(row['value_json']))
        except json.JSONDecodeError as exc:
            raise MemoryIntegrityError('invalid fact value JSON') from exc
        memory_value = MemoryValue(value_type=ValueType(str(row['value_type'])), value=value, unit=None if row['unit'] is None else str(row['unit']), entity_id=None if row['value_entity_id'] is None else str(row['value_entity_id']), raw_representation=None if row['raw_representation'] is None else str(row['raw_representation']))
        return MemoryFact(id=fact_id, subject_entity_id=str(row['subject_entity_id']), property_id=str(row['property_id']), value=memory_value, memory_class=MemoryClass(str(row['memory_class'])), authority=MemoryAuthority(str(row['authority'])), confidence=float(row['confidence']), status=self._fact_status(conn, fact_id=fact_id, initial_status=str(row['initial_status']), as_of_revision=as_of_revision), valid_from=_parse_utc(row['valid_from']), valid_until=_parse_utc(row['valid_until']), recorded_at=_parse_utc(str(row['recorded_at'])), source_episode_ids=source_episodes, source_fact_ids=source_facts, supersedes_fact_ids=supersedes, contradicts_fact_ids=contradicts, canonical_key=str(row['canonical_key']), metadata=self._metadata(str(row['metadata_json'])), schema_version=int(row['schema_version']))

    def _hydrate_relation(self, conn: sqlite3.Connection, row: sqlite3.Row, *, as_of_revision: int | None=None) -> MemoryRelation:
        relation_id = str(row['id'])
        source_episodes = self._string_tuple(conn, '\n            SELECT episode_id\n            FROM relation_episode_sources\n            WHERE relation_id = ?\n            ORDER BY episode_id\n            ', (relation_id,), 'episode_id')
        supersedes = self._string_tuple(conn, '\n            SELECT old_relation_id\n            FROM relation_supersessions\n            WHERE new_relation_id = ?\n            ORDER BY created_revision, old_relation_id\n            ', (relation_id,), 'old_relation_id')
        contradicts = self._string_tuple(conn, '\n            SELECT contradicting_relation_id\n            FROM relation_contradictions\n            WHERE relation_id = ?\n            ORDER BY created_revision, contradicting_relation_id\n            ', (relation_id,), 'contradicting_relation_id')
        return MemoryRelation(id=relation_id, source_entity_id=str(row['source_entity_id']), property_id=str(row['property_id']), target_entity_id=str(row['target_entity_id']), memory_class=MemoryClass(str(row['memory_class'])), authority=MemoryAuthority(str(row['authority'])), confidence=float(row['confidence']), status=self._relation_status(conn, relation_id=relation_id, initial_status=str(row['initial_status']), as_of_revision=as_of_revision), valid_from=_parse_utc(row['valid_from']), valid_until=_parse_utc(row['valid_until']), recorded_at=_parse_utc(str(row['recorded_at'])), source_episode_ids=source_episodes, supersedes_relation_ids=supersedes, contradicts_relation_ids=contradicts, canonical_key=str(row['canonical_key']), metadata=self._metadata(str(row['metadata_json'])), schema_version=int(row['schema_version']))

    def get_property(
        self,
        property_id: str,
    ) -> CanonicalProperty | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM properties
                WHERE id = ?
                """,
                (
                    str(
                        property_id
                    ),
                ),
            ).fetchone()

            if row is None:
                return None

            return self._hydrate_property(
                row
            )

        finally:
            conn.close()

    def list_properties(
        self,
        *,
        kind: PropertyKind | None = None,
    ) -> tuple[
        CanonicalProperty,
        ...,
    ]:
        if (
            kind is not None
            and not isinstance(
                kind,
                PropertyKind,
            )
        ):
            raise ValueError(
                "kind must be "
                "PropertyKind or None"
            )

        conn = self._connect()

        try:
            if kind is None:
                rows = tuple(
                    conn.execute(
                        """
                        SELECT *
                        FROM properties
                        ORDER BY
                            created_revision,
                            id
                        """
                    )
                )

            else:
                rows = tuple(
                    conn.execute(
                        """
                        SELECT *
                        FROM properties
                        WHERE kind = ?
                        ORDER BY
                            created_revision,
                            id
                        """,
                        (
                            kind.value,
                        ),
                    )
                )

            return tuple(
                self._hydrate_property(
                    row
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def get_entity(
        self,
        entity_id: str,
    ) -> Entity | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM entities
                WHERE id = ?
                """,
                (
                    str(
                        entity_id
                    ),
                ),
            ).fetchone()

            if row is None:
                return None

            return self._hydrate_entity(
                conn,
                row,
            )

        finally:
            conn.close()

    def list_entities(
        self,
    ) -> tuple[Entity, ...]:
        conn = self._connect()

        try:
            rows = conn.execute(
                """
                SELECT *
                FROM entities
                ORDER BY id
                """
            ).fetchall()

            return tuple(
                self._hydrate_entity(
                    conn,
                    row,
                )
                for row in rows
            )

        finally:
            conn.close()

    def get_episode(
        self,
        episode_id: str,
    ) -> MemoryEpisode | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM episodes
                WHERE id = ?
                """,
                (
                    str(
                        episode_id
                    ),
                ),
            ).fetchone()

            if row is None:
                return None

            return self._hydrate_episode(
                conn,
                row,
            )

        finally:
            conn.close()

    def get_fact(
        self,
        fact_id: str,
    ) -> MemoryFact | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM facts
                WHERE id = ?
                """,
                (
                    str(
                        fact_id
                    ),
                ),
            ).fetchone()

            if row is None:
                return None

            return self._hydrate_fact(
                conn,
                row,
            )

        finally:
            conn.close()

    def get_relation(
        self,
        relation_id: str,
    ) -> MemoryRelation | None:
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT *
                FROM relations
                WHERE id = ?
                """,
                (
                    str(
                        relation_id
                    ),
                ),
            ).fetchone()

            if row is None:
                return None

            return self._hydrate_relation(
                conn,
                row,
            )

        finally:
            conn.close()

    def _validate_read_revision(
        self,
        revision: int,
    ) -> int:
        value = int(
            revision
        )

        current = (
            self.canonical_revision()
        )

        if (
            value < 0
            or value > current
        ):
            raise MemoryIntegrityError(
                (
                    "requested canonical revision "
                    f"{value} outside 0..{current}"
                )
            )

        return value

    def _fact_rows(
        self,
        conn: sqlite3.Connection,
        *,
        subject_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None,
        current_only: bool,
        as_of_revision: int | None,
    ) -> tuple[sqlite3.Row, ...]:
        subjects = tuple(
            dict.fromkeys(
                str(
                    value
                )
                for value
                in subject_entity_ids
                if str(
                    value
                ).strip()
            )
        )

        if not subjects:
            return ()

        clauses = [
            (
                "f.subject_entity_id "
                "IN ("
                + ",".join(
                    "?"
                    for _ in subjects
                )
                + ")"
            )
        ]

        params: list[Any] = list(
            subjects
        )

        property_values = tuple(
            dict.fromkeys(
                str(
                    value
                )
                for value
                in (
                    property_ids
                    or ()
                )
                if str(
                    value
                ).strip()
            )
        )

        if property_values:
            clauses.append(
                (
                    "f.property_id IN ("
                    + ",".join(
                        "?"
                        for _ in (
                            property_values
                        )
                    )
                    + ")"
                )
            )

            params.extend(
                property_values
            )

        if current_only:
            clauses.append(
                "f.initial_status = ?"
            )

            params.append(
                MemoryStatus
                .ACTIVE
                .value
            )

            if (
                as_of_revision
                is None
            ):
                clauses.append(
                    """
                    NOT EXISTS(
                        SELECT 1
                        FROM fact_supersessions AS s
                        WHERE
                            s.old_fact_id = f.id
                    )
                    """
                )

            else:
                clauses.append(
                    "f.created_revision <= ?"
                )

                params.append(
                    as_of_revision
                )

                clauses.append(
                    """
                    NOT EXISTS(
                        SELECT 1
                        FROM fact_supersessions AS s
                        WHERE
                            s.old_fact_id = f.id
                            AND
                            s.created_revision <= ?
                    )
                    """
                )

                params.append(
                    as_of_revision
                )

        sql = (
            """
            SELECT f.*
            FROM facts AS f
            WHERE
            """
            + "\nAND ".join(
                clauses
            )
            + """
            ORDER BY
                f.created_revision,
                f.id
            """
        )

        return tuple(
            conn.execute(
                sql,
                tuple(
                    params
                ),
            ).fetchall()
        )

    def _relation_rows(
        self,
        conn: sqlite3.Connection,
        *,
        source_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None,
        current_only: bool,
        as_of_revision: int | None,
    ) -> tuple[sqlite3.Row, ...]:
        sources = tuple(
            dict.fromkeys(
                str(
                    value
                )
                for value
                in source_entity_ids
                if str(
                    value
                ).strip()
            )
        )

        if not sources:
            return ()

        clauses = [
            (
                "r.source_entity_id "
                "IN ("
                + ",".join(
                    "?"
                    for _ in sources
                )
                + ")"
            )
        ]

        params: list[Any] = list(
            sources
        )

        property_values = tuple(
            dict.fromkeys(
                str(
                    value
                )
                for value
                in (
                    property_ids
                    or ()
                )
                if str(
                    value
                ).strip()
            )
        )

        if property_values:
            clauses.append(
                (
                    "r.property_id IN ("
                    + ",".join(
                        "?"
                        for _ in (
                            property_values
                        )
                    )
                    + ")"
                )
            )

            params.extend(
                property_values
            )

        if current_only:
            clauses.append(
                "r.initial_status = ?"
            )

            params.append(
                MemoryStatus
                .ACTIVE
                .value
            )

            if (
                as_of_revision
                is None
            ):
                clauses.append(
                    """
                    NOT EXISTS(
                        SELECT 1
                        FROM relation_supersessions AS s
                        WHERE
                            s.old_relation_id = r.id
                    )
                    """
                )

            else:
                clauses.append(
                    "r.created_revision <= ?"
                )

                params.append(
                    as_of_revision
                )

                clauses.append(
                    """
                    NOT EXISTS(
                        SELECT 1
                        FROM relation_supersessions AS s
                        WHERE
                            s.old_relation_id = r.id
                            AND
                            s.created_revision <= ?
                    )
                    """
                )

                params.append(
                    as_of_revision
                )

        sql = (
            """
            SELECT r.*
            FROM relations AS r
            WHERE
            """
            + "\nAND ".join(
                clauses
            )
            + """
            ORDER BY
                r.created_revision,
                r.id
            """
        )

        return tuple(
            conn.execute(
                sql,
                tuple(
                    params
                ),
            ).fetchall()
        )

    def query_current_facts(
        self,
        *,
        subject_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryFact, ...]:
        conn = self._connect()

        try:
            rows = self._fact_rows(
                conn,
                subject_entity_ids=(
                    subject_entity_ids
                ),
                property_ids=property_ids,
                current_only=True,
                as_of_revision=None,
            )

            return tuple(
                self._hydrate_fact(
                    conn,
                    row,
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def query_historical_facts(
        self,
        *,
        subject_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryFact, ...]:
        conn = self._connect()

        try:
            rows = self._fact_rows(
                conn,
                subject_entity_ids=(
                    subject_entity_ids
                ),
                property_ids=property_ids,
                current_only=False,
                as_of_revision=None,
            )

            return tuple(
                self._hydrate_fact(
                    conn,
                    row,
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def query_facts_as_of_revision(
        self,
        *,
        revision: int,
        subject_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryFact, ...]:
        checked_revision = (
            self._validate_read_revision(
                revision
            )
        )

        conn = self._connect()

        try:
            rows = self._fact_rows(
                conn,
                subject_entity_ids=(
                    subject_entity_ids
                ),
                property_ids=property_ids,
                current_only=True,
                as_of_revision=(
                    checked_revision
                ),
            )

            return tuple(
                self._hydrate_fact(
                    conn,
                    row,
                    as_of_revision=(
                        checked_revision
                    ),
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def query_current_relations(
        self,
        *,
        source_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryRelation, ...]:
        conn = self._connect()

        try:
            rows = self._relation_rows(
                conn,
                source_entity_ids=(
                    source_entity_ids
                ),
                property_ids=property_ids,
                current_only=True,
                as_of_revision=None,
            )

            return tuple(
                self._hydrate_relation(
                    conn,
                    row,
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def query_historical_relations(
        self,
        *,
        source_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryRelation, ...]:
        conn = self._connect()

        try:
            rows = self._relation_rows(
                conn,
                source_entity_ids=(
                    source_entity_ids
                ),
                property_ids=property_ids,
                current_only=False,
                as_of_revision=None,
            )

            return tuple(
                self._hydrate_relation(
                    conn,
                    row,
                )
                for row
                in rows
            )

        finally:
            conn.close()

    def query_relations_as_of_revision(
        self,
        *,
        revision: int,
        source_entity_ids: tuple[str, ...],
        property_ids: tuple[str, ...] | None = None,
    ) -> tuple[MemoryRelation, ...]:
        checked_revision = (
            self._validate_read_revision(
                revision
            )
        )

        conn = self._connect()

        try:
            rows = self._relation_rows(
                conn,
                source_entity_ids=(
                    source_entity_ids
                ),
                property_ids=property_ids,
                current_only=True,
                as_of_revision=(
                    checked_revision
                ),
            )

            return tuple(
                self._hydrate_relation(
                    conn,
                    row,
                    as_of_revision=(
                        checked_revision
                    ),
                )
                for row
                in rows
            )

        finally:
            conn.close()


    def projection_cursor(
        self,
        name: str,
    ) -> int:
        projection_name = str(
            name or ""
        ).strip()

        if not projection_name:
            raise MemoryIntegrityError(
                "projection name must not be empty"
            )

        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT last_applied_revision
                FROM projection_cursors
                WHERE name = ?
                """,
                (
                    projection_name,
                ),
            ).fetchone()

            if row is None:
                return 0

            value = int(
                row[
                    "last_applied_revision"
                ]
            )

            if value < 0:
                raise MemoryIntegrityError(
                    "projection cursor is negative"
                )

            return value

        finally:
            conn.close()

    def projection_cursors(
        self,
    ) -> dict[str, int]:
        conn = self._connect()

        try:
            result: dict[str, int] = {}

            for row in conn.execute(
                """
                SELECT
                    name,
                    last_applied_revision
                FROM projection_cursors
                ORDER BY name
                """
            ):
                value = int(
                    row[
                        "last_applied_revision"
                    ]
                )

                if value < 0:
                    raise MemoryIntegrityError(
                        "projection cursor is negative"
                    )

                result[
                    str(
                        row["name"]
                    )
                ] = value

            return result

        finally:
            conn.close()

    def advance_projection_cursor(
        self,
        name: str,
        revision: int,
    ) -> int:
        projection_name = str(
            name or ""
        ).strip()

        if not projection_name:
            raise MemoryIntegrityError(
                "projection name must not be empty"
            )

        target_revision = int(
            revision
        )

        if target_revision < 0:
            raise MemoryIntegrityError(
                "projection revision must be >= 0"
            )

        conn = self._connect()

        try:
            conn.execute(
                "BEGIN IMMEDIATE"
            )

            canonical_row = (
                conn.execute(
                    """
                    SELECT value
                    FROM meta
                    WHERE key =
                        'canonical_revision'
                    """
                ).fetchone()
            )

            if canonical_row is None:
                raise MemorySchemaError(
                    "canonical_revision missing"
                )

            canonical_revision = int(
                canonical_row[
                    "value"
                ]
            )

            if (
                target_revision
                > canonical_revision
            ):
                raise MemoryIntegrityError(
                    (
                        "projection cursor cannot "
                        "advance beyond canonical revision"
                    )
                )

            existing_row = (
                conn.execute(
                    """
                    SELECT last_applied_revision
                    FROM projection_cursors
                    WHERE name = ?
                    """,
                    (
                        projection_name,
                    ),
                ).fetchone()
            )

            existing_revision = (
                0
                if existing_row is None
                else int(
                    existing_row[
                        "last_applied_revision"
                    ]
                )
            )

            if (
                target_revision
                < existing_revision
            ):
                raise MemoryIntegrityError(
                    (
                        "projection cursor cannot "
                        "move backwards"
                    )
                )

            conn.execute(
                """
                INSERT INTO projection_cursors(
                    name,
                    last_applied_revision,
                    updated_at
                )
                VALUES(
                    ?, ?, ?
                )
                ON CONFLICT(name)
                DO UPDATE SET
                    last_applied_revision =
                        excluded.last_applied_revision,
                    updated_at =
                        excluded.updated_at
                """,
                (
                    projection_name,
                    target_revision,
                    utc_text(
                        utc_now()
                    ),
                ),
            )

            conn.commit()

            return target_revision

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def verify_consistency(
        self,
    ) -> tuple[
        bool,
        tuple[
            str,
            ...,
        ],
    ]:
        problems: list[str] = []

        conn = self._connect()

        try:
            revision_row = (
                conn.execute(
                    """
                    SELECT value
                    FROM meta
                    WHERE key =
                        'canonical_revision'
                    """
                ).fetchone()
            )

            if revision_row is None:
                return (
                    False,
                    (
                        "canonical_revision:missing",
                    ),
                )

            try:
                canonical_revision = int(
                    revision_row[
                        "value"
                    ]
                )

            except (
                TypeError,
                ValueError,
            ):
                return (
                    False,
                    (
                        "canonical_revision:invalid",
                    ),
                )

            if canonical_revision < 0:
                problems.append(
                    "canonical_revision:negative"
                )

            transactions = tuple(
                conn.execute(
                    """
                    SELECT
                        transaction_id,
                        revision,
                        status
                    FROM transactions
                    ORDER BY revision
                    """
                )
            )

            revisions = [
                int(
                    row[
                        "revision"
                    ]
                )
                for row
                in transactions
            ]

            expected_revisions = list(
                range(
                    1,
                    canonical_revision
                    + 1,
                )
            )

            if revisions != expected_revisions:
                problems.append(
                    "transaction_revision_sequence"
                )

            for transaction in transactions:
                transaction_id = str(
                    transaction[
                        "transaction_id"
                    ]
                )

                transaction_revision = int(
                    transaction[
                        "revision"
                    ]
                )

                if (
                    str(
                        transaction[
                            "status"
                        ]
                    )
                    != TransactionStatus
                    .COMMITTED
                    .value
                ):
                    problems.append(
                        (
                            "transaction:"
                            f"{transaction_id}:"
                            "not_committed"
                        )
                    )

                audit_rows = tuple(
                    conn.execute(
                        """
                        SELECT
                            revision,
                            event_index,
                            event_type
                        FROM audit_events
                        WHERE transaction_id = ?
                        ORDER BY event_index
                        """,
                        (
                            transaction_id,
                        ),
                    )
                )

                if not audit_rows:
                    problems.append(
                        (
                            "transaction:"
                            f"{transaction_id}:"
                            "missing_audit"
                        )
                    )

                    continue

                event_indices = [
                    int(
                        row[
                            "event_index"
                        ]
                    )
                    for row
                    in audit_rows
                ]

                if event_indices != list(
                    range(
                        len(
                            audit_rows
                        )
                    )
                ):
                    problems.append(
                        (
                            "transaction:"
                            f"{transaction_id}:"
                            "audit_index_sequence"
                        )
                    )

                if any(
                    int(
                        row[
                            "revision"
                        ]
                    )
                    != transaction_revision
                    for row
                    in audit_rows
                ):
                    problems.append(
                        (
                            "transaction:"
                            f"{transaction_id}:"
                            "audit_revision"
                        )
                    )

                if (
                    str(
                        audit_rows[-1][
                            "event_type"
                        ]
                    )
                    != AuditEventType
                    .TRANSACTION_COMMITTED
                    .value
                ):
                    problems.append(
                        (
                            "transaction:"
                            f"{transaction_id}:"
                            "missing_terminal_commit_event"
                        )
                    )

            revision_bound_tables = (
                (
                    "entities",
                    "id",
                    "created_transaction_id",
                    "created_revision",
                ),
                (
                    "properties",
                    "id",
                    "created_transaction_id",
                    "created_revision",
                ),
                (
                    "episodes",
                    "id",
                    "created_transaction_id",
                    "created_revision",
                ),
                (
                    "facts",
                    "id",
                    "created_transaction_id",
                    "created_revision",
                ),
                (
                    "relations",
                    "id",
                    "created_transaction_id",
                    "created_revision",
                ),
                (
                    "fact_supersessions",
                    "old_fact_id",
                    "transaction_id",
                    "created_revision",
                ),
                (
                    "relation_supersessions",
                    "old_relation_id",
                    "transaction_id",
                    "created_revision",
                ),
                (
                    "fact_contradictions",
                    "fact_id",
                    "transaction_id",
                    "created_revision",
                ),
                (
                    "relation_contradictions",
                    "relation_id",
                    "transaction_id",
                    "created_revision",
                ),
            )

            for (
                table_name,
                identifier_column,
                transaction_column,
                revision_column,
            ) in revision_bound_tables:
                mismatch = conn.execute(
                    f"""
                    SELECT
                        r.{identifier_column}
                        AS record_id
                    FROM
                        {table_name} AS r
                    LEFT JOIN
                        transactions AS t
                        ON
                            t.transaction_id
                            =
                            r.{transaction_column}
                    WHERE
                        t.transaction_id
                            IS NULL
                        OR
                        r.{revision_column}
                            <>
                            t.revision
                        OR
                        t.status
                            <>
                            ?
                        OR
                        r.{revision_column}
                            >
                            ?
                    LIMIT 1
                    """,
                    (
                        TransactionStatus
                        .COMMITTED
                        .value,
                        canonical_revision,
                    ),
                ).fetchone()

                if mismatch is not None:
                    problems.append(
                        (
                            f"{table_name}:"
                            f"{mismatch['record_id']}:"
                            "revision_binding"
                        )
                    )

            for row in conn.execute(
                """
                SELECT
                    name,
                    last_applied_revision
                FROM projection_cursors
                ORDER BY name
                """
            ):
                projection_name = str(
                    row[
                        "name"
                    ]
                )

                projection_revision = int(
                    row[
                        "last_applied_revision"
                    ]
                )

                if (
                    projection_revision < 0
                    or projection_revision
                    > canonical_revision
                ):
                    problems.append(
                        (
                            "projection:"
                            f"{projection_name}:"
                            "revision_out_of_range"
                        )
                    )

        except Exception as exc:
            problems.append(
                (
                    f"{type(exc).__name__}:"
                    f"{exc}"
                )
            )

        finally:
            conn.close()

        return (
            not problems,
            tuple(
                problems
            ),
        )

    def verify_audit_chain(
        self,
    ) -> tuple[
        bool,
        tuple[
            str,
            ...,
        ],
    ]:
        problems: list[str] = []

        previous_hash = (
            _GENESIS_AUDIT_HASH
        )

        conn = self._connect()

        try:
            rows = conn.execute(
                """
                SELECT
                    id,
                    transaction_id,
                    revision,
                    event_index,
                    event_type,
                    record_id,
                    record_type,
                    actor_entity_id,
                    timestamp,
                    details_json,
                    previous_hash,
                    event_hash,
                    schema_version
                FROM audit_events
                ORDER BY
                    revision,
                    event_index
                """
            ).fetchall()

            for row in rows:
                try:
                    details = json.loads(
                        str(
                            row[
                                "details_json"
                            ]
                        )
                    )

                except json.JSONDecodeError:
                    problems.append(
                        (
                            f"audit:{row['id']}:"
                            "invalid_details_json"
                        )
                    )
                    break

                payload = {
                    "id":
                        str(
                            row["id"]
                        ),
                    "transaction_id":
                        str(
                            row[
                                "transaction_id"
                            ]
                        ),
                    "revision":
                        int(
                            row["revision"]
                        ),
                    "event_index":
                        int(
                            row[
                                "event_index"
                            ]
                        ),
                    "event_type":
                        str(
                            row[
                                "event_type"
                            ]
                        ),
                    "record_id":
                        row["record_id"],
                    "record_type":
                        row["record_type"],
                    "actor_entity_id":
                        row[
                            "actor_entity_id"
                        ],
                    "timestamp":
                        str(
                            row["timestamp"]
                        ),
                    "details":
                        details,
                    "schema_version":
                        int(
                            row[
                                "schema_version"
                            ]
                        ),
                }

                stored_previous = str(
                    row[
                        "previous_hash"
                    ]
                )

                if (
                    stored_previous
                    != previous_hash
                ):
                    problems.append(
                        (
                            f"audit:{row['id']}:"
                            "previous_hash"
                        )
                    )
                    break

                expected_hash = (
                    _audit_digest(
                        previous_hash,
                        payload,
                    )
                )

                if (
                    str(
                        row[
                            "event_hash"
                        ]
                    )
                    != expected_hash
                ):
                    problems.append(
                        (
                            f"audit:{row['id']}:"
                            "event_hash"
                        )
                    )
                    break

                previous_hash = (
                    expected_hash
                )

            tx_mismatch = (
                conn.execute(
                    """
                    SELECT a.id
                    FROM
                        audit_events AS a
                    JOIN
                        transactions AS t
                        ON
                            t.transaction_id
                            =
                            a.transaction_id
                    WHERE
                        a.revision
                        <>
                        t.revision
                    LIMIT 1
                    """
                ).fetchone()
            )

            if tx_mismatch is not None:
                problems.append(
                    (
                        f"audit:"
                        f"{tx_mismatch['id']}:"
                        "revision_mismatch"
                    )
                )

        finally:
            conn.close()

        return (
            not problems,
            tuple(
                problems
            ),
        )

    def integrity_check(
        self,
    ) -> tuple[
        bool,
        tuple[
            str,
            ...,
        ],
    ]:
        problems: list[str] = []

        conn = self._connect()

        try:
            rows = tuple(
                str(
                    row[0]
                )
                for row
                in conn.execute(
                    (
                        "PRAGMA "
                        "integrity_check"
                    )
                )
            )

            if rows != (
                "ok",
            ):
                problems.extend(
                    rows
                )

            for row in conn.execute(
                (
                    "PRAGMA "
                    "foreign_key_check"
                )
            ):
                problems.append(
                    (
                        "foreign_key:"
                        + ":".join(
                            str(
                                value
                            )
                            for value
                            in row
                        )
                    )
                )

            self._validate_schema(
                conn
            )

        except Exception as exc:
            problems.append(
                (
                    f"{type(exc).__name__}:"
                    f"{exc}"
                )
            )

        finally:
            conn.close()

        (
            audit_ok,
            audit_problems,
        ) = self.verify_audit_chain()

        if not audit_ok:
            problems.extend(
                audit_problems
            )

        (
            consistency_ok,
            consistency_problems,
        ) = self.verify_consistency()

        if not consistency_ok:
            problems.extend(
                consistency_problems
            )

        return (
            not problems,
            tuple(
                problems
            ),
        )

    def assert_integrity(
        self,
    ) -> None:
        ok, problems = (
            self.integrity_check()
        )

        if not ok:
            raise MemoryIntegrityError(
                "; ".join(
                    problems
                )
            )
