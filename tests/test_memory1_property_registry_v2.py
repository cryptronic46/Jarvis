from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest

from jarvis_core.memory import (
    CanonicalMemoryStore,
    CanonicalProperty,
    Cardinality,
    CommitStatus,
    Entity,
    MemoryAuthority,
    MemoryClass,
    MemoryEpisode,
    MemoryFact,
    MemoryNamespace,
    MemoryRelation,
    MemoryStatus,
    MemoryValue,
    PropertyKind,
    SourceType,
    ValueType,
)
from jarvis_core.memory.enums import (
    MEMORY_CONTRACT_VERSION,
    SCHEMA_VERSION,
)
from jarvis_core.memory.errors import (
    MemorySchemaError,
)
from jarvis_core.memory.ids import (
    new_memory_id,
)
from jarvis_core.memory.models import (
    utc_now,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    CandidateCatalog,
    IdentityResolutionAction,
    IdentitySelection,
    resolve_with_matcher,
)


def content_hash(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


class NewIdentityMatcher:
    def select_identity(
        self,
        *,
        domain,
        semantic_labels,
        semantic_type,
        candidates,
    ):
        return IdentitySelection(
            action=(
                IdentityResolutionAction.NEW
            ),
            confidence=1.0,
        )


def new_property_id(
    *,
    labels: tuple[str, ...],
    semantic_type: str,
) -> str:
    result = resolve_with_matcher(
        catalog=CandidateCatalog(
            domain=(
                CanonicalIdentityDomain.PROPERTY
            ),
            candidates=(),
        ),
        matcher=NewIdentityMatcher(),
        semantic_labels=labels,
        semantic_type=semantic_type,
    )

    if (
        result.action
        is not IdentityResolutionAction.NEW
        or result.canonical_id is None
    ):
        raise AssertionError(
            "Core did not mint property ID"
        )

    return result.canonical_id


class Memory1PropertyRegistryV2Tests(
    unittest.TestCase
):
    def setUp(
        self,
    ):
        self.tmp = (
            tempfile.TemporaryDirectory()
        )

        self.path = (
            Path(
                self.tmp.name
            )
            / "memory1.sqlite3"
        )

    def tearDown(
        self,
    ):
        self.tmp.cleanup()

    def fact_property(
        self,
        *,
        label: str = "semantic_attribute",
    ) -> CanonicalProperty:
        return CanonicalProperty(
            id=new_property_id(
                labels=(
                    label,
                ),
                semantic_type="attribute",
            ),
            kind=PropertyKind.FACT,
            semantic_labels=(
                label,
            ),
            semantic_type="attribute",
            cardinality=(
                Cardinality.SINGLE_CURRENT
            ),
            value_type=ValueType.STRING,
        )

    def relation_property(
        self,
    ) -> CanonicalProperty:
        return CanonicalProperty(
            id=new_property_id(
                labels=(
                    "semantic_relation",
                ),
                semantic_type="relationship",
            ),
            kind=PropertyKind.RELATION,
            semantic_labels=(
                "semantic_relation",
            ),
            semantic_type="relationship",
            cardinality=(
                Cardinality.MULTI_CURRENT
            ),
            value_type=None,
        )

    def _downgrade_latest_to_v1_shape(
        self,
    ) -> None:
        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        conn.row_factory = sqlite3.Row

        try:
            latest_version = int(
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
            )

            self.assertEqual(
                latest_version,
                4,
            )

            fact_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM facts
                    """
                ).fetchone()[0]
            )

            relation_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM relations
                    """
                ).fetchone()[0]
            )

            self.assertEqual(
                fact_count,
                0,
            )

            self.assertEqual(
                relation_count,
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
                    CREATE TABLE
                    facts_v1_fixture(
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
                    relations_v1_fixture(
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
                        facts_v1_fixture
                    RENAME TO facts
                    """
                )

                conn.execute(
                    """
                    ALTER TABLE
                        relations_v1_fixture
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

                conn.execute(
                    """
                    DROP TABLE
                        reserved_property_bindings
                    """
                )

                conn.execute(
                    """
                    DROP TABLE properties
                    """
                )

                cursor = conn.execute(
                    """
                    UPDATE meta
                    SET value = '1'
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

            self.assertEqual(
                int(
                    conn.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]
                ),
                1,
            )

            tables = {
                str(row[0])
                for row in conn.execute(
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

            self.assertNotIn(
                "properties",
                tables,
            )

            self.assertNotIn(
                "reserved_property_bindings",
                tables,
            )

            fact_columns = {
                str(row["name"])
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        "facts"
                    )
                    """
                )
            }

            relation_columns = {
                str(row["name"])
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        "relations"
                    )
                    """
                )
            }

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

            violations = tuple(
                conn.execute(
                    "PRAGMA foreign_key_check"
                )
            )

            self.assertEqual(
                violations,
                (),
            )

        finally:
            conn.close()

    def _raw_state(
        self,
    ) -> dict[str, object]:
        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            return {
                "facts":
                    tuple(
                        conn.execute(
                            """
                            SELECT *
                            FROM facts
                            ORDER BY id
                            """
                        )
                    ),
                "relations":
                    tuple(
                        conn.execute(
                            """
                            SELECT *
                            FROM relations
                            ORDER BY id
                            """
                        )
                    ),
                "entities":
                    tuple(
                        conn.execute(
                            """
                            SELECT *
                            FROM entities
                            ORDER BY id
                            """
                        )
                    ),
                "transactions":
                    int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM transactions
                            """
                        ).fetchone()[0]
                    ),
                "audit":
                    int(
                        conn.execute(
                            """
                            SELECT COUNT(*)
                            FROM audit_events
                            """
                        ).fetchone()[0]
                    ),
                "revision":
                    int(
                        conn.execute(
                            """
                            SELECT value
                            FROM meta
                            WHERE key =
                                'canonical_revision'
                            """
                        ).fetchone()[0]
                    ),
            }

        finally:
            conn.close()

    def _create_v1_assertion_fixture(
        self,
        store: CanonicalMemoryStore,
    ) -> None:
        owner = Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
        )

        person = Entity.create(
            namespace=(
                MemoryNamespace.PERSON
            ),
            canonical_name=(
                "Example Person"
            ),
            entity_type="person",
        )

        now = utc_now()

        text = (
            "legacy canonical assertion"
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
                content_hash(
                    text
                )
            ),
            speaker_entity_id=(
                owner.id
            ),
            explicit_memory_request=True,
            subject_hints=(
                owner.id,
                person.id,
            ),
        )

        tx = store.begin_transaction()

        tx.create_entity(
            owner
        )

        tx.create_entity(
            person
        )

        tx.append_episode(
            episode
        )

        receipt = tx.commit()

        self.assertEqual(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            receipt.canonical_revision,
            1,
        )

        transaction_id = (
            receipt.transaction_id
        )

        self.assertTrue(
            transaction_id
        )

        self._downgrade_latest_to_v1_shape()

        fact_id = new_memory_id()
        relation_id = new_memory_id()

        recorded_at = (
            utc_now()
            .isoformat()
        )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

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
                        1,
                        owner.id,
                        "legacy_attribute",
                        ValueType.INTEGER.value,
                        "1",
                        None,
                        None,
                        "1",
                        MemoryClass.FACTUAL.value,
                        Cardinality
                        .SINGLE_CURRENT
                        .value,
                        MemoryAuthority
                        .OWNER_EXPLICIT
                        .value,
                        1.0,
                        MemoryStatus.ACTIVE.value,
                        None,
                        None,
                        recorded_at,
                        (
                            f"{owner.id}"
                            "|legacy_attribute"
                        ),
                        "{}",
                        transaction_id,
                        1,
                    ),
                )

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
                        1,
                        owner.id,
                        "legacy_relation",
                        person.id,
                        MemoryClass
                        .RELATIONAL
                        .value,
                        Cardinality
                        .MULTI_CURRENT
                        .value,
                        MemoryAuthority
                        .OWNER_EXPLICIT
                        .value,
                        1.0,
                        MemoryStatus.ACTIVE.value,
                        None,
                        None,
                        recorded_at,
                        (
                            f"{owner.id}"
                            "|legacy_relation"
                        ),
                        "{}",
                        transaction_id,
                        1,
                    ),
                )

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

    def test_schema_v2_contains_first_class_property_registry(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        self.assertEqual(
            SCHEMA_VERSION,
            4,
        )

        self._downgrade_latest_to_v1_shape()

        conn = store._connect()

        try:
            result = (
                store._migrate_v1_to_v2(
                    conn
                )
            )

        finally:
            conn.close()

        self.assertIsNone(
            result
        )

        self.assertEqual(
            store.schema_version(),
            2,
        )

        self.assertEqual(
            store.contract_version(),
            MEMORY_CONTRACT_VERSION,
        )

        self.assertIn(
            "properties",
            set(
                store.table_names()
            ),
        )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            user_version = int(
                conn.execute(
                    "PRAGMA user_version"
                ).fetchone()[0]
            )

            fact_columns = {
                str(row[1])
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        "facts"
                    )
                    """
                )
            }

            relation_columns = {
                str(row[1])
                for row in conn.execute(
                    """
                    PRAGMA table_info(
                        "relations"
                    )
                    """
                )
            }

        finally:
            conn.close()

        self.assertEqual(
            user_version,
            2,
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

        self.assertEqual(
            store.list_properties(),
            (),
        )

    def test_canonical_property_contract_is_frozen_and_typed(
        self,
    ):
        property = (
            self.fact_property()
        )

        self.assertEqual(
            property.kind,
            PropertyKind.FACT,
        )

        self.assertEqual(
            property.value_type,
            ValueType.STRING,
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            property.semantic_type = (
                "changed"
            )

        with self.assertRaises(
            ValueError
        ):
            CanonicalProperty(
                id=new_property_id(
                    labels=(
                        "semantic_fact",
                    ),
                    semantic_type="attribute",
                ),
                kind=PropertyKind.FACT,
                semantic_labels=(
                    "semantic_fact",
                ),
                semantic_type="attribute",
                cardinality=(
                    Cardinality.SINGLE_CURRENT
                ),
                value_type=None,
            )

        with self.assertRaises(
            ValueError
        ):
            CanonicalProperty(
                id=new_property_id(
                    labels=(
                        "semantic_relation",
                    ),
                    semantic_type="relationship",
                ),
                kind=PropertyKind.RELATION,
                semantic_labels=(
                    "semantic_relation",
                ),
                semantic_type="relationship",
                cardinality=(
                    Cardinality.MULTI_CURRENT
                ),
                value_type=ValueType.STRING,
            )

    def test_property_semantic_labels_are_evidence_not_normalized_map(
        self,
    ):
        labels = (
            "semantic_form_one",
            "semantic_form_two",
        )

        property = CanonicalProperty(
            id=new_property_id(
                labels=labels,
                semantic_type="attribute",
            ),
            kind=PropertyKind.FACT,
            semantic_labels=labels,
            semantic_type="attribute",
            cardinality=(
                Cardinality.SINGLE_CURRENT
            ),
            value_type=ValueType.STRING,
        )

        self.assertEqual(
            property.semantic_labels,
            labels,
        )

        with self.assertRaises(
            ValueError
        ):
            CanonicalProperty(
                id=new_property_id(
                    labels=(
                        "semantic_form",
                    ),
                    semantic_type="attribute",
                ),
                kind=PropertyKind.FACT,
                semantic_labels=(
                    "semantic_form",
                    "semantic_form",
                ),
                semantic_type="attribute",
                cardinality=(
                    Cardinality.SINGLE_CURRENT
                ),
                value_type=ValueType.STRING,
            )

    def test_property_creation_is_canonical_transaction_and_audited(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        property = (
            self.fact_property()
        )

        before = (
            store.canonical_revision()
        )

        tx = (
            store.begin_transaction()
        )

        created_id = tx.create_property(
            property
        )

        receipt = tx.commit()

        self.assertEqual(
            created_id,
            property.id,
        )

        self.assertEqual(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            receipt.canonical_revision,
            before + 1,
        )

        self.assertEqual(
            store.canonical_revision(),
            before + 1,
        )

        self.assertEqual(
            store.get_property(
                property.id
            ),
            property,
        )

        self.assertEqual(
            store.list_properties(),
            (
                property,
            ),
        )

        self.assertEqual(
            store.list_properties(
                kind=PropertyKind.FACT
            ),
            (
                property,
            ),
        )

        self.assertEqual(
            store.list_properties(
                kind=PropertyKind.RELATION
            ),
            (),
        )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            events = tuple(
                conn.execute(
                    """
                    SELECT
                        event_type,
                        details_json
                    FROM audit_events
                    ORDER BY
                        revision,
                        event_index
                    """
                )
            )

        finally:
            conn.close()

        self.assertEqual(
            events[0][0],
            "PROPERTY_CREATED",
        )

        self.assertEqual(
            events[-1][0],
            "TRANSACTION_COMMITTED",
        )

        commit_details = json.loads(
            events[-1][1]
        )

        self.assertEqual(
            commit_details[
                "property_count"
            ],
            1,
        )

        ok, problems = (
            store.integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )

    def test_property_rollback_does_not_consume_revision(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        property = (
            self.fact_property()
        )

        tx = (
            store.begin_transaction()
        )

        tx.create_property(
            property
        )

        tx.rollback()

        self.assertIsNone(
            store.get_property(
                property.id
            )
        )

        self.assertEqual(
            store.canonical_revision(),
            0,
        )

    def test_fact_and_relation_property_kinds_roundtrip_separately(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        fact_property = (
            self.fact_property()
        )

        relation_property = (
            self.relation_property()
        )

        tx = (
            store.begin_transaction()
        )

        tx.create_property(
            fact_property
        )

        tx.create_property(
            relation_property
        )

        receipt = tx.commit()

        self.assertEqual(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            store.list_properties(
                kind=PropertyKind.FACT
            ),
            (
                fact_property,
            ),
        )

        self.assertEqual(
            store.list_properties(
                kind=PropertyKind.RELATION
            ),
            (
                relation_property,
            ),
        )

    def test_v1_to_v2_migration_preserves_assertions_revision_and_journal(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        self._create_v1_assertion_fixture(
            store
        )

        before = self._raw_state()

        self.assertEqual(
            len(
                before["facts"]
            ),
            1,
        )

        self.assertEqual(
            len(
                before["relations"]
            ),
            1,
        )

        self.assertGreater(
            before["transactions"],
            0,
        )

        self.assertGreater(
            before["audit"],
            0,
        )

        conn = store._connect()

        try:
            result = (
                store._migrate_v1_to_v2(
                    conn
                )
            )

        finally:
            conn.close()

        self.assertIsNone(
            result
        )

        after = self._raw_state()

        self.assertEqual(
            store.schema_version(),
            2,
        )

        self.assertEqual(
            before["facts"],
            after["facts"],
        )

        self.assertEqual(
            before["relations"],
            after["relations"],
        )

        self.assertEqual(
            before["entities"],
            after["entities"],
        )

        self.assertEqual(
            before["revision"],
            after["revision"],
        )

        self.assertEqual(
            before["transactions"],
            after["transactions"],
        )

        self.assertEqual(
            before["audit"],
            after["audit"],
        )

        self.assertEqual(
            store.list_properties(),
            (),
        )

        audit_ok, audit_problems = (
            store.verify_audit_chain()
        )

        self.assertTrue(
            audit_ok,
            audit_problems,
        )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            integrity = str(
                conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
            )

            foreign_key_problems = tuple(
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
            foreign_key_problems,
            (),
        )

    def test_v1_to_v2_migration_does_not_create_memory_commit(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        self._downgrade_latest_to_v1_shape()

        before = self._raw_state()

        self.assertEqual(
            before["revision"],
            0,
        )

        self.assertEqual(
            before["transactions"],
            0,
        )

        self.assertEqual(
            before["audit"],
            0,
        )

        conn = store._connect()

        try:
            result = (
                store._migrate_v1_to_v2(
                    conn
                )
            )

        finally:
            conn.close()

        self.assertIsNone(
            result
        )

        after = self._raw_state()

        self.assertEqual(
            store.schema_version(),
            2,
        )

        self.assertEqual(
            store.canonical_revision(),
            0,
        )

        self.assertEqual(
            before["transactions"],
            after["transactions"],
        )

        self.assertEqual(
            before["audit"],
            after["audit"],
        )

        self.assertEqual(
            before["revision"],
            after["revision"],
        )

        self.assertEqual(
            store.list_properties(),
            (),
        )

    def test_future_schema_is_rejected_before_latest_property_ddl(
        self,
    ):
        CanonicalMemoryStore(
            self.path
        )

        self._downgrade_latest_to_v1_shape()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            conn.execute(
                """
                UPDATE meta
                SET value = '999'
                WHERE key =
                    'schema_version'
                """
            )

            conn.execute(
                "PRAGMA user_version = 999"
            )

            conn.commit()

        finally:
            conn.close()

        with self.assertRaises(
            MemorySchemaError
        ):
            CanonicalMemoryStore(
                self.path
            )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            row = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE
                    type = 'table'
                    AND name =
                        'properties'
                """
            ).fetchone()

            fact_columns = {
                str(item[1])
                for item in conn.execute(
                    """
                    PRAGMA table_info(
                        "facts"
                    )
                    """
                )
            }

        finally:
            conn.close()

        self.assertIsNone(
            row
        )

        self.assertIn(
            "predicate",
            fact_columns,
        )

        self.assertNotIn(
            "property_id",
            fact_columns,
        )

    def test_property_registry_read_api_is_read_only(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        property = (
            self.fact_property()
        )

        tx = (
            store.begin_transaction()
        )

        tx.create_property(
            property
        )

        tx.commit()

        before = (
            store.canonical_revision()
        )

        self.assertEqual(
            store.get_property(
                property.id
            ),
            property,
        )

        self.assertEqual(
            store.list_properties(),
            (
                property,
            ),
        )

        self.assertEqual(
            store.canonical_revision(),
            before,
        )

    def test_property_registry_does_not_change_memory_contract_version(
        self,
    ):
        store = CanonicalMemoryStore(
            self.path
        )

        self.assertEqual(
            MEMORY_CONTRACT_VERSION,
            "1.0",
        )

        self.assertEqual(
            store.contract_version(),
            "1.0",
        )

    def test_model_resolution_boundary_still_hides_canonical_ids(
        self,
    ):
        from jarvis_core.memory.resolution import (
            CanonicalIdentityCandidate,
        )

        secret = new_property_id(
            labels=(
                "semantic_hidden",
            ),
            semantic_type="attribute",
        )

        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain.PROPERTY
            ),
            candidates=(
                CanonicalIdentityCandidate(
                    domain=(
                        CanonicalIdentityDomain.PROPERTY
                    ),
                    canonical_id=secret,
                    semantic_labels=(
                        "semantic_hidden",
                    ),
                    semantic_type="attribute",
                ),
            ),
        )

        views = catalog.model_views()

        self.assertEqual(
            len(views),
            1,
        )

        self.assertFalse(
            hasattr(
                views[0],
                "canonical_id",
            )
        )

        self.assertNotIn(
            secret,
            repr(
                views[0]
            ),
        )
