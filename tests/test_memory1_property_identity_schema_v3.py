from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Cardinality,
    CommitStatus,
    Entity,
    MemoryAuthority,
    MemoryClass,
    MemoryEpisode,
    MemoryNamespace,
    MemoryStatus,
    PropertyKind,
    SourceType,
    ValueType,
)
from jarvis_core.memory.canonical_store import (
    MemorySchemaError,
)
from jarvis_core.memory.enums import (
    SCHEMA_VERSION,
)
from jarvis_core.memory.ids import (
    new_memory_id,
)
from jarvis_core.memory.models import (
    MemoryFact,
    MemoryRelation,
    utc_now,
)


FACT_PROPERTY_ID = (
    "property_"
    "11111111111111111111111111111111"
)

FACT_PROPERTY_DUPLICATE_ID = (
    "property_"
    "22222222222222222222222222222222"
)

RELATION_PROPERTY_ID = (
    "property_"
    "33333333333333333333333333333333"
)


class Memory1PropertyIdentitySchemaV3Tests(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile.TemporaryDirectory()
        )

        self.path = (
            Path(self.tmp.name)
            / "memory1.sqlite3"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _connect(self):
        conn = sqlite3.connect(
            str(self.path)
        )

        conn.row_factory = (
            sqlite3.Row
        )

        return conn

    def _columns(
        self,
        table,
    ):
        conn = self._connect()

        try:
            return tuple(
                str(row["name"])
                for row in conn.execute(
                    f'PRAGMA '
                    f'table_info("{table}")'
                )
            )

        finally:
            conn.close()

    def _foreign_keys(
        self,
        table,
    ):
        conn = self._connect()

        try:
            return tuple(
                tuple(row)
                for row in conn.execute(
                    f'PRAGMA '
                    f'foreign_key_list("{table}")'
                )
            )

        finally:
            conn.close()

    def _table_rows(
        self,
        table,
    ):
        conn = self._connect()

        try:
            return tuple(
                tuple(row)
                for row in conn.execute(
                    f'SELECT * '
                    f'FROM "{table}" '
                    f'ORDER BY rowid'
                )
            )

        finally:
            conn.close()

    def _meta_value(
        self,
        key,
    ):
        conn = self._connect()

        try:
            row = conn.execute(
                """
                SELECT value
                FROM meta
                WHERE key = ?
                """,
                (
                    key,
                ),
            ).fetchone()

            self.assertIsNotNone(
                row
            )

            return str(
                row["value"]
            )

        finally:
            conn.close()

    def _database_snapshot(
        self,
    ):
        conn = self._connect()

        try:
            objects = tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT
                        type,
                        name,
                        tbl_name,
                        sql
                    FROM sqlite_master
                    WHERE
                        name NOT LIKE
                            'sqlite_%'
                    ORDER BY
                        type,
                        name
                    """
                )
            )

            tables = tuple(
                str(row["name"])
                for row in conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE
                        type = 'table'
                        AND name NOT LIKE
                            'sqlite_%'
                    ORDER BY name
                    """
                )
            )

            rows = {}

            for table in tables:
                rows[table] = tuple(
                    tuple(row)
                    for row in conn.execute(
                        f'SELECT * '
                        f'FROM "{table}" '
                        f'ORDER BY rowid'
                    )
                )

            user_version = int(
                conn.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )

            return (
                objects,
                tuple(
                    (
                        table,
                        rows[table],
                    )
                    for table in tables
                ),
                user_version,
            )

        finally:
            conn.close()

    def _preserved_state(
        self,
    ):
        return {
            "canonical_revision":
                self._meta_value(
                    "canonical_revision"
                ),

            "entities":
                self._table_rows(
                    "entities"
                ),

            "episodes":
                self._table_rows(
                    "episodes"
                ),

            "properties":
                self._table_rows(
                    "properties"
                ),

            "transactions":
                self._table_rows(
                    "transactions"
                ),

            "audit_events":
                self._table_rows(
                    "audit_events"
                ),

            "fact_episode_sources":
                self._table_rows(
                    "fact_episode_sources"
                ),

            "fact_fact_sources":
                self._table_rows(
                    "fact_fact_sources"
                ),

            "relation_episode_sources":
                self._table_rows(
                    "relation_episode_sources"
                ),

            "fact_supersessions":
                self._table_rows(
                    "fact_supersessions"
                ),

            "relation_supersessions":
                self._table_rows(
                    "relation_supersessions"
                ),

            "fact_contradictions":
                self._table_rows(
                    "fact_contradictions"
                ),

            "relation_contradictions":
                self._table_rows(
                    "relation_contradictions"
                ),
        }

    def _create_base_journal(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        owner = Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
        )

        target_a = Entity.create(
            namespace=(
                MemoryNamespace.PERSON
            ),
            canonical_name=(
                "Target A"
            ),
            entity_type="person",
        )

        target_b = Entity.create(
            namespace=(
                MemoryNamespace.PERSON
            ),
            canonical_name=(
                "Target B"
            ),
            entity_type="person",
        )

        now = utc_now()

        text = (
            "schema v2 migration fixture"
        )

        episode = MemoryEpisode(
            id=new_memory_id(),
            occurred_at=now,
            recorded_at=now,
            source_type=(
                SourceType.OWNER_TURN
            ),
            raw_text=text,
            content_hash=(
                hashlib.sha256(
                    text.encode(
                        "utf-8"
                    )
                ).hexdigest()
            ),
            speaker_entity_id=(
                owner.id
            ),
            explicit_memory_request=True,
            subject_hints=(
                owner.id,
                target_a.id,
                target_b.id,
            ),
        )

        tx = store.begin_transaction(
            actor_entity_id=(
                owner.id
            )
        )

        tx.create_entity(
            owner
        )

        tx.create_entity(
            target_a
        )

        tx.create_entity(
            target_b
        )

        tx.append_episode(
            episode
        )

        receipt = tx.commit()

        self.assertIs(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            receipt.canonical_revision,
            1,
        )

        self.assertIsNotNone(
            receipt.transaction_id
        )

        return (
            store,
            owner,
            target_a,
            target_b,
            episode,
            receipt.transaction_id,
        )

    def _downgrade_latest_to_v2_shape(
        self,
    ):
        conn = self._connect()

        try:
            self.assertEqual(
                str(
                    conn.execute(
                        """
                        SELECT value
                        FROM meta
                        WHERE key =
                            'schema_version'
                        """
                    ).fetchone()[
                        "value"
                    ]
                ),
                "4",
            )

            self.assertEqual(
                int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM facts
                        """
                    ).fetchone()[0]
                ),
                0,
            )

            self.assertEqual(
                int(
                    conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM relations
                        """
                    ).fetchone()[0]
                ),
                0,
            )

            conn.execute(
                "PRAGMA foreign_keys = OFF"
            )

            self.assertEqual(
                int(
                    conn.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                ),
                0,
            )

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            try:
                conn.execute(
                    """
                    DROP TABLE
                        reserved_property_bindings
                    """
                )

                conn.execute(
                    """
                    CREATE TABLE
                    facts_v2_fixture(
                        id TEXT PRIMARY KEY,
                        schema_version
                            INTEGER NOT NULL,
                        subject_entity_id
                            TEXT NOT NULL
                            REFERENCES
                                entities(id),
                        predicate
                            TEXT NOT NULL,
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
                        cardinality
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
                    relations_v2_fixture(
                        id TEXT PRIMARY KEY,
                        schema_version
                            INTEGER NOT NULL,
                        source_entity_id
                            TEXT NOT NULL
                            REFERENCES
                                entities(id),
                        predicate
                            TEXT NOT NULL,
                        target_entity_id
                            TEXT NOT NULL
                            REFERENCES
                                entities(id),
                        memory_class
                            TEXT NOT NULL,
                        cardinality
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
                    "DROP TABLE facts"
                )

                conn.execute(
                    "DROP TABLE relations"
                )

                conn.execute(
                    """
                    ALTER TABLE
                        facts_v2_fixture
                    RENAME TO facts
                    """
                )

                conn.execute(
                    """
                    ALTER TABLE
                        relations_v2_fixture
                    RENAME TO relations
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX
                    idx_memory1_facts_subject_predicate
                    ON facts(
                        subject_entity_id,
                        predicate
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
                    idx_memory1_relations_source_predicate
                    ON relations(
                        source_entity_id,
                        predicate
                    )
                    """
                )

                conn.execute(
                    """
                    CREATE INDEX
                    idx_memory1_relations_target_predicate
                    ON relations(
                        target_entity_id,
                        predicate
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
                    SET value = '2'
                    WHERE
                        key =
                            'schema_version'
                        AND value = '4'
                    """
                )

                self.assertEqual(
                    cursor.rowcount,
                    1,
                )

                conn.execute(
                    "PRAGMA user_version = 2"
                )

                conn.commit()

            except Exception:
                conn.rollback()
                raise

            finally:
                conn.execute(
                    "PRAGMA foreign_keys = ON"
                )

            self.assertEqual(
                int(
                    conn.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                ),
                1,
            )

        finally:
            conn.close()

    def _insert_property(
        self,
        conn,
        *,
        property_id,
        kind,
        labels,
        cardinality,
        value_type,
        transaction_id,
        created_at,
    ):
        conn.execute(
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
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            (
                property_id,
                2,
                kind.value,
                json.dumps(
                    list(labels),
                    ensure_ascii=False,
                    separators=(
                        ",",
                        ":",
                    ),
                ),
                (
                    "attribute"
                    if kind
                    is PropertyKind.FACT
                    else "relationship"
                ),
                cardinality.value,
                (
                    value_type.value
                    if value_type
                    is not None
                    else None
                ),
                MemoryStatus.ACTIVE.value,
                created_at,
                transaction_id,
                1,
            ),
        )

    def _seed_v2(
        self,
        mode="exact",
    ):
        (
            store,
            owner,
            target_a,
            target_b,
            episode,
            transaction_id,
        ) = self._create_base_journal()

        self._downgrade_latest_to_v2_shape()

        fact_old = new_memory_id()
        fact_new = new_memory_id()

        relation_old = (
            new_memory_id()
        )

        relation_new = (
            new_memory_id()
        )

        now = (
            utc_now()
            .isoformat()
        )

        conn = self._connect()

        try:
            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            try:
                conn.execute(
                    """
                    UPDATE entities
                    SET schema_version = 2
                    """
                )

                conn.execute(
                    """
                    UPDATE episodes
                    SET schema_version = 2
                    """
                )

                if mode == "exact":
                    self._insert_property(
                        conn,
                        property_id=(
                            FACT_PROPERTY_ID
                        ),
                        kind=(
                            PropertyKind.FACT
                        ),
                        labels=(
                            "age",
                        ),
                        cardinality=(
                            Cardinality
                            .TEMPORAL_SINGLE
                        ),
                        value_type=(
                            ValueType.INTEGER
                        ),
                        transaction_id=(
                            transaction_id
                        ),
                        created_at=now,
                    )

                elif mode == "zero":
                    self._insert_property(
                        conn,
                        property_id=(
                            FACT_PROPERTY_ID
                        ),
                        kind=(
                            PropertyKind.FACT
                        ),
                        labels=(
                            "height",
                        ),
                        cardinality=(
                            Cardinality
                            .TEMPORAL_SINGLE
                        ),
                        value_type=(
                            ValueType.INTEGER
                        ),
                        transaction_id=(
                            transaction_id
                        ),
                        created_at=now,
                    )

                elif mode == "multi":
                    self._insert_property(
                        conn,
                        property_id=(
                            FACT_PROPERTY_ID
                        ),
                        kind=(
                            PropertyKind.FACT
                        ),
                        labels=(
                            "age",
                        ),
                        cardinality=(
                            Cardinality
                            .TEMPORAL_SINGLE
                        ),
                        value_type=(
                            ValueType.INTEGER
                        ),
                        transaction_id=(
                            transaction_id
                        ),
                        created_at=now,
                    )

                    self._insert_property(
                        conn,
                        property_id=(
                            FACT_PROPERTY_DUPLICATE_ID
                        ),
                        kind=(
                            PropertyKind.FACT
                        ),
                        labels=(
                            "age",
                        ),
                        cardinality=(
                            Cardinality
                            .TEMPORAL_SINGLE
                        ),
                        value_type=(
                            ValueType.INTEGER
                        ),
                        transaction_id=(
                            transaction_id
                        ),
                        created_at=now,
                    )

                elif mode == "structural":
                    self._insert_property(
                        conn,
                        property_id=(
                            FACT_PROPERTY_ID
                        ),
                        kind=(
                            PropertyKind.FACT
                        ),
                        labels=(
                            "age",
                        ),
                        cardinality=(
                            Cardinality
                            .MULTI_CURRENT
                        ),
                        value_type=(
                            ValueType.INTEGER
                        ),
                        transaction_id=(
                            transaction_id
                        ),
                        created_at=now,
                    )

                else:
                    raise AssertionError(
                        "unknown fixture mode"
                    )

                self._insert_property(
                    conn,
                    property_id=(
                        RELATION_PROPERTY_ID
                    ),
                    kind=(
                        PropertyKind.RELATION
                    ),
                    labels=(
                        "partner",
                    ),
                    cardinality=(
                        Cardinality
                        .TEMPORAL_SINGLE
                    ),
                    value_type=None,
                    transaction_id=(
                        transaction_id
                    ),
                    created_at=now,
                )

                for (
                    fact_id,
                    value,
                    raw_value,
                ) in (
                    (
                        fact_old,
                        37,
                        "37",
                    ),
                    (
                        fact_new,
                        38,
                        "38",
                    ),
                ):
                    conn.execute(
                        """
                        INSERT INTO facts(
                            id,
                            schema_version,
                            subject_entity_id,
                            predicate,
                            value_type,
                            value_json,
                            unit,
                            value_entity_id,
                            raw_representation,
                            memory_class,
                            cardinality,
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
                            ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            fact_id,
                            2,
                            owner.id,
                            "age",
                            ValueType.INTEGER.value,
                            json.dumps(
                                value
                            ),
                            None,
                            None,
                            raw_value,
                            MemoryClass.FACTUAL.value,
                            Cardinality
                            .TEMPORAL_SINGLE
                            .value,
                            MemoryAuthority
                            .OWNER_EXPLICIT
                            .value,
                            1.0,
                            MemoryStatus.ACTIVE.value,
                            None,
                            None,
                            now,
                            (
                                f"{owner.id}"
                                "|age"
                            ),
                            "{}",
                            transaction_id,
                            1,
                        ),
                    )

                for (
                    relation_id,
                    target_id,
                ) in (
                    (
                        relation_old,
                        target_a.id,
                    ),
                    (
                        relation_new,
                        target_b.id,
                    ),
                ):
                    conn.execute(
                        """
                        INSERT INTO relations(
                            id,
                            schema_version,
                            source_entity_id,
                            predicate,
                            target_entity_id,
                            memory_class,
                            cardinality,
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
                            ?, ?, ?
                        )
                        """,
                        (
                            relation_id,
                            2,
                            owner.id,
                            "partner",
                            target_id,
                            MemoryClass
                            .RELATIONAL
                            .value,
                            Cardinality
                            .TEMPORAL_SINGLE
                            .value,
                            MemoryAuthority
                            .OWNER_EXPLICIT
                            .value,
                            1.0,
                            MemoryStatus.ACTIVE.value,
                            None,
                            None,
                            now,
                            (
                                f"{owner.id}"
                                "|partner"
                            ),
                            "{}",
                            transaction_id,
                            1,
                        ),
                    )

                for fact_id in (
                    fact_old,
                    fact_new,
                ):
                    conn.execute(
                        """
                        INSERT INTO
                        fact_episode_sources(
                            fact_id,
                            episode_id
                        )
                        VALUES(?, ?)
                        """,
                        (
                            fact_id,
                            episode.id,
                        ),
                    )

                conn.execute(
                    """
                    INSERT INTO
                    fact_fact_sources(
                        fact_id,
                        source_fact_id
                    )
                    VALUES(?, ?)
                    """,
                    (
                        fact_new,
                        fact_old,
                    ),
                )

                for relation_id in (
                    relation_old,
                    relation_new,
                ):
                    conn.execute(
                        """
                        INSERT INTO
                        relation_episode_sources(
                            relation_id,
                            episode_id
                        )
                        VALUES(?, ?)
                        """,
                        (
                            relation_id,
                            episode.id,
                        ),
                    )

                conn.execute(
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
                        fact_old,
                        fact_new,
                        transaction_id,
                        1,
                        now,
                    ),
                )

                conn.execute(
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
                        relation_old,
                        relation_new,
                        transaction_id,
                        1,
                        now,
                    ),
                )

                conn.execute(
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
                        fact_new,
                        fact_old,
                        transaction_id,
                        1,
                        now,
                    ),
                )

                conn.execute(
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
                        relation_new,
                        relation_old,
                        transaction_id,
                        1,
                        now,
                    ),
                )

                violations = tuple(
                    conn.execute(
                        "PRAGMA foreign_key_check"
                    )
                )

                self.assertEqual(
                    violations,
                    (),
                )

                conn.commit()

            except Exception:
                conn.rollback()
                raise

        finally:
            conn.close()

        self.assertEqual(
            self._meta_value(
                "schema_version"
            ),
            "2",
        )

        self.assertEqual(
            self._meta_value(
                "canonical_revision"
            ),
            "1",
        )

        return {
            "store":
                store,

            "owner_id":
                owner.id,

            "target_a_id":
                target_a.id,

            "target_b_id":
                target_b.id,

            "episode_id":
                episode.id,

            "transaction_id":
                transaction_id,

            "fact_old":
                fact_old,

            "fact_new":
                fact_new,

            "relation_old":
                relation_old,

            "relation_new":
                relation_new,
        }

    def _rows_by_id(
        self,
        table,
    ):
        conn = self._connect()

        try:
            return {
                str(row["id"]):
                    dict(row)
                for row in conn.execute(
                    f'SELECT * '
                    f'FROM "{table}" '
                    f'ORDER BY id'
                )
            }

        finally:
            conn.close()

    def _assert_v3_physical_contract(
        self,
    ):
        fact_columns = (
            self._columns(
                "facts"
            )
        )

        relation_columns = (
            self._columns(
                "relations"
            )
        )

        self.assertIn(
            "property_id",
            fact_columns,
        )

        self.assertNotIn(
            "predicate",
            fact_columns,
        )

        self.assertNotIn(
            "cardinality",
            fact_columns,
        )

        self.assertIn(
            "property_id",
            relation_columns,
        )

        self.assertNotIn(
            "predicate",
            relation_columns,
        )

        self.assertNotIn(
            "cardinality",
            relation_columns,
        )

        fact_fks = (
            self._foreign_keys(
                "facts"
            )
        )

        relation_fks = (
            self._foreign_keys(
                "relations"
            )
        )

        self.assertTrue(
            any(
                (
                    row[2]
                    == "properties"
                    and row[3]
                    == "property_id"
                    and row[4]
                    == "id"
                )
                for row in fact_fks
            )
        )

        self.assertTrue(
            any(
                (
                    row[2]
                    == "properties"
                    and row[3]
                    == "property_id"
                    and row[4]
                    == "id"
                )
                for row in relation_fks
            )
        )

    def _assert_sqlite_integrity(
        self,
    ):
        conn = self._connect()

        try:
            integrity = str(
                conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            )

            foreign_keys = tuple(
                conn.execute(
                    "PRAGMA foreign_key_check"
                )
            )

        finally:
            conn.close()

        self.assertEqual(
            integrity.lower(),
            "ok",
        )

        self.assertEqual(
            foreign_keys,
            (),
        )

    def _assert_successful_mapping(
        self,
        seed,
        before,
        *,
        expected_schema_version="3",
    ):
        self.assertEqual(
            self._meta_value(
                "schema_version"
            ),
            str(
                expected_schema_version
            ),
        )

        self.assertEqual(
            self._meta_value(
                "canonical_revision"
            ),
            before[
                "canonical_revision"
            ],
        )

        self._assert_v3_physical_contract()

        after = (
            self._preserved_state()
        )

        for key in (
            "canonical_revision",
            "entities",
            "episodes",
            "properties",
            "transactions",
            "audit_events",
            "fact_episode_sources",
            "fact_fact_sources",
            "relation_episode_sources",
            "fact_supersessions",
            "relation_supersessions",
            "fact_contradictions",
            "relation_contradictions",
        ):
            self.assertEqual(
                after[key],
                before[key],
                key,
            )

        facts = (
            self._rows_by_id(
                "facts"
            )
        )

        relations = (
            self._rows_by_id(
                "relations"
            )
        )

        self.assertEqual(
            set(facts),
            {
                seed[
                    "fact_old"
                ],
                seed[
                    "fact_new"
                ],
            },
        )

        self.assertEqual(
            set(relations),
            {
                seed[
                    "relation_old"
                ],
                seed[
                    "relation_new"
                ],
            },
        )

        for row in facts.values():
            self.assertEqual(
                int(
                    row[
                        "schema_version"
                    ]
                ),
                3,
            )

            self.assertEqual(
                row[
                    "property_id"
                ],
                FACT_PROPERTY_ID,
            )

            self.assertEqual(
                row[
                    "canonical_key"
                ],
                (
                    f"{seed['owner_id']}"
                    f"|{FACT_PROPERTY_ID}"
                ),
            )

        for row in relations.values():
            self.assertEqual(
                int(
                    row[
                        "schema_version"
                    ]
                ),
                3,
            )

            self.assertEqual(
                row[
                    "property_id"
                ],
                RELATION_PROPERTY_ID,
            )

            self.assertEqual(
                row[
                    "canonical_key"
                ],
                (
                    f"{seed['owner_id']}"
                    f"|{RELATION_PROPERTY_ID}"
                ),
            )

        property_rows = (
            self._rows_by_id(
                "properties"
            )
        )

        self.assertEqual(
            int(
                property_rows[
                    FACT_PROPERTY_ID
                ][
                    "schema_version"
                ]
            ),
            2,
        )

        self.assertEqual(
            int(
                property_rows[
                    RELATION_PROPERTY_ID
                ][
                    "schema_version"
                ]
            ),
            2,
        )

        entity_rows = (
            self._rows_by_id(
                "entities"
            )
        )

        for row in (
            entity_rows.values()
        ):
            self.assertEqual(
                int(
                    row[
                        "schema_version"
                    ]
                ),
                2,
            )

        episode_rows = (
            self._rows_by_id(
                "episodes"
            )
        )

        for row in (
            episode_rows.values()
        ):
            self.assertEqual(
                int(
                    row[
                        "schema_version"
                    ]
                ),
                2,
            )

        self._assert_sqlite_integrity()

        store = seed["store"]

        audit_ok, problems = (
            store.verify_audit_chain()
        )

        self.assertTrue(
            audit_ok,
            problems,
        )

    def _assert_failed_migration_rolls_back(
        self,
        mode,
    ):
        seed = self._seed_v2(
            mode
        )

        before = (
            self._database_snapshot()
        )

        conn = (
            seed["store"]
            ._connect()
        )

        try:
            with self.assertRaises(
                MemorySchemaError
            ):
                (
                    seed["store"]
                    ._migrate_v2_to_v3(
                        conn
                    )
                )

        finally:
            conn.close()

        after = (
            self._database_snapshot()
        )

        self.assertEqual(
            after,
            before,
        )

        self.assertEqual(
            self._meta_value(
                "schema_version"
            ),
            "2",
        )

        fact_columns = (
            self._columns(
                "facts"
            )
        )

        relation_columns = (
            self._columns(
                "relations"
            )
        )

        self.assertIn(
            "predicate",
            fact_columns,
        )

        self.assertIn(
            "cardinality",
            fact_columns,
        )

        self.assertNotIn(
            "property_id",
            fact_columns,
        )

        self.assertIn(
            "predicate",
            relation_columns,
        )

        self.assertIn(
            "cardinality",
            relation_columns,
        )

        self.assertNotIn(
            "property_id",
            relation_columns,
        )

        self._assert_sqlite_integrity()

    def test_fresh_schema_v3_has_first_class_property_identity(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        self.assertEqual(
            SCHEMA_VERSION,
            4,
        )

        self.assertEqual(
            store.schema_version(),
            4,
        )

        self.assertEqual(
            store.canonical_revision(),
            0,
        )

        self.assertIn(
            "property_id",
            MemoryFact
            .__dataclass_fields__,
        )

        self.assertNotIn(
            "predicate",
            MemoryFact
            .__dataclass_fields__,
        )

        self.assertNotIn(
            "cardinality",
            MemoryFact
            .__dataclass_fields__,
        )

        self.assertIn(
            "property_id",
            MemoryRelation
            .__dataclass_fields__,
        )

        self.assertNotIn(
            "predicate",
            MemoryRelation
            .__dataclass_fields__,
        )

        self.assertNotIn(
            "cardinality",
            MemoryRelation
            .__dataclass_fields__,
        )

        for method_name in (
            "query_current_facts",
            "query_historical_facts",
            "query_facts_as_of_revision",
            "query_current_relations",
            "query_historical_relations",
            "query_relations_as_of_revision",
        ):
            signature = inspect.signature(
                getattr(
                    CanonicalMemoryStore,
                    method_name,
                )
            )

            self.assertIn(
                "property_ids",
                signature.parameters,
            )

            self.assertNotIn(
                "predicates",
                signature.parameters,
            )

        self._assert_v3_physical_contract()

        self._assert_sqlite_integrity()

    def test_direct_v2_to_v3_exact_mapping_preserves_canonical_state(
        self,
    ):
        seed = self._seed_v2(
            "exact"
        )

        before = (
            self._preserved_state()
        )

        conn = (
            seed["store"]
            ._connect()
        )

        try:
            result = (
                seed["store"]
                ._migrate_v2_to_v3(
                    conn
                )
            )

        finally:
            conn.close()

        self.assertIsNone(
            result
        )

        self._assert_successful_mapping(
            seed,
            before,
        )

    def test_initializer_automatically_runs_v2_to_v3(
        self,
    ):
        seed = self._seed_v2(
            "exact"
        )

        before = (
            self._preserved_state()
        )

        reopened = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            reopened.schema_version(),
            4,
        )

        self.assertIn(
            "reserved_property_bindings",
            set(
                reopened.table_names()
            ),
        )

        self._assert_successful_mapping(
            seed,
            before,
            expected_schema_version="4",
        )

    def test_v2_to_v3_zero_match_fails_closed_and_rolls_back(
        self,
    ):
        self._assert_failed_migration_rolls_back(
            "zero"
        )

    def test_v2_to_v3_multiple_matches_fail_closed_and_roll_back(
        self,
    ):
        self._assert_failed_migration_rolls_back(
            "multi"
        )

    def test_v2_to_v3_structural_mismatch_fails_closed_and_rolls_back(
        self,
    ):
        self._assert_failed_migration_rolls_back(
            "structural"
        )

    def test_initializer_runs_v1_to_v2_to_v3_sequentially_for_empty_store(
        self,
    ):
        CanonicalMemoryStore(
            self.path
        )

        self._downgrade_latest_to_v2_shape()

        conn = self._connect()

        try:
            conn.execute(
                "PRAGMA foreign_keys = OFF"
            )

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            try:
                conn.execute(
                    "DROP TABLE properties"
                )

                cursor = conn.execute(
                    """
                    UPDATE meta
                    SET value = '1'
                    WHERE
                        key =
                            'schema_version'
                        AND value = '2'
                    """
                )

                self.assertEqual(
                    cursor.rowcount,
                    1,
                )

                conn.execute(
                    "PRAGMA user_version = 1"
                )

                conn.commit()

            except Exception:
                conn.rollback()
                raise

            finally:
                conn.execute(
                    "PRAGMA foreign_keys = ON"
                )

        finally:
            conn.close()

        self.assertEqual(
            self._meta_value(
                "schema_version"
            ),
            "1",
        )

        migrated = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            migrated.schema_version(),
            4,
        )

        self.assertEqual(
            migrated.canonical_revision(),
            0,
        )

        self.assertIn(
            "properties",
            set(
                migrated.table_names()
            ),
        )

        self.assertIn(
            "reserved_property_bindings",
            set(
                migrated.table_names()
            ),
        )

        self._assert_v3_physical_contract()

        self._assert_sqlite_integrity()

    def test_v2_to_v3_migration_has_no_semantic_repair_or_memory_commit_owner(
        self,
    ):
        import ast
        import textwrap

        source = inspect.getsource(
            CanonicalMemoryStore
            ._migrate_v2_to_v3
        )

        tree = ast.parse(
            textwrap.dedent(
                source
            )
        )

        def attribute_chain(
            node,
        ):
            parts = []
            current = node

            while isinstance(
                current,
                ast.Attribute,
            ):
                parts.append(
                    current.attr
                )
                current = current.value

            if isinstance(
                current,
                ast.Name,
            ):
                parts.append(
                    current.id
                )

                return ".".join(
                    reversed(
                        parts
                    )
                )

            return None

        symbol_names = {
            node.id
            for node in ast.walk(
                tree
            )
            if isinstance(
                node,
                ast.Name,
            )
        }

        attribute_chains = {
            chain
            for node in ast.walk(
                tree
            )
            if isinstance(
                node,
                ast.Attribute,
            )
            for chain in (
                attribute_chain(
                    node
                ),
            )
            if chain is not None
        }

        called_chains = set()

        called_names = set()

        for node in ast.walk(
            tree
        ):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            if isinstance(
                node.func,
                ast.Name,
            ):
                called_names.add(
                    node.func.id
                )

            elif isinstance(
                node.func,
                ast.Attribute,
            ):
                chain = (
                    attribute_chain(
                        node.func
                    )
                )

                if chain is not None:
                    called_chains.add(
                        chain
                    )

        all_symbols = (
            symbol_names
            | {
                part
                for chain
                in attribute_chains
                for part
                in chain.split(".")
            }
        )

        for forbidden in (
            "new_property_id",
            "MemoryCommitReceipt",
            "CommitStatus",
        ):
            self.assertNotIn(
                forbidden,
                all_symbols,
            )

        self.assertNotIn(
            "create_property",
            called_names,
        )

        self.assertFalse(
            any(
                chain.endswith(
                    ".create_property"
                )
                for chain
                in called_chains
            )
        )

        for forbidden_call in (
            "casefold",
            "lower",
            "upper",
        ):
            self.assertNotIn(
                forbidden_call,
                called_names,
            )

            self.assertFalse(
                any(
                    chain.endswith(
                        "."
                        + forbidden_call
                    )
                    for chain
                    in called_chains
                )
            )

        for forbidden_owner in (
            "matcher",
            "regex",
            "synonym",
        ):
            self.assertFalse(
                any(
                    forbidden_owner
                    in symbol.lower()
                    for symbol
                    in all_symbols
                )
            )

        semantic_label_memberships = 0

        cardinality_value_comparisons = 0

        value_type_value_comparisons = 0

        for node in ast.walk(
            tree
        ):
            if not isinstance(
                node,
                ast.Compare,
            ):
                continue

            chains = {
                chain
                for expression in (
                    node.left,
                    *node.comparators,
                )
                for child
                in ast.walk(
                    expression
                )
                if isinstance(
                    child,
                    ast.Attribute,
                )
                for chain in (
                    attribute_chain(
                        child
                    ),
                )
                if chain is not None
            }

            if (
                any(
                    isinstance(
                        operator,
                        ast.In,
                    )
                    for operator
                    in node.ops
                )
                and any(
                    chain.endswith(
                        ".semantic_labels"
                    )
                    for chain
                    in chains
                )
            ):
                semantic_label_memberships += 1

            if (
                any(
                    chain.endswith(
                        ".cardinality.value"
                    )
                    for chain
                    in chains
                )
            ):
                cardinality_value_comparisons += 1

            if (
                any(
                    chain.endswith(
                        ".value_type.value"
                    )
                    for chain
                    in chains
                )
            ):
                value_type_value_comparisons += 1

        self.assertGreaterEqual(
            semantic_label_memberships,
            2,
        )

        self.assertGreaterEqual(
            cardinality_value_comparisons,
            2,
        )

        self.assertGreaterEqual(
            value_type_value_comparisons,
            1,
        )

        self.assertIn(
            "PropertyKind.FACT",
            attribute_chains,
        )

        self.assertIn(
            "PropertyKind.RELATION",
            attribute_chains,
        )

        rollback_calls = (
            int(
                "conn.rollback"
                in called_chains
            )
        )

        self.assertEqual(
            rollback_calls,
            1,
        )


if __name__ == "__main__":
    unittest.main()
