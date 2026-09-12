from __future__ import annotations

import ast
import dataclasses
import inspect
import sqlite3
import tempfile
import unittest
from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
from unittest import mock

import jarvis_core.memory.write_executor as write_executor

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
    CanonicalMemoryTransaction,
)
from jarvis_core.memory.enums import (
    Cardinality,
    CommitStatus,
    MemoryAuthority,
    MemoryClass,
    MemoryNamespace,
    MemoryStatus,
    PropertyKind,
    SourceType,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryIntegrityError,
    MemoryValidationError,
)
from jarvis_core.memory.ids import (
    new_memory_id,
)
from jarvis_core.memory.interpreter import (
    EntityProposal,
    FactProposal,
    MemoryInterpretation,
    MemoryOperation,
    PropertyProposal,
    RelationProposal,
)
from jarvis_core.memory.models import (
    CanonicalProperty,
    Entity,
    MemoryCommitReceipt,
    MemoryEpisode,
    MemoryFact,
    MemoryRelation,
    MemoryValue,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
)
from jarvis_core.memory.resolution_plan import (
    MemoryResolutionPlan,
    RememberEntityReferenceResolution,
    RememberPropertyResolution,
)
from jarvis_core.memory.write_executor import (
    TrustedWriteExecutionContext,
    execute_memory_resolution_plan,
)


FACT_PROPERTY_ID = (
    "property_"
    "11111111111111111111111111111111"
)

FACT_PROPERTY_ID_2 = (
    "property_"
    "22222222222222222222222222222222"
)

RELATION_PROPERTY_ID = (
    "property_"
    "33333333333333333333333333333333"
)


class Memory1WriteExecutorTests(
    unittest.TestCase
):
    def setUp(self):
        self.tmp = (
            tempfile.TemporaryDirectory()
        )

        self.path = (
            Path(self.tmp.name)
            / "memory.sqlite3"
        )

        self.store = (
            CanonicalMemoryStore(
                self.path
            )
        )

        self.now = datetime(
            2026,
            9,
            10,
            12,
            0,
            tzinfo=timezone.utc,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _context(
        self,
        *,
        actor_entity_id=None,
        speaker_entity_id=None,
        authority=(
            MemoryAuthority
            .OWNER_EXPLICIT
        ),
        source_type=(
            SourceType.OWNER_TURN
        ),
        raw_text=(
            "O utilizador pediu "
            "explicitamente para guardar."
        ),
    ):
        return (
            TrustedWriteExecutionContext(
                raw_text=raw_text,
                source_type=source_type,
                authority=authority,
                occurred_at=self.now,
                recorded_at=self.now,
                actor_entity_id=(
                    actor_entity_id
                ),
                speaker_entity_id=(
                    speaker_entity_id
                ),
                conversation_id="conv-1",
                sequence=7,
            )
        )

    def _resolution(
        self,
        *,
        domain,
        action,
        canonical_id,
        confidence=1.0,
    ):
        return (
            CanonicalIdentityResolution(
                domain=domain,
                action=action,
                confidence=confidence,
                canonical_id=(
                    canonical_id
                ),
            )
        )

    def _new_entity_row(
        self,
        local_ref,
        *,
        canonical_id=None,
        namespace=(
            MemoryNamespace.PERSON
        ),
        confidence=0.95,
    ):
        if canonical_id is None:
            canonical_id = (
                new_memory_id()
            )

        proposal = EntityProposal(
            local_ref=local_ref,
            canonical_name=(
                "Person "
                + local_ref
            ),
            entity_type="person",
            namespace_hint=namespace,
            aliases=(),
        )

        return (
            RememberEntityReferenceResolution(
                local_ref=local_ref,
                proposal=proposal,
                resolution=self._resolution(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    action=(
                        IdentityResolutionAction
                        .NEW
                    ),
                    canonical_id=(
                        canonical_id
                    ),
                    confidence=confidence,
                ),
                trusted_binding=False,
            )
        )

    def _existing_entity_row(
        self,
        local_ref,
        canonical_id,
    ):
        return (
            RememberEntityReferenceResolution(
                local_ref=local_ref,
                proposal=None,
                resolution=self._resolution(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    action=(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    canonical_id=(
                        canonical_id
                    ),
                ),
                trusted_binding=True,
            )
        )

    def _fact_property_proposal(
        self,
        local_ref="age",
        *,
        value_type=(
            ValueType.INTEGER
        ),
    ):
        return PropertyProposal(
            local_ref=local_ref,
            semantic_labels=(
                local_ref,
            ),
            semantic_type="attribute",
            cardinality=(
                Cardinality
                .SINGLE_CURRENT
            ),
            value_type=value_type,
        )

    def _relation_property_proposal(
        self,
        local_ref="partner",
    ):
        return PropertyProposal(
            local_ref=local_ref,
            semantic_labels=(
                local_ref,
            ),
            semantic_type=(
                "relationship"
            ),
            cardinality=(
                Cardinality
                .MULTI_CURRENT
            ),
            value_type=None,
        )

    def _new_fact_property_row(
        self,
        *,
        local_ref="age",
        property_id=(
            FACT_PROPERTY_ID
        ),
        value_type=(
            ValueType.INTEGER
        ),
    ):
        proposal = (
            self
            ._fact_property_proposal(
                local_ref,
                value_type=value_type,
            )
        )

        return RememberPropertyResolution(
            local_ref=local_ref,
            kind=PropertyKind.FACT,
            proposal=proposal,
            resolution=self._resolution(
                domain=(
                    CanonicalIdentityDomain
                    .PROPERTY
                ),
                action=(
                    IdentityResolutionAction
                    .NEW
                ),
                canonical_id=(
                    property_id
                ),
            ),
        )

    def _existing_fact_property_row(
        self,
        property_id,
        *,
        local_ref="age",
        value_type=(
            ValueType.INTEGER
        ),
    ):
        proposal = (
            self
            ._fact_property_proposal(
                local_ref,
                value_type=value_type,
            )
        )

        return RememberPropertyResolution(
            local_ref=local_ref,
            kind=PropertyKind.FACT,
            proposal=proposal,
            resolution=self._resolution(
                domain=(
                    CanonicalIdentityDomain
                    .PROPERTY
                ),
                action=(
                    IdentityResolutionAction
                    .EXISTING
                ),
                canonical_id=(
                    property_id
                ),
            ),
        )

    def _new_relation_property_row(
        self,
        *,
        local_ref="partner",
        property_id=(
            RELATION_PROPERTY_ID
        ),
    ):
        proposal = (
            self
            ._relation_property_proposal(
                local_ref
            )
        )

        return RememberPropertyResolution(
            local_ref=local_ref,
            kind=PropertyKind.RELATION,
            proposal=proposal,
            resolution=self._resolution(
                domain=(
                    CanonicalIdentityDomain
                    .PROPERTY
                ),
                action=(
                    IdentityResolutionAction
                    .NEW
                ),
                canonical_id=(
                    property_id
                ),
            ),
        )

    def _plan(
        self,
        *,
        entity_rows=(),
        fact_property_rows=(),
        relation_property_rows=(),
        facts=(),
        relations=(),
        operation=(
            MemoryOperation.REMEMBER
        ),
        needs_confirmation=False,
        ambiguities=(),
        explicit_memory_request=True,
    ):
        interpretation = (
            MemoryInterpretation(
                operation=operation,
                confidence=1.0,
                explicit_memory_request=(
                    explicit_memory_request
                ),
                entities=tuple(
                    row.proposal
                    for row in entity_rows
                    if (
                        row.proposal
                        is not None
                    )
                ),
                fact_properties=tuple(
                    row.proposal
                    for row
                    in fact_property_rows
                ),
                relation_properties=tuple(
                    row.proposal
                    for row
                    in relation_property_rows
                ),
                facts=tuple(facts),
                relations=tuple(
                    relations
                ),
                query=None,
                needs_confirmation=(
                    needs_confirmation
                ),
                ambiguities=tuple(
                    ambiguities
                ),
            )
        )

        return MemoryResolutionPlan(
            interpretation=(
                interpretation
            ),
            remember_entities=tuple(
                entity_rows
            ),
            remember_fact_properties=tuple(
                fact_property_rows
            ),
            remember_relation_properties=tuple(
                relation_property_rows
            ),
        )

    def _fact(
        self,
        *,
        subject_ref="person",
        property_ref="age",
        value=38,
        value_entity_ref=None,
        valid_from=None,
        valid_until=None,
    ):
        return FactProposal(
            subject_ref=subject_ref,
            property_ref=property_ref,
            value=value,
            memory_class=(
                MemoryClass.FACTUAL
            ),
            confidence=0.97,
            unit=None,
            value_entity_ref=(
                value_entity_ref
            ),
            raw_representation=(
                str(value)
            ),
            valid_from=valid_from,
            valid_until=valid_until,
        )

    def _relation(
        self,
        *,
        source_ref="person_a",
        property_ref="partner",
        target_ref="person_b",
        valid_from=None,
        valid_until=None,
    ):
        return RelationProposal(
            source_ref=source_ref,
            property_ref=property_ref,
            target_ref=target_ref,
            memory_class=(
                MemoryClass.RELATIONAL
            ),
            confidence=0.96,
            valid_from=valid_from,
            valid_until=valid_until,
        )

    def _count(
        self,
        table,
    ):
        conn = sqlite3.connect(
            str(self.path)
        )

        try:
            return int(
                conn.execute(
                    f'SELECT COUNT(*) '
                    f'FROM "{table}"'
                ).fetchone()[0]
            )

        finally:
            conn.close()

    def _row(
        self,
        table,
    ):
        conn = sqlite3.connect(
            str(self.path)
        )

        conn.row_factory = (
            sqlite3.Row
        )

        try:
            row = conn.execute(
                f'SELECT * '
                f'FROM "{table}" '
                f'ORDER BY rowid DESC '
                f'LIMIT 1'
            ).fetchone()

            if row is None:
                return None

            return dict(row)

        finally:
            conn.close()

    def _state(
        self,
    ):
        return {
            "revision":
                self.store
                .canonical_revision(),

            "transactions":
                self._count(
                    "transactions"
                ),

            "audit":
                self._count(
                    "audit_events"
                ),

            "properties":
                self._count(
                    "properties"
                ),

            "entities":
                self._count(
                    "entities"
                ),

            "episodes":
                self._count(
                    "episodes"
                ),

            "facts":
                self._count(
                    "facts"
                ),

            "relations":
                self._count(
                    "relations"
                ),
        }

    def _seed_entity_and_fact_property(
        self,
    ):
        entity = Entity(
            id=new_memory_id(),
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name="OWNER",
            entity_type="person",
            aliases=(),
            status=(
                MemoryStatus.ACTIVE
            ),
            created_at=self.now,
            updated_at=self.now,
            source_episode_ids=(),
            confidence=1.0,
            metadata={},
        )

        property = CanonicalProperty(
            id=FACT_PROPERTY_ID_2,
            kind=PropertyKind.FACT,
            semantic_labels=(
                "age",
            ),
            semantic_type="attribute",
            cardinality=(
                Cardinality
                .SINGLE_CURRENT
            ),
            value_type=(
                ValueType.INTEGER
            ),
            status=(
                MemoryStatus.ACTIVE
            ),
            created_at=self.now,
        )

        with (
            self.store
            .begin_transaction()
        ) as tx:
            tx.create_property(
                property
            )

            tx.create_entity(
                entity
            )

            receipt = tx.commit()

        self.assertIs(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        return (
            entity,
            property,
        )

    def test_trusted_context_is_frozen_and_validates_trusted_fields(
        self,
    ):
        context = self._context()

        self.assertTrue(
            dataclasses.is_dataclass(
                TrustedWriteExecutionContext
            )
        )

        self.assertTrue(
            TrustedWriteExecutionContext
            .__dataclass_params__
            .frozen
        )

        self.assertTrue(
            hasattr(
                TrustedWriteExecutionContext,
                "__slots__",
            )
        )

        with self.assertRaises(
            dataclasses.FrozenInstanceError
        ):
            context.raw_text = "changed"

        invalid_cases = (
            {
                "raw_text": "   ",
            },
            {
                "source_type": "OWNER_TURN",
            },
            {
                "authority": "OWNER_EXPLICIT",
            },
            {
                "occurred_at":
                    datetime(
                        2026,
                        9,
                        10,
                        12,
                        0,
                    ),
            },
            {
                "recorded_at":
                    datetime(
                        2026,
                        9,
                        10,
                        12,
                        0,
                    ),
            },
            {
                "actor_entity_id": "",
            },
            {
                "speaker_entity_id": "",
            },
            {
                "conversation_id": "",
            },
            {
                "sequence": True,
            },
        )

        base = {
            "raw_text": "remember",
            "source_type":
                SourceType.OWNER_TURN,
            "authority":
                MemoryAuthority
                .OWNER_EXPLICIT,
            "occurred_at":
                self.now,
            "recorded_at":
                self.now,
            "actor_entity_id":
                None,
            "speaker_entity_id":
                None,
            "conversation_id":
                None,
            "sequence":
                None,
        }

        for override in (
            invalid_cases
        ):
            values = dict(base)
            values.update(
                override
            )

            with self.subTest(
                override=override
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    TrustedWriteExecutionContext(
                        **values
                    )

    def test_new_entity_property_and_fact_commit_atomically(
        self,
    ):
        entity_row = (
            self._new_entity_row(
                "person"
            )
        )

        property_row = (
            self._new_fact_property_row()
        )

        plan = self._plan(
            entity_rows=(
                entity_row,
            ),
            fact_property_rows=(
                property_row,
            ),
            facts=(
                self._fact(),
            ),
        )

        receipt = (
            execute_memory_resolution_plan(
                plan,
                store=self.store,
                context=self._context(),
            )
        )

        self.assertIsInstance(
            receipt,
            MemoryCommitReceipt,
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
            len(
                receipt.episode_ids
            ),
            1,
        )

        self.assertEqual(
            len(
                receipt.fact_ids
            ),
            1,
        )

        self.assertEqual(
            receipt.relation_ids,
            (),
        )

        entity_id = (
            entity_row
            .resolution
            .canonical_id
        )

        self.assertIsNotNone(
            entity_id
        )

        stored_entity = (
            self.store.get_entity(
                entity_id
            )
        )

        self.assertIsNotNone(
            stored_entity
        )

        self.assertEqual(
            stored_entity
            .source_episode_ids,
            receipt.episode_ids,
        )

        stored_property = (
            self.store.get_property(
                FACT_PROPERTY_ID
            )
        )

        self.assertIsNotNone(
            stored_property
        )

        self.assertIs(
            stored_property.kind,
            PropertyKind.FACT,
        )

        self.assertIs(
            stored_property.value_type,
            ValueType.INTEGER,
        )

        facts = (
            self.store
            .query_current_facts(
                subject_entity_ids=(
                    entity_id,
                ),
                property_ids=(
                    FACT_PROPERTY_ID,
                ),
            )
        )

        self.assertEqual(
            len(facts),
            1,
        )

        fact = facts[0]

        self.assertEqual(
            fact.value.value,
            38,
        )

        self.assertIs(
            fact.authority,
            MemoryAuthority
            .OWNER_EXPLICIT,
        )

        self.assertEqual(
            fact.source_episode_ids,
            receipt.episode_ids,
        )

        self.assertEqual(
            fact.canonical_key,
            (
                f"{entity_id}"
                f"|{FACT_PROPERTY_ID}"
            ),
        )

    def test_new_relation_commits_with_resolved_canonical_identity(
        self,
    ):
        first = (
            self._new_entity_row(
                "person_a"
            )
        )

        second = (
            self._new_entity_row(
                "person_b"
            )
        )

        relation_property = (
            self
            ._new_relation_property_row()
        )

        plan = self._plan(
            entity_rows=(
                first,
                second,
            ),
            relation_property_rows=(
                relation_property,
            ),
            relations=(
                self._relation(),
            ),
        )

        receipt = (
            execute_memory_resolution_plan(
                plan,
                store=self.store,
                context=self._context(),
            )
        )

        self.assertIs(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            len(
                receipt.relation_ids
            ),
            1,
        )

        source_id = (
            first.resolution
            .canonical_id
        )

        target_id = (
            second.resolution
            .canonical_id
        )

        relations = (
            self.store
            .query_current_relations(
                source_entity_ids=(
                    source_id,
                ),
                property_ids=(
                    RELATION_PROPERTY_ID,
                ),
            )
        )

        self.assertEqual(
            len(relations),
            1,
        )

        relation = relations[0]

        self.assertEqual(
            relation.target_entity_id,
            target_id,
        )

        self.assertEqual(
            relation.canonical_key,
            (
                f"{source_id}"
                f"|{RELATION_PROPERTY_ID}"
            ),
        )

        self.assertEqual(
            relation.source_episode_ids,
            receipt.episode_ids,
        )

    def test_existing_identity_is_reused_and_trusted_context_reaches_canonical_rows(
        self,
    ):
        (
            owner,
            property,
        ) = (
            self
            ._seed_entity_and_fact_property()
        )

        plan = self._plan(
            entity_rows=(
                self._existing_entity_row(
                    "owner",
                    owner.id,
                ),
            ),
            fact_property_rows=(
                self
                ._existing_fact_property_row(
                    property.id
                ),
            ),
            facts=(
                self._fact(
                    subject_ref="owner",
                ),
            ),
        )

        receipt = (
            execute_memory_resolution_plan(
                plan,
                store=self.store,
                context=self._context(
                    actor_entity_id=(
                        owner.id
                    ),
                    speaker_entity_id=(
                        owner.id
                    ),
                    authority=(
                        MemoryAuthority
                        .OWNER_CONFIRMED
                    ),
                    raw_text=(
                        "Tenho 38 anos."
                    ),
                ),
            )
        )

        self.assertIs(
            receipt.status,
            CommitStatus.COMMITTED,
        )

        self.assertEqual(
            receipt.canonical_revision,
            2,
        )

        self.assertEqual(
            self._count(
                "entities"
            ),
            1,
        )

        self.assertEqual(
            self._count(
                "properties"
            ),
            1,
        )

        episode_row = (
            self._row(
                "episodes"
            )
        )

        self.assertEqual(
            episode_row[
                "speaker_entity_id"
            ],
            owner.id,
        )

        self.assertEqual(
            episode_row[
                "source_type"
            ],
            SourceType
            .OWNER_TURN
            .value,
        )

        self.assertEqual(
            episode_row[
                "raw_text"
            ],
            "Tenho 38 anos.",
        )

        facts = (
            self.store
            .query_current_facts(
                subject_entity_ids=(
                    owner.id,
                ),
                property_ids=(
                    property.id,
                ),
            )
        )

        self.assertEqual(
            len(facts),
            1,
        )

        self.assertIs(
            facts[0].authority,
            MemoryAuthority
            .OWNER_CONFIRMED,
        )

        conn = sqlite3.connect(
            str(self.path)
        )

        try:
            actor_audit_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM audit_events
                    WHERE actor_entity_id = ?
                    """,
                    (
                        owner.id,
                    ),
                ).fetchone()[0]
            )

        finally:
            conn.close()

        self.assertGreater(
            actor_audit_count,
            0,
        )

    def test_temporal_strings_are_mechanically_parsed_to_aware_datetimes(
        self,
    ):
        entity_row = (
            self._new_entity_row(
                "person"
            )
        )

        property_row = (
            self._new_fact_property_row()
        )

        plan = self._plan(
            entity_rows=(
                entity_row,
            ),
            fact_property_rows=(
                property_row,
            ),
            facts=(
                self._fact(
                    valid_from=(
                        "2026-09-10"
                        "T09:00:00+00:00"
                    ),
                    valid_until=(
                        "2027-09-10"
                        "T09:00:00+00:00"
                    ),
                ),
            ),
        )

        execute_memory_resolution_plan(
            plan,
            store=self.store,
            context=self._context(),
        )

        entity_id = (
            entity_row
            .resolution
            .canonical_id
        )

        fact = (
            self.store
            .query_current_facts(
                subject_entity_ids=(
                    entity_id,
                ),
                property_ids=(
                    FACT_PROPERTY_ID,
                ),
            )[0]
        )

        self.assertIsNotNone(
            fact.valid_from
        )

        self.assertIsNotNone(
            fact.valid_until
        )

        self.assertIsNotNone(
            fact.valid_from
            .utcoffset()
        )

        self.assertIsNotNone(
            fact.valid_until
            .utcoffset()
        )

        bad_plan = self._plan(
            entity_rows=(
                self._new_entity_row(
                    "other"
                ),
            ),
            fact_property_rows=(
                self._new_fact_property_row(
                    property_id=(
                        FACT_PROPERTY_ID_2
                    )
                ),
            ),
            facts=(
                self._fact(
                    subject_ref="other",
                    valid_from=(
                        "2026-09-10"
                    ),
                ),
            ),
        )

        before = self._state()

        with self.assertRaises(
            MemoryValidationError
        ):
            execute_memory_resolution_plan(
                bad_plan,
                store=self.store,
                context=self._context(),
            )

        self.assertEqual(
            self._state(),
            before,
        )

    def test_non_remember_confirmation_and_ambiguities_fail_before_transaction(
        self,
    ):
        from jarvis_core.memory.interpreter import (
            MemoryQueryProposal,
        )

        none_plan = self._plan(
            operation=(
                MemoryOperation.NONE
            ),
            explicit_memory_request=False,
        )

        recall_plan = MemoryResolutionPlan(
            interpretation=(
                MemoryInterpretation(
                    operation=(
                        MemoryOperation.RECALL
                    ),
                    confidence=1.0,
                    explicit_memory_request=False,
                    entities=(),
                    fact_properties=(),
                    relation_properties=(),
                    facts=(),
                    relations=(),
                    query=MemoryQueryProposal(
                        subject_refs=(
                            "owner",
                        ),
                    ),
                    needs_confirmation=False,
                    ambiguities=(),
                )
            )
        )

        remember_row = (
            self._new_entity_row(
                "guarded_person"
            )
        )

        confirmation_plan = self._plan(
            entity_rows=(
                remember_row,
            ),
            needs_confirmation=True,
        )

        ambiguity_plan = self._plan(
            entity_rows=(
                remember_row,
            ),
            ambiguities=(
                "unresolved",
            ),
        )

        cases = (
            none_plan,
            recall_plan,
            confirmation_plan,
            ambiguity_plan,
        )

        for plan in cases:
            with self.subTest(
                operation=(
                    plan.interpretation
                    .operation
                ),
                confirmation=(
                    plan.interpretation
                    .needs_confirmation
                ),
                ambiguities=(
                    plan.interpretation
                    .ambiguities
                ),
            ):
                before = (
                    self._state()
                )

                with self.assertRaises(
                    MemoryValidationError
                ):
                    execute_memory_resolution_plan(
                        plan,
                        store=self.store,
                        context=(
                            self._context()
                        ),
                    )

                self.assertEqual(
                    self._state(),
                    before,
                )

    def test_ambiguous_identity_and_new_entity_without_namespace_fail_before_transaction(
        self,
    ):
        proposal = EntityProposal(
            local_ref="person",
            canonical_name="Person",
            entity_type="person",
            namespace_hint=(
                MemoryNamespace.PERSON
            ),
            aliases=(),
        )

        ambiguous_row = (
            RememberEntityReferenceResolution(
                local_ref="person",
                proposal=proposal,
                resolution=self._resolution(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    action=(
                        IdentityResolutionAction
                        .AMBIGUOUS
                    ),
                    canonical_id=None,
                    confidence=0.5,
                ),
                trusted_binding=False,
            )
        )

        no_namespace = (
            self._new_entity_row(
                "person",
                namespace=None,
            )
        )

        for row in (
            ambiguous_row,
            no_namespace,
        ):
            plan = self._plan(
                entity_rows=(
                    row,
                ),
            )

            before = (
                self._state()
            )

            with self.assertRaises(
                MemoryValidationError
            ):
                execute_memory_resolution_plan(
                    plan,
                    store=self.store,
                    context=self._context(),
                )

            self.assertEqual(
                self._state(),
                before,
            )

    def test_missing_and_colliding_canonical_identities_fail_before_transaction(
        self,
    ):
        missing_entity = (
            self._existing_entity_row(
                "owner",
                new_memory_id(),
            )
        )

        supporting_property = (
            self._new_fact_property_row(
                property_id=(
                    FACT_PROPERTY_ID
                )
            )
        )

        missing_entity_plan = self._plan(
            entity_rows=(
                missing_entity,
            ),
            fact_property_rows=(
                supporting_property,
            ),
            facts=(
                self._fact(
                    subject_ref="owner",
                    property_ref="age",
                ),
            ),
        )

        missing_property = (
            self
            ._existing_fact_property_row(
                FACT_PROPERTY_ID
            )
        )

        missing_property_subject = (
            self._new_entity_row(
                "missing_property_subject"
            )
        )

        missing_property_plan = self._plan(
            entity_rows=(
                missing_property_subject,
            ),
            fact_property_rows=(
                missing_property,
            ),
            facts=(
                self._fact(
                    subject_ref=(
                        "missing_property_subject"
                    ),
                    property_ref="age",
                ),
            ),
        )

        for plan in (
            missing_entity_plan,
            missing_property_plan,
        ):
            before = (
                self._state()
            )

            with self.assertRaises(
                MemoryValidationError
            ):
                execute_memory_resolution_plan(
                    plan,
                    store=self.store,
                    context=self._context(),
                )

            self.assertEqual(
                self._state(),
                before,
            )

        (
            existing_entity,
            existing_property,
        ) = (
            self
            ._seed_entity_and_fact_property()
        )

        collision_entity = (
            self._new_entity_row(
                "collision",
                canonical_id=(
                    existing_entity.id
                ),
            )
        )

        collision_entity_plan = (
            self._plan(
                entity_rows=(
                    collision_entity,
                ),
            )
        )

        collision_property = (
            self._new_fact_property_row(
                property_id=(
                    existing_property.id
                )
            )
        )

        existing_subject = (
            self._existing_entity_row(
                "owner",
                existing_entity.id,
            )
        )

        collision_property_plan = (
            self._plan(
                entity_rows=(
                    existing_subject,
                ),
                fact_property_rows=(
                    collision_property,
                ),
                facts=(
                    self._fact(
                        subject_ref="owner",
                        property_ref="age",
                    ),
                ),
            )
        )

        for plan in (
            collision_entity_plan,
            collision_property_plan,
        ):
            before = (
                self._state()
            )

            with self.assertRaises(
                MemoryValidationError
            ):
                execute_memory_resolution_plan(
                    plan,
                    store=self.store,
                    context=self._context(),
                )

            self.assertEqual(
                self._state(),
                before,
            )

    def test_actor_and_speaker_must_preexist_before_transaction(
        self,
    ):
        missing = new_memory_id()

        contexts = (
            self._context(
                actor_entity_id=(
                    missing
                )
            ),
            self._context(
                speaker_entity_id=(
                    missing
                )
            ),
        )

        valid_remember_row = (
            self._new_entity_row(
                "context_guard_person"
            )
        )

        plan = self._plan(
            entity_rows=(
                valid_remember_row,
            ),
        )

        for context in contexts:
            before = (
                self._state()
            )

            with self.assertRaises(
                MemoryValidationError
            ):
                execute_memory_resolution_plan(
                    plan,
                    store=self.store,
                    context=context,
                )

            self.assertEqual(
                self._state(),
                before,
            )

    def test_unresolved_assertion_references_fail_before_transaction(
        self,
    ):
        property_row = (
            self._new_fact_property_row()
        )

        plan = self._plan(
            fact_property_rows=(
                property_row,
            ),
            facts=(
                self._fact(
                    subject_ref=(
                        "missing"
                    ),
                ),
            ),
        )

        before = self._state()

        with self.assertRaises(
            MemoryValidationError
        ):
            execute_memory_resolution_plan(
                plan,
                store=self.store,
                context=self._context(),
            )

        self.assertEqual(
            self._state(),
            before,
        )

    def test_transaction_failure_rolls_back_episode_entities_properties_and_revision(
        self,
    ):
        entity_row = (
            self._new_entity_row(
                "person"
            )
        )

        property_row = (
            self._new_fact_property_row()
        )

        plan = self._plan(
            entity_rows=(
                entity_row,
            ),
            fact_property_rows=(
                property_row,
            ),
            facts=(
                self._fact(),
            ),
        )

        before = self._state()

        with mock.patch.object(
            CanonicalMemoryTransaction,
            "create_fact",
            side_effect=RuntimeError(
                "forced failure"
            ),
        ):
            with self.assertRaises(
                RuntimeError
            ):
                execute_memory_resolution_plan(
                    plan,
                    store=self.store,
                    context=self._context(),
                )

        self.assertEqual(
            self._state(),
            before,
        )

        self.assertEqual(
            self.store
            .canonical_revision(),
            0,
        )

    def test_executor_module_has_single_transaction_and_no_semantic_or_sql_owner(
        self,
    ):
        source = inspect.getsource(
            write_executor
        )

        tree = ast.parse(
            source
        )

        execute_nodes = [
            node
            for node in tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == (
                    "execute_memory_"
                    "resolution_plan"
                )
            )
        ]

        self.assertEqual(
            len(execute_nodes),
            1,
        )

        execute_node = (
            execute_nodes[0]
        )

        calls = []

        for node in ast.walk(
            execute_node
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
                calls.append(
                    node.func.id
                )

            elif isinstance(
                node.func,
                ast.Attribute,
            ):
                calls.append(
                    node.func.attr
                )

        self.assertEqual(
            calls.count(
                "begin_transaction"
            ),
            1,
        )

        self.assertEqual(
            calls.count(
                "commit"
            ),
            1,
        )

        for forbidden_call in (
            "execute",
            "executemany",
            "cursor",
            "casefold",
            "lower",
            "upper",
        ):
            self.assertNotIn(
                forbidden_call,
                calls,
            )

        imports = set()

        for node in tree.body:
            if isinstance(
                node,
                ast.ImportFrom,
            ):
                imports.add(
                    node.module or ""
                )

            elif isinstance(
                node,
                ast.Import,
            ):
                imports.update(
                    alias.name
                    for alias
                    in node.names
                )

        for forbidden_import in (
            "sqlite3",
            "re",
            "jarvis_core.core.local_llm",
            "jarvis_core.services.memory_grounding",
            "jarvis_core.services.memory_index",
        ):
            self.assertNotIn(
                forbidden_import,
                imports,
            )

        identifiers = {
            node.id
            for node in ast.walk(
                tree
            )
            if isinstance(
                node,
                ast.Name,
            )
        }

        for forbidden_owner in (
            "SemanticIdentityMatcher",
            "SemanticMemoryModel",
        ):
            self.assertNotIn(
                forbidden_owner,
                identifiers,
            )

        self.assertNotIn(
            "MemoryCommitReceipt(",
            source,
        )

        self.assertNotIn(
            "new_property_id",
            source,
        )

        self.assertNotIn(
            "predicate=",
            source,
        )

        self.assertIn(
            "property_id=",
            source,
        )


    def test_identical_fact_reaffirmation_is_zero_mutation_idempotent(
        self,
    ):
        entity, property = (
            self._seed_entity_and_fact_property()
        )

        row = self._existing_entity_row(
            "person",
            entity.id,
        )
        property_row = (
            self._existing_fact_property_row(
                property.id,
            )
        )

        first = execute_memory_resolution_plan(
            self._plan(
                entity_rows=(row,),
                fact_property_rows=(
                    property_row,
                ),
                facts=(
                    self._fact(
                        subject_ref="person",
                        value=38,
                    ),
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=entity.id,
                speaker_entity_id=entity.id,
            ),
        )

        self.assertIs(
            first.status,
            CommitStatus.COMMITTED,
        )

        existing_fact_id = first.fact_ids[0]
        state_before = self._state()
        bytes_before = self.path.read_bytes()

        reaffirmation = FactProposal(
            subject_ref="person",
            property_ref="age",
            value=38,
            memory_class=MemoryClass.FACTUAL,
            confidence=0.21,
            unit=None,
            value_entity_ref=None,
            raw_representation="trinta e oito",
            valid_from=None,
            valid_until=None,
        )

        receipt = execute_memory_resolution_plan(
            self._plan(
                entity_rows=(row,),
                fact_property_rows=(
                    property_row,
                ),
                facts=(
                    reaffirmation,
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=entity.id,
                speaker_entity_id=entity.id,
                authority=(
                    MemoryAuthority
                    .OWNER_CONFIRMED
                ),
                raw_text=(
                    "Tenho 38 anos."
                ),
            ),
        )

        self.assertIs(
            receipt.status,
            CommitStatus.NO_CHANGE,
        )
        self.assertEqual(
            receipt.message_code,
            "MEMORY_NO_CHANGE_IDEMPOTENT",
        )
        self.assertEqual(
            receipt.fact_ids,
            (existing_fact_id,),
        )
        self.assertEqual(
            receipt.episode_ids,
            (),
        )
        self.assertEqual(
            receipt.superseded_fact_ids,
            (),
        )
        self.assertEqual(
            self._state(),
            state_before,
        )
        self.assertEqual(
            self.path.read_bytes(),
            bytes_before,
        )

        current = self.store.query_current_facts(
            subject_entity_ids=(entity.id,),
            property_ids=(property.id,),
        )
        self.assertEqual(
            len(current),
            1,
        )
        self.assertIs(
            current[0].authority,
            MemoryAuthority.OWNER_EXPLICIT,
        )
        self.assertEqual(
            current[0].confidence,
            0.97,
        )

    def test_different_single_current_fact_supersedes_previous(
        self,
    ):
        entity, property = (
            self._seed_entity_and_fact_property()
        )
        row = self._existing_entity_row(
            "person",
            entity.id,
        )
        property_row = (
            self._existing_fact_property_row(
                property.id,
            )
        )

        first = execute_memory_resolution_plan(
            self._plan(
                entity_rows=(row,),
                fact_property_rows=(property_row,),
                facts=(
                    self._fact(
                        subject_ref="person",
                        value=38,
                    ),
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=entity.id,
                speaker_entity_id=entity.id,
            ),
        )

        old_id = first.fact_ids[0]
        revision_before = (
            self.store.canonical_revision()
        )

        second = execute_memory_resolution_plan(
            self._plan(
                entity_rows=(row,),
                fact_property_rows=(property_row,),
                facts=(
                    self._fact(
                        subject_ref="person",
                        value=39,
                    ),
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=entity.id,
                speaker_entity_id=entity.id,
                raw_text="Agora tenho 39 anos.",
            ),
        )

        self.assertIs(
            second.status,
            CommitStatus.COMMITTED,
        )
        self.assertEqual(
            second.superseded_fact_ids,
            (old_id,),
        )
        self.assertEqual(
            second.canonical_revision,
            revision_before + 1,
        )

        current = self.store.query_current_facts(
            subject_entity_ids=(entity.id,),
            property_ids=(property.id,),
        )
        history = self.store.query_historical_facts(
            subject_entity_ids=(entity.id,),
            property_ids=(property.id,),
        )

        self.assertEqual(len(current), 1)
        self.assertEqual(
            current[0].value.value,
            39,
        )
        self.assertEqual(len(history), 2)

    def test_single_current_relation_supersedes_previous_target(
        self,
    ):
        people = []
        for name in ("A", "B", "C"):
            people.append(
                Entity(
                    id=new_memory_id(),
                    namespace=MemoryNamespace.PERSON,
                    canonical_name=name,
                    entity_type="person",
                    created_at=self.now,
                    updated_at=self.now,
                )
            )

        property = CanonicalProperty(
            id=RELATION_PROPERTY_ID,
            kind=PropertyKind.RELATION,
            semantic_labels=("partner",),
            semantic_type="relationship",
            cardinality=Cardinality.SINGLE_CURRENT,
            value_type=None,
            created_at=self.now,
        )

        with self.store.begin_transaction() as tx:
            tx.create_property(property)
            for entity in people:
                tx.create_entity(entity)
            tx.commit()

        relation_property_proposal = PropertyProposal(
            local_ref="partner",
            semantic_labels=("partner",),
            semantic_type="relationship",
            cardinality=Cardinality.SINGLE_CURRENT,
            value_type=None,
        )
        relation_property_row = RememberPropertyResolution(
            local_ref="partner",
            kind=PropertyKind.RELATION,
            proposal=relation_property_proposal,
            resolution=self._resolution(
                domain=CanonicalIdentityDomain.PROPERTY,
                action=IdentityResolutionAction.EXISTING,
                canonical_id=property.id,
            ),
        )

        rows = tuple(
            self._existing_entity_row(ref, entity.id)
            for ref, entity in zip(
                ("a", "b", "c"),
                people,
            )
        )

        first = execute_memory_resolution_plan(
            self._plan(
                entity_rows=rows,
                relation_property_rows=(
                    relation_property_row,
                ),
                relations=(
                    self._relation(
                        source_ref="a",
                        target_ref="b",
                    ),
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=people[0].id,
                speaker_entity_id=people[0].id,
            ),
        )

        old_id = first.relation_ids[0]

        second = execute_memory_resolution_plan(
            self._plan(
                entity_rows=rows,
                relation_property_rows=(
                    relation_property_row,
                ),
                relations=(
                    self._relation(
                        source_ref="a",
                        target_ref="c",
                    ),
                ),
            ),
            store=self.store,
            context=self._context(
                actor_entity_id=people[0].id,
                speaker_entity_id=people[0].id,
                raw_text="C é agora a relação atual.",
            ),
        )

        self.assertEqual(
            second.superseded_relation_ids,
            (old_id,),
        )

        current = self.store.query_current_relations(
            source_entity_ids=(people[0].id,),
            property_ids=(property.id,),
        )
        history = self.store.query_historical_relations(
            source_entity_ids=(people[0].id,),
            property_ids=(property.id,),
        )

        self.assertEqual(len(current), 1)
        self.assertEqual(
            current[0].target_entity_id,
            people[2].id,
        )
        self.assertEqual(len(history), 2)

    def test_single_current_duplicate_store_rows_fail_before_transaction(
        self,
    ):
        entity, property = (
            self._seed_entity_and_fact_property()
        )

        episode = MemoryEpisode(
            id=new_memory_id(),
            occurred_at=self.now,
            recorded_at=self.now,
            source_type=SourceType.OWNER_TURN,
            raw_text="seed duplicate current rows",
            content_hash="0" * 64,
            speaker_entity_id=entity.id,
            explicit_memory_request=True,
        )

        with self.store.begin_transaction(
            actor_entity_id=entity.id,
        ) as tx:
            tx.append_episode(episode)
            for value in (38, 39):
                tx.create_fact(
                    MemoryFact(
                        id=new_memory_id(),
                        subject_entity_id=entity.id,
                        property_id=property.id,
                        value=MemoryValue(
                            value_type=ValueType.INTEGER,
                            value=value,
                        ),
                        memory_class=MemoryClass.FACTUAL,
                        authority=MemoryAuthority.OWNER_EXPLICIT,
                        confidence=1.0,
                        status=MemoryStatus.ACTIVE,
                        recorded_at=self.now,
                        canonical_key=(
                            f"{entity.id}|{property.id}"
                        ),
                        source_episode_ids=(episode.id,),
                    )
                )
            tx.commit()

        state_before = self._state()
        bytes_before = self.path.read_bytes()

        with self.assertRaises(MemoryIntegrityError):
            execute_memory_resolution_plan(
                self._plan(
                    entity_rows=(
                        self._existing_entity_row(
                            "person",
                            entity.id,
                        ),
                    ),
                    fact_property_rows=(
                        self._existing_fact_property_row(
                            property.id,
                        ),
                    ),
                    facts=(
                        self._fact(
                            subject_ref="person",
                            value=40,
                        ),
                    ),
                ),
                store=self.store,
                context=self._context(
                    actor_entity_id=entity.id,
                    speaker_entity_id=entity.id,
                ),
            )

        self.assertEqual(self._state(), state_before)
        self.assertEqual(self.path.read_bytes(), bytes_before)


if __name__ == "__main__":
    unittest.main()
