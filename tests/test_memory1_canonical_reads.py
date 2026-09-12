from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
import tempfile
import unittest

from jarvis_core.memory import (
    CanonicalMemoryStore,
    Cardinality,
    Entity,
    MemoryAuthority,
    MemoryClass,
    MemoryEpisode,
    MemoryFact,
    MemoryNamespace,
    MemoryRelation,
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
PARTNER_PROPERTY_ID = "property_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
MISSING_PROPERTY_ID = "property_cccccccccccccccccccccccccccccccc"



def content_hash(
    text: str,
) -> str:
    return hashlib.sha256(
        text.encode(
            "utf-8"
        )
    ).hexdigest()


class Memory1CanonicalReadTests(
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

    def age_property(
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

    def partner_property(
        self,
    ) -> CanonicalProperty:
        return CanonicalProperty(
            id=PARTNER_PROPERTY_ID,
            kind=PropertyKind.RELATION,
            semantic_labels=(
                "partner",
            ),
            semantic_type="relationship",
            cardinality=(
                Cardinality.TEMPORAL_SINGLE
            ),
            value_type=None,
        )

    def tearDown(
        self,
    ):
        self.tmp.cleanup()

    def owner(
        self,
        name: str = "OWNER",
    ) -> Entity:
        return Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name=name,
            entity_type="person",
            aliases=(
                name.lower(),
            ),
        )

    def person(
        self,
        name: str,
    ) -> Entity:
        return Entity.create(
            namespace=(
                MemoryNamespace.PERSON
            ),
            canonical_name=name,
            entity_type="person",
        )

    def episode(
        self,
        owner_id: str,
        text: str,
    ) -> MemoryEpisode:
        now = utc_now()

        return MemoryEpisode(
            id=new_memory_id(),
            occurred_at=now,
            recorded_at=now,
            source_type=(
                SourceType.OWNER_TURN
            ),
            raw_text=text,
            normalized_text=(
                text.lower()
            ),
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
            metadata={
                "language": "pt-PT",
            },
        )

    def age_fact(self, owner_id: str, episode_id: str, age: int, *, supersedes: tuple[str, ...]=()) -> MemoryFact:
        return MemoryFact(id=new_memory_id(), subject_entity_id=owner_id, property_id=AGE_PROPERTY_ID, value=MemoryValue(value_type=ValueType.INTEGER, value=age, raw_representation=str(age)), memory_class=MemoryClass.FACTUAL, authority=MemoryAuthority.OWNER_EXPLICIT, confidence=1.0, status=MemoryStatus.ACTIVE, recorded_at=utc_now(), canonical_key=f'{owner_id}|{AGE_PROPERTY_ID}', source_episode_ids=(episode_id,), supersedes_fact_ids=supersedes, metadata={'test': 'age'})

    def relation(self, owner_id: str, target_id: str, episode_id: str, *, supersedes: tuple[str, ...]=()) -> MemoryRelation:
        return MemoryRelation(id=new_memory_id(), source_entity_id=owner_id, property_id=PARTNER_PROPERTY_ID, target_entity_id=target_id, memory_class=MemoryClass.RELATIONAL, authority=MemoryAuthority.OWNER_EXPLICIT, confidence=1.0, status=MemoryStatus.ACTIVE, recorded_at=utc_now(), canonical_key=f'{owner_id}|{PARTNER_PROPERTY_ID}', source_episode_ids=(episode_id,), supersedes_relation_ids=supersedes)

    def commit_initial_age(self, age: int=38):
        owner = self.owner()
        episode = self.episode(owner.id, f'Eu tenho {age} anos.')
        fact = self.age_fact(owner.id, episode.id, age)
        tx = self.store.begin_transaction(actor_entity_id=owner.id)
        tx.create_entity(owner)
        tx.append_episode(episode)
        tx.create_property(self.age_property())
        tx.create_fact(fact)
        receipt = tx.commit()
        return (owner, episode, fact, receipt)

    def test_roundtrip_reconstructs_entity_episode_and_fact(
        self,
    ):
        (
            owner,
            episode,
            fact,
            _,
        ) = (
            self.commit_initial_age()
        )

        loaded_owner = (
            self.store
            .get_entity(
                owner.id
            )
        )

        loaded_episode = (
            self.store
            .get_episode(
                episode.id
            )
        )

        loaded_fact = (
            self.store
            .get_fact(
                fact.id
            )
        )

        self.assertEqual(
            loaded_owner.id,
            owner.id,
        )

        self.assertEqual(
            loaded_owner.aliases,
            owner.aliases,
        )

        self.assertEqual(
            loaded_episode.raw_text,
            episode.raw_text,
        )

        self.assertEqual(
            loaded_episode
            .subject_hints,
            (
                owner.id,
            ),
        )

        self.assertEqual(
            loaded_episode
            .metadata[
                "language"
            ],
            "pt-PT",
        )

        self.assertEqual(
            loaded_fact.value.value,
            38,
        )

        self.assertEqual(
            loaded_fact
            .source_episode_ids,
            (
                episode.id,
            ),
        )

        self.assertEqual(
            loaded_fact.status,
            MemoryStatus.ACTIVE,
        )

    def test_unknown_ids_return_none(
        self,
    ):
        unknown = new_memory_id()

        self.assertIsNone(
            self.store
            .get_entity(
                unknown
            )
        )

        self.assertIsNone(
            self.store
            .get_episode(
                unknown
            )
        )

        self.assertIsNone(
            self.store
            .get_fact(
                unknown
            )
        )

        self.assertIsNone(
            self.store
            .get_relation(
                unknown
            )
        )

    def test_fact_supersession_preserves_history_and_changes_current_state(self):
        owner, _, old_fact, receipt1 = self.commit_initial_age(38)
        episode2 = self.episode(owner.id, 'Agora tenho 39 anos.')
        new_fact = self.age_fact(owner.id, episode2.id, 39, supersedes=(old_fact.id,))
        tx = self.store.begin_transaction(actor_entity_id=owner.id)
        tx.append_episode(episode2)
        tx.create_fact(new_fact)
        receipt2 = tx.commit()
        self.assertEqual(receipt1.canonical_revision, 1)
        self.assertEqual(receipt2.canonical_revision, 2)
        self.assertEqual(receipt2.superseded_fact_ids, (old_fact.id,))
        current = self.store.query_current_facts(subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].value.value, 39)
        history = self.store.query_historical_facts(subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        self.assertEqual(len(history), 2)
        by_id = {item.id: item for item in history}
        self.assertEqual(by_id[old_fact.id].status, MemoryStatus.SUPERSEDED)
        self.assertEqual(by_id[new_fact.id].status, MemoryStatus.ACTIVE)
        self.assertEqual(by_id[new_fact.id].supersedes_fact_ids, (old_fact.id,))

    def test_supersession_does_not_rewrite_original_fact_row(
        self,
    ):
        (
            owner,
            _,
            old_fact,
            _,
        ) = (
            self.commit_initial_age(
                38
            )
        )

        episode2 = self.episode(
            owner.id,
            "Agora tenho 39 anos.",
        )

        new_fact = self.age_fact(
            owner.id,
            episode2.id,
            39,
            supersedes=(
                old_fact.id,
            ),
        )

        tx = (
            self.store
            .begin_transaction()
        )

        tx.append_episode(
            episode2
        )

        tx.create_fact(
            new_fact
        )

        tx.commit()

        conn = sqlite3.connect(
            str(
                self.path
            )
        )

        try:
            row = conn.execute(
                """
                SELECT
                    initial_status,
                    value_json
                FROM facts
                WHERE id = ?
                """,
                (
                    old_fact.id,
                ),
            ).fetchone()

        finally:
            conn.close()

        self.assertEqual(
            row[0],
            "ACTIVE",
        )

        self.assertEqual(
            row[1],
            "38",
        )

        self.assertEqual(
            self.store
            .get_fact(
                old_fact.id
            ).status,
            MemoryStatus
            .SUPERSEDED,
        )

    def test_fact_state_can_be_reconstructed_as_of_revision(self):
        owner, _, old_fact, _ = self.commit_initial_age(38)
        episode2 = self.episode(owner.id, 'Agora tenho 39 anos.')
        new_fact = self.age_fact(owner.id, episode2.id, 39, supersedes=(old_fact.id,))
        tx = self.store.begin_transaction()
        tx.append_episode(episode2)
        tx.create_fact(new_fact)
        tx.commit()
        at_one = self.store.query_facts_as_of_revision(revision=1, subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        at_two = self.store.query_facts_as_of_revision(revision=2, subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        self.assertEqual(len(at_one), 1)
        self.assertEqual(at_one[0].value.value, 38)
        self.assertEqual(at_one[0].status, MemoryStatus.ACTIVE)
        self.assertEqual(len(at_two), 1)
        self.assertEqual(at_two[0].value.value, 39)
        self.assertEqual(at_two[0].status, MemoryStatus.ACTIVE)

    def test_invalid_future_revision_fails_closed(
        self,
    ):
        self.commit_initial_age()

        with self.assertRaises(
            MemoryIntegrityError
        ):
            (
                self.store
                .query_facts_as_of_revision(
                    revision=2,
                    subject_entity_ids=(
                        "anything",
                    ),
                )
            )

    def test_relation_supersession_supports_current_history_and_revision(self):
        owner = self.owner()
        ana = self.person('Ana')
        episode1 = self.episode(owner.id, 'A minha parceira ? Ana.')
        relation1 = self.relation(owner.id, ana.id, episode1.id)
        tx1 = self.store.begin_transaction()
        tx1.create_entity(owner)
        tx1.create_entity(ana)
        tx1.append_episode(episode1)
        tx1.create_property(self.partner_property())
        tx1.create_relation(relation1)
        tx1.commit()
        bea = self.person('Bea')
        episode2 = self.episode(owner.id, 'A minha parceira agora ? Bea.')
        relation2 = self.relation(owner.id, bea.id, episode2.id, supersedes=(relation1.id,))
        tx2 = self.store.begin_transaction()
        tx2.create_entity(bea)
        tx2.append_episode(episode2)
        tx2.create_relation(relation2)
        receipt2 = tx2.commit()
        self.assertEqual(receipt2.superseded_relation_ids, (relation1.id,))
        current = self.store.query_current_relations(source_entity_ids=(owner.id,), property_ids=(PARTNER_PROPERTY_ID,))
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0].target_entity_id, bea.id)
        history = self.store.query_historical_relations(source_entity_ids=(owner.id,), property_ids=(PARTNER_PROPERTY_ID,))
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].status, MemoryStatus.SUPERSEDED)
        self.assertEqual(history[1].status, MemoryStatus.ACTIVE)
        at_one = self.store.query_relations_as_of_revision(revision=1, source_entity_ids=(owner.id,), property_ids=(PARTNER_PROPERTY_ID,))
        self.assertEqual(len(at_one), 1)
        self.assertEqual(at_one[0].target_entity_id, ana.id)
        self.assertEqual(at_one[0].status, MemoryStatus.ACTIVE)

    def test_current_query_respects_subject_and_property_filters(self):
        owner1 = self.owner('OWNER-1')
        owner2 = self.owner('OWNER-2')
        ep1 = self.episode(owner1.id, 'Tenho 38 anos.')
        ep2 = self.episode(owner2.id, 'Tenho 41 anos.')
        fact1 = self.age_fact(owner1.id, ep1.id, 38)
        fact2 = self.age_fact(owner2.id, ep2.id, 41)
        tx = self.store.begin_transaction()
        tx.create_entity(owner1)
        tx.create_entity(owner2)
        tx.append_episode(ep1)
        tx.append_episode(ep2)
        tx.create_property(self.age_property())
        tx.create_fact(fact1)
        tx.create_fact(fact2)
        tx.commit()
        result = self.store.query_current_facts(subject_entity_ids=(owner1.id,), property_ids=(AGE_PROPERTY_ID,))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].subject_entity_id, owner1.id)
        self.assertEqual(result[0].value.value, 38)
        none = self.store.query_current_facts(subject_entity_ids=(owner1.id,), property_ids=(MISSING_PROPERTY_ID,))
        self.assertEqual(none, ())

    def test_reopen_preserves_current_and_historical_read_semantics(self):
        owner, _, old_fact, _ = self.commit_initial_age(38)
        ep2 = self.episode(owner.id, 'Agora tenho 39 anos.')
        fact2 = self.age_fact(owner.id, ep2.id, 39, supersedes=(old_fact.id,))
        tx = self.store.begin_transaction()
        tx.append_episode(ep2)
        tx.create_fact(fact2)
        tx.commit()
        reopened = CanonicalMemoryStore(self.path)
        current = reopened.query_current_facts(subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        history = reopened.query_historical_facts(subject_entity_ids=(owner.id,), property_ids=(AGE_PROPERTY_ID,))
        self.assertEqual(current[0].value.value, 39)
        self.assertEqual(len(history), 2)
        self.assertEqual(reopened.get_fact(old_fact.id).status, MemoryStatus.SUPERSEDED)
        ok, problems = reopened.integrity_check()
        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
