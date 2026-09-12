from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Entity,
    MemoryNamespace,
)
from jarvis_core.memory.errors import (
    MemoryIntegrityError,
)


class Memory1RecoveryProjectionTests(
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

        self.store = (
            CanonicalMemoryStore(
                self.path
            )
        )

    def tearDown(
        self,
    ):
        self.tmp.cleanup()

    def commit_owner(
        self,
    ):
        owner = Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
        )

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_entity(
            owner
        )

        receipt = tx.commit()

        return (
            owner,
            receipt,
        )

    def counts(
        self,
    ):
        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            return {
                table:
                    conn.execute(
                        (
                            "SELECT COUNT(*) "
                            f"FROM {table}"
                        )
                    ).fetchone()[0]
                for table
                in (
                    "transactions",
                    "entities",
                    "audit_events",
                )
            }

        finally:
            conn.close()

    def test_empty_store_consistency_is_green(
        self,
    ):
        ok, problems = (
            self.store
            .verify_consistency()
        )

        self.assertTrue(
            ok,
            problems,
        )

        self.assertEqual(
            problems,
            (),
        )

    def test_committed_store_consistency_is_green(
        self,
    ):
        self.commit_owner()

        ok, problems = (
            self.store
            .verify_consistency()
        )

        self.assertTrue(
            ok,
            problems,
        )

    def test_missing_projection_cursor_is_zero(
        self,
    ):
        self.assertEqual(
            self.store
            .projection_cursor(
                "fts"
            ),
            0,
        )

        self.assertEqual(
            self.store
            .projection_cursors(),
            {},
        )

    def test_projection_cursor_advances_and_survives_reopen(
        self,
    ):
        _, receipt = (
            self.commit_owner()
        )

        self.assertEqual(
            receipt
            .canonical_revision,
            1,
        )

        self.assertEqual(
            self.store
            .advance_projection_cursor(
                "fts",
                1,
            ),
            1,
        )

        reopened = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            reopened
            .projection_cursor(
                "fts"
            ),
            1,
        )

        self.assertEqual(
            reopened
            .projection_cursors(),
            {
                "fts": 1,
            },
        )

        self.assertEqual(
            reopened
            .canonical_revision(),
            1,
        )

    def test_projection_cursor_cannot_exceed_canonical_revision(
        self,
    ):
        self.commit_owner()

        with self.assertRaises(
            MemoryIntegrityError
        ):
            (
                self.store
                .advance_projection_cursor(
                    "vector",
                    2,
                )
            )

        self.assertEqual(
            self.store
            .projection_cursor(
                "vector"
            ),
            0,
        )

    def test_projection_cursor_cannot_move_backwards(
        self,
    ):
        self.commit_owner()

        self.store.advance_projection_cursor(
            "graph",
            1,
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            (
                self.store
                .advance_projection_cursor(
                    "graph",
                    0,
                )
            )

        self.assertEqual(
            self.store
            .projection_cursor(
                "graph"
            ),
            1,
        )

        self.assertEqual(
            self.store
            .advance_projection_cursor(
                "graph",
                1,
            ),
            1,
        )

    def test_abrupt_process_exit_rolls_back_open_transaction(
        self,
    ):
        entity_id = (
            "00000000-0000-4000-"
            "8000-000000000101"
        )

        child = r"""
import os
import sys

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Entity,
    MemoryNamespace,
)

store = CanonicalMemoryStore(
    sys.argv[1]
)

owner = Entity(
    id=sys.argv[2],
    namespace=MemoryNamespace.OWNER,
    canonical_name="OWNER",
    entity_type="person",
)

tx = store.begin_transaction()

tx.create_entity(
    owner
)

os._exit(91)
"""

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(
                    self.path
                ),
                entity_id,
            ],
            cwd=str(
                Path.cwd()
            ),
        )

        self.assertEqual(
            result.returncode,
            91,
        )

        reopened = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            reopened
            .canonical_revision(),
            0,
        )

        self.assertIsNone(
            reopened
            .get_entity(
                entity_id
            )
        )

        self.assertEqual(
            self.counts(),
            {
                "transactions": 0,
                "entities": 0,
                "audit_events": 0,
            },
        )

        ok, problems = (
            reopened
            .integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )

    def test_committed_transaction_survives_abrupt_process_exit(
        self,
    ):
        entity_id = (
            "00000000-0000-4000-"
            "8000-000000000102"
        )

        child = r"""
import os
import sys

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Entity,
    MemoryNamespace,
)

store = CanonicalMemoryStore(
    sys.argv[1]
)

owner = Entity(
    id=sys.argv[2],
    namespace=MemoryNamespace.OWNER,
    canonical_name="OWNER",
    entity_type="person",
)

tx = store.begin_transaction()

tx.create_entity(
    owner
)

tx.commit()

os._exit(92)
"""

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(
                    self.path
                ),
                entity_id,
            ],
            cwd=str(
                Path.cwd()
            ),
        )

        self.assertEqual(
            result.returncode,
            92,
        )

        reopened = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.assertEqual(
            reopened
            .canonical_revision(),
            1,
        )

        loaded = (
            reopened
            .get_entity(
                entity_id
            )
        )

        self.assertIsNotNone(
            loaded
        )

        self.assertEqual(
            loaded
            .canonical_name,
            "OWNER",
        )

        ok, problems = (
            reopened
            .integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )

    def test_consistency_detects_canonical_revision_gap(
        self,
    ):
        self.commit_owner()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            conn.execute(
                """
                UPDATE meta
                SET value = '2'
                WHERE key =
                    'canonical_revision'
                """
            )

            conn.commit()

        finally:
            conn.close()

        ok, problems = (
            self.store
            .verify_consistency()
        )

        self.assertFalse(
            ok
        )

        self.assertIn(
            "transaction_revision_sequence",
            problems,
        )

    def test_consistency_detects_projection_ahead_of_canonical(
        self,
    ):
        self.commit_owner()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            conn.execute(
                """
                INSERT INTO projection_cursors(
                    name,
                    last_applied_revision,
                    updated_at
                )
                VALUES(
                    'fts',
                    2,
                    '2026-09-08T12:00:00.000000Z'
                )
                """
            )

            conn.commit()

        finally:
            conn.close()

        ok, problems = (
            self.store
            .verify_consistency()
        )

        self.assertFalse(
            ok
        )

        self.assertTrue(
            any(
                item.startswith(
                    "projection:fts:"
                )
                for item
                in problems
            )
        )

    def test_integrity_check_includes_consistency_verification(
        self,
    ):
        self.commit_owner()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            conn.execute(
                """
                UPDATE transactions
                SET status = 'IN_PROGRESS'
                WHERE revision = 1
                """
            )

            conn.commit()

        finally:
            conn.close()

        consistency_ok, consistency_problems = (
            self.store
            .verify_consistency()
        )

        self.assertFalse(
            consistency_ok
        )

        self.assertTrue(
            consistency_problems
        )

        integrity_ok, integrity_problems = (
            self.store
            .integrity_check()
        )

        self.assertFalse(
            integrity_ok
        )

        self.assertTrue(
            integrity_problems
        )


if __name__ == "__main__":
    unittest.main()
