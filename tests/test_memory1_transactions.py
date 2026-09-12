from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
import tempfile
import unittest

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Cardinality,
    CommitStatus,
    Entity,
    MemoryAuthority,
    MemoryClass,
    MemoryEpisode,
    MemoryFact,
    MemoryNamespace,
    MemoryStatus,
    MemoryValue,
    SourceType,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryIntegrityError,
)
from jarvis_core.memory.ids import (
    new_memory_id,
)
from jarvis_core.memory.models import (
    utc_now,
)

from jarvis_core.memory import (
    CanonicalProperty,
    PropertyKind,
)

AGE_PROPERTY_ID = "property_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"



def content_hash(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


class Memory1TransactionTests(
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

    def _owner(
        self,
    ):
        return Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
        )

    def _age_property(
        self,
    ) -> CanonicalProperty:
        return CanonicalProperty(
            id=AGE_PROPERTY_ID,
            kind=PropertyKind.FACT,
            semantic_labels=(
                "age",
            ),
            semantic_type="attribute",
            cardinality=(
                Cardinality.TEMPORAL_SINGLE
            ),
            value_type=ValueType.INTEGER,
        )

    def _episode(
        self,
        owner_id: str,
        text: str,
    ):
        now = utc_now()

        return MemoryEpisode(
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
                owner_id
            ),
            explicit_memory_request=True,
            subject_hints=(
                owner_id,
            ),
        )

    def _age_fact(self, owner_id: str, episode_id: str):
        return MemoryFact(id=new_memory_id(), subject_entity_id=owner_id, property_id=AGE_PROPERTY_ID, value=MemoryValue(value_type=ValueType.INTEGER, value=38), memory_class=MemoryClass.FACTUAL, authority=MemoryAuthority.OWNER_EXPLICIT, confidence=1.0, status=MemoryStatus.ACTIVE, recorded_at=utc_now(), canonical_key=f'{owner_id}|{AGE_PROPERTY_ID}', source_episode_ids=(episode_id,))

    def _counts(
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
                    "episodes",
                    "facts",
                    "audit_events",
                )
            }

        finally:
            conn.close()

    def test_atomic_commit_persists_entity_episode_fact_revision_and_receipt(self):
        owner = self._owner()
        episode = self._episode(owner.id, 'Eu tenho 38 anos, guarda esta informa??o.')
        fact = self._age_fact(owner.id, episode.id)
        tx = self.store.begin_transaction(actor_entity_id=owner.id)
        tx.create_entity(owner)
        tx.append_episode(episode)
        tx.create_property(self._age_property())
        tx.create_fact(fact)
        receipt = tx.commit()
        self.assertEqual(receipt.status, CommitStatus.COMMITTED)
        self.assertEqual(receipt.canonical_revision, 1)
        self.assertEqual(receipt.episode_ids, (episode.id,))
        self.assertEqual(receipt.fact_ids, (fact.id,))
        self.assertEqual(receipt.relation_ids, ())
        self.assertEqual(receipt.message_code, 'MEMORY_COMMITTED')
        self.assertEqual(self.store.canonical_revision(), 1)
        counts = self._counts()
        self.assertEqual(counts['transactions'], 1)
        self.assertEqual(counts['entities'], 1)
        self.assertEqual(counts['episodes'], 1)
        self.assertEqual(counts['facts'], 1)
        self.assertEqual(counts['audit_events'], 5)
        ok, problems = self.store.verify_audit_chain()
        self.assertTrue(ok, problems)

    def test_exception_context_rolls_back_everything(
        self,
    ):
        owner = self._owner()

        with self.assertRaises(
            RuntimeError
        ):
            with (
                self.store
                .begin_transaction()
            ) as tx:
                tx.create_entity(
                    owner
                )

                raise RuntimeError(
                    "boom"
                )

        self.assertEqual(
            self.store
            .canonical_revision(),
            0,
        )

        self.assertEqual(
            self._counts(),
            {
                "transactions": 0,
                "entities": 0,
                "episodes": 0,
                "facts": 0,
                "audit_events": 0,
            },
        )

    def test_foreign_key_failure_rolls_back_everything(
        self,
    ):
        episode = self._episode(
            new_memory_id(),
            (
                "facto com speaker "
                "inexistente"
            ),
        )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            with (
                self.store
                .begin_transaction()
            ) as tx:
                tx.append_episode(
                    episode
                )

        self.assertEqual(
            self.store
            .canonical_revision(),
            0,
        )

        counts = self._counts()

        self.assertEqual(
            counts["transactions"],
            0,
        )

        self.assertEqual(
            counts["episodes"],
            0,
        )

        self.assertEqual(
            counts["audit_events"],
            0,
        )

    def test_fact_without_provenance_is_rejected_and_rolled_back(self):
        owner = self._owner()
        fact = MemoryFact(id=new_memory_id(), subject_entity_id=owner.id, property_id=AGE_PROPERTY_ID, value=MemoryValue(value_type=ValueType.INTEGER, value=38), memory_class=MemoryClass.FACTUAL, authority=MemoryAuthority.OWNER_EXPLICIT, confidence=1.0, status=MemoryStatus.ACTIVE, recorded_at=utc_now(), canonical_key=f'{owner.id}|{AGE_PROPERTY_ID}')
        with self.assertRaises(MemoryIntegrityError):
            with self.store.begin_transaction() as tx:
                tx.create_entity(owner)
                tx.create_property(self._age_property())
                tx.create_fact(fact)
        self.assertEqual(self.store.canonical_revision(), 0)
        counts = self._counts()
        self.assertEqual(counts['transactions'], 0)
        self.assertEqual(counts['entities'], 0)
        self.assertEqual(counts['facts'], 0)
        self.assertEqual(counts['audit_events'], 0)

    def test_no_change_commit_does_not_consume_revision(
        self,
    ):
        tx = (
            self.store
            .begin_transaction()
        )

        receipt = tx.commit()

        self.assertEqual(
            receipt.status,
            CommitStatus.NO_CHANGE,
        )

        self.assertEqual(
            receipt
            .canonical_revision,
            0,
        )

        self.assertEqual(
            self.store
            .canonical_revision(),
            0,
        )

        self.assertEqual(
            self._counts()[
                "transactions"
            ],
            0,
        )

        self.assertEqual(
            self._counts()[
                "audit_events"
            ],
            0,
        )

    def test_revisions_are_monotonic_across_commits(self):
        owner = self._owner()
        tx1 = self.store.begin_transaction()
        tx1.create_entity(owner)
        receipt1 = tx1.commit()
        episode = self._episode(owner.id, 'Eu tenho 38 anos.')
        fact = self._age_fact(owner.id, episode.id)
        tx2 = self.store.begin_transaction(actor_entity_id=owner.id)
        tx2.append_episode(episode)
        tx2.create_property(self._age_property())
        tx2.create_fact(fact)
        receipt2 = tx2.commit()
        self.assertEqual(receipt1.canonical_revision, 1)
        self.assertEqual(receipt2.canonical_revision, 2)
        self.assertEqual(self.store.canonical_revision(), 2)
        ok, problems = self.store.verify_audit_chain()
        self.assertTrue(ok, problems)

    def test_committed_rows_are_immediately_visible_to_new_connection(
        self,
    ):
        owner = self._owner()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_entity(
            owner
        )

        receipt = tx.commit()

        self.assertEqual(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            row = conn.execute(
                """
                SELECT canonical_name
                FROM entities
                WHERE id = ?
                """,
                (
                    owner.id,
                ),
            ).fetchone()

        finally:
            conn.close()

        self.assertEqual(
            row[0],
            "OWNER",
        )

    def test_double_commit_fails_closed(
        self,
    ):
        owner = self._owner()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_entity(
            owner
        )

        tx.commit()

        with self.assertRaises(
            MemoryIntegrityError
        ):
            tx.commit()

    def test_audit_tamper_is_detected(
        self,
    ):
        owner = self._owner()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_entity(
            owner
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
                UPDATE audit_events
                SET
                    details_json =
                    '{"tampered":true}'
                WHERE
                    event_index = 0
                """
            )

            conn.commit()

        finally:
            conn.close()

        (
            ok,
            problems,
        ) = (
            self.store
            .verify_audit_chain()
        )

        self.assertFalse(
            ok
        )

        self.assertTrue(
            problems
        )

    def test_integrity_check_includes_audit_chain(
        self,
    ):
        owner = self._owner()

        tx = (
            self.store
            .begin_transaction()
        )

        tx.create_entity(
            owner
        )

        tx.commit()

        (
            ok,
            problems,
        ) = (
            self.store
            .integrity_check()
        )

        self.assertTrue(
            ok,
            problems,
        )


if __name__ == "__main__":
    unittest.main()
