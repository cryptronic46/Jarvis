from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
)
from datetime import datetime
from pathlib import Path
from uuid import UUID
import sqlite3
import tempfile
import unittest

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Entity,
    MemoryNamespace,
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


class Memory1CanonicalSchemaTests(
    unittest.TestCase
):

    def setUp(
        self,
    ):
        self.tmp = (
            tempfile
            .TemporaryDirectory()
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

    def test_store_uses_wal_foreign_keys_and_full_sync(
        self,
    ):
        store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            store.journal_mode(),
            "wal",
        )

        self.assertTrue(
            store
            .foreign_keys_enabled()
        )

        self.assertIn(
            store.synchronous_mode(),
            {
                2,
                3,
            },
        )

    def test_schema_and_contract_versions_are_frozen(
        self,
    ):
        store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            store.schema_version(),
            SCHEMA_VERSION,
        )

        self.assertEqual(
            store.contract_version(),
            (
                MEMORY_CONTRACT_VERSION
            ),
        )

        self.assertEqual(
            store
            .canonical_revision(),
            0,
        )

    def test_all_canonical_tables_exist(
        self,
    ):
        store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertTrue(
            (
                CanonicalMemoryStore
                .REQUIRED_TABLES
            ).issubset(
                set(
                    store.table_names()
                )
            )
        )

    def test_empty_store_passes_integrity_check(
        self,
    ):
        store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        ok, problems = (
            store.integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )

        self.assertEqual(
            problems,
            (),
        )

    def test_reopen_preserves_revision_and_schema(
        self,
    ):
        first = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            first
            .canonical_revision(),
            0,
        )

        second = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            second
            .canonical_revision(),
            0,
        )

        self.assertEqual(
            second.schema_version(),
            SCHEMA_VERSION,
        )

    def test_schema_version_mismatch_fails_closed(
        self,
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
            conn.execute(
                """
                UPDATE meta
                SET value = '999'
                WHERE key =
                    'schema_version'
                """
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

    def test_memory_ids_are_opaque_valid_uuids(
        self,
    ):
        first = (
            new_memory_id()
        )

        second = (
            new_memory_id()
        )

        self.assertNotEqual(
            first,
            second,
        )

        self.assertEqual(
            str(
                UUID(
                    first
                )
            ),
            first,
        )

        self.assertEqual(
            str(
                UUID(
                    second
                )
            ),
            second,
        )

    def test_contract_objects_are_frozen(
        self,
    ):
        entity = Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            entity.canonical_name = (
                "changed"
            )

    def test_contract_objects_require_timezone_aware_datetimes(
        self,
    ):
        with self.assertRaises(
            Exception
        ):
            Entity(
                id=new_memory_id(),
                namespace=(
                    MemoryNamespace
                    .OWNER
                ),
                canonical_name=(
                    "OWNER"
                ),
                entity_type=(
                    "person"
                ),
                created_at=(
                    datetime.now()
                ),
                updated_at=(
                    datetime.now()
                ),
            )

    def test_memory1_schema_is_independent_from_legacy_index(
        self,
    ):
        store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        names = set(
            store.table_names()
        )

        self.assertNotIn(
            "records_fts",
            names,
        )

        self.assertNotIn(
            "records",
            names,
        )


if __name__ == "__main__":
    unittest.main()
