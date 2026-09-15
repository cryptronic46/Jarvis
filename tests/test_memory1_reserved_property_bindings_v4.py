from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)
from jarvis_core.memory.enums import (
    Cardinality,
    CommitStatus,
    PropertyKind,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryIntegrityError,
)
from jarvis_core.memory.models import (
    CanonicalProperty,
)


PROPERTY_A = (
    "property_"
    "11111111111111111111111111111111"
)

PROPERTY_B = (
    "property_"
    "22222222222222222222222222222222"
)

SLOT_LANGUAGE = (
    "interaction.language"
)

SLOT_VERBOSITY = (
    "interaction.verbosity"
)


class Memory1ReservedPropertyBindingsV4Tests(
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
            / "memory.sqlite3"
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

    def property(
        self,
        property_id=PROPERTY_A,
    ):
        return CanonicalProperty(
            id=property_id,
            kind=PropertyKind.FACT,
            semantic_labels=(
                "test_reserved_property",
            ),
            semantic_type=(
                "reserved_test"
            ),
            cardinality=(
                Cardinality
                .SINGLE_CURRENT
            ),
            value_type=(
                ValueType.STRING
            ),
        )

    def audit_rows(
        self,
        transaction_id,
    ):
        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        conn.row_factory = (
            sqlite3.Row
        )

        try:
            return tuple(
                conn.execute(
                    """
                    SELECT
                        event_type,
                        record_id,
                        record_type,
                        details_json
                    FROM audit_events
                    WHERE transaction_id = ?
                    ORDER BY event_index
                    """,
                    (
                        transaction_id,
                    ),
                )
            )

        finally:
            conn.close()

    def test_empty_store_has_no_reserved_bindings(
        self,
    ):
        self.assertIsNone(
            self.store
            .get_reserved_property_binding(
                SLOT_LANGUAGE
            )
        )

        self.assertEqual(
            self.store
            .list_reserved_property_bindings(),
            (),
        )

    def test_property_and_binding_can_commit_together(
        self,
    ):
        property = self.property()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_property(
            property
        )

        result = (
            tx.bind_reserved_property(
                SLOT_LANGUAGE,
                property.id,
            )
        )

        receipt = tx.commit()

        self.assertEqual(
            result,
            property.id,
        )

        self.assertIs(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            receipt.canonical_revision,
            1,
        )

        self.assertEqual(
            self.store
            .get_reserved_property_binding(
                SLOT_LANGUAGE
            ),
            property.id,
        )

        self.assertEqual(
            self.store
            .list_reserved_property_bindings(),
            (
                (
                    SLOT_LANGUAGE,
                    property.id,
                ),
            ),
        )

        rows = self.audit_rows(
            receipt.transaction_id
        )

        self.assertEqual(
            tuple(
                row["event_type"]
                for row
                in rows
            ),
            (
                "PROPERTY_CREATED",
                "RESERVED_PROPERTY_BOUND",
                "TRANSACTION_COMMITTED",
            ),
        )

        bound_details = json.loads(
            rows[1][
                "details_json"
            ]
        )

        self.assertEqual(
            bound_details,
            {
                "property_id":
                    property.id,
                "slot_name":
                    SLOT_LANGUAGE,
            },
        )

        commit_details = json.loads(
            rows[-1][
                "details_json"
            ]
        )

        self.assertEqual(
            commit_details[
                "property_count"
            ],
            1,
        )

        self.assertEqual(
            commit_details[
                "binding_count"
            ],
            1,
        )

        ok, problems = (
            self.store
            .integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )

    def test_existing_property_can_be_bound_later(
        self,
    ):
        property = self.property()

        tx1 = (
            self.store
            .begin_transaction()
        )

        tx1.create_property(
            property
        )

        first = tx1.commit()

        tx2 = (
            self.store
            .begin_transaction()
        )

        tx2.bind_reserved_property(
            SLOT_LANGUAGE,
            property.id,
        )

        second = tx2.commit()

        self.assertEqual(
            first.canonical_revision,
            1,
        )

        self.assertEqual(
            second.canonical_revision,
            2,
        )

        rows = self.audit_rows(
            second.transaction_id
        )

        self.assertEqual(
            tuple(
                row["event_type"]
                for row
                in rows
            ),
            (
                "RESERVED_PROPERTY_BOUND",
                "TRANSACTION_COMMITTED",
            ),
        )

        commit_details = json.loads(
            rows[-1][
                "details_json"
            ]
        )

        self.assertEqual(
            commit_details[
                "property_count"
            ],
            0,
        )

        self.assertEqual(
            commit_details[
                "binding_count"
            ],
            1,
        )

    def test_same_binding_is_idempotent_no_change(
        self,
    ):
        property = self.property()

        tx1 = (
            self.store
            .begin_transaction()
        )

        tx1.create_property(
            property
        )

        tx1.bind_reserved_property(
            SLOT_LANGUAGE,
            property.id,
        )

        first = tx1.commit()

        before = (
            self.store
            .canonical_revision()
        )

        tx2 = (
            self.store
            .begin_transaction()
        )

        result = (
            tx2.bind_reserved_property(
                SLOT_LANGUAGE,
                property.id,
            )
        )

        second = tx2.commit()

        self.assertEqual(
            result,
            property.id,
        )

        self.assertIs(
            second.status,
            CommitStatus.NO_CHANGE,
        )

        self.assertEqual(
            second.canonical_revision,
            first.canonical_revision,
        )

        self.assertEqual(
            self.store
            .canonical_revision(),
            before,
        )

        self.assertEqual(
            self.store
            .get_reserved_property_binding(
                SLOT_LANGUAGE
            ),
            property.id,
        )

    def test_divergent_slot_binding_fails_closed(
        self,
    ):
        property_a = self.property(
            PROPERTY_A
        )

        property_b = self.property(
            PROPERTY_B
        )

        tx1 = (
            self.store
            .begin_transaction()
        )

        tx1.create_property(
            property_a
        )

        tx1.create_property(
            property_b
        )

        tx1.bind_reserved_property(
            SLOT_LANGUAGE,
            property_a.id,
        )

        tx1.commit()

        before = (
            self.store
            .canonical_revision()
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            with (
                self.store
                .begin_transaction()
            ) as tx2:
                tx2.bind_reserved_property(
                    SLOT_LANGUAGE,
                    property_b.id,
                )

        self.assertEqual(
            self.store
            .canonical_revision(),
            before,
        )

        self.assertEqual(
            self.store
            .get_reserved_property_binding(
                SLOT_LANGUAGE
            ),
            property_a.id,
        )

    def test_property_cannot_claim_two_reserved_slots(
        self,
    ):
        property = self.property()

        tx1 = (
            self.store
            .begin_transaction()
        )

        tx1.create_property(
            property
        )

        tx1.bind_reserved_property(
            SLOT_LANGUAGE,
            property.id,
        )

        tx1.commit()

        before = (
            self.store
            .canonical_revision()
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            with (
                self.store
                .begin_transaction()
            ) as tx2:
                tx2.bind_reserved_property(
                    SLOT_VERBOSITY,
                    property.id,
                )

        self.assertEqual(
            self.store
            .canonical_revision(),
            before,
        )

        self.assertIsNone(
            self.store
            .get_reserved_property_binding(
                SLOT_VERBOSITY
            )
        )

    def test_unknown_property_is_rejected(
        self,
    ):
        before = (
            self.store
            .canonical_revision()
        )

        with self.assertRaises(
            MemoryIntegrityError
        ):
            with (
                self.store
                .begin_transaction()
            ) as tx:
                tx.bind_reserved_property(
                    SLOT_LANGUAGE,
                    PROPERTY_A,
                )

        self.assertEqual(
            self.store
            .canonical_revision(),
            before,
        )

        self.assertEqual(
            self.store
            .list_reserved_property_bindings(),
            (),
        )

    def test_explicit_rollback_removes_binding(
        self,
    ):
        property = self.property()

        tx1 = (
            self.store
            .begin_transaction()
        )

        tx1.create_property(
            property
        )

        tx1.commit()

        before = (
            self.store
            .canonical_revision()
        )

        tx2 = (
            self.store
            .begin_transaction()
        )

        tx2.bind_reserved_property(
            SLOT_LANGUAGE,
            property.id,
        )

        tx2.rollback()

        self.assertEqual(
            self.store
            .canonical_revision(),
            before,
        )

        self.assertIsNone(
            self.store
            .get_reserved_property_binding(
                SLOT_LANGUAGE
            )
        )

    def test_consistency_detects_binding_revision_tamper(
        self,
    ):
        property = self.property()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_property(
            property
        )

        tx.bind_reserved_property(
            SLOT_LANGUAGE,
            property.id,
        )

        tx.commit()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            conn.execute(
                """
                UPDATE reserved_property_bindings
                SET created_revision = 999
                WHERE slot_name = ?
                """,
                (
                    SLOT_LANGUAGE,
                ),
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
                (
                    "reserved_property_bindings:"
                    in problem
                    and
                    "revision_binding"
                    in problem
                )
                for problem
                in problems
            ),
            problems,
        )


if __name__ == "__main__":
    unittest.main()
