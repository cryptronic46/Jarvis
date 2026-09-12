from __future__ import annotations

import inspect
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from jarvis_core.memory.entity_resolution import (
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from jarvis_core.memory.enums import PropertyKind
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    EntityQueryProposal,
    MemoryInterpretation,
    MemoryOperation,
    MemoryQueryProposal,
    PropertyQueryProposal,
    QueryTemporalMode,
)
from jarvis_core.memory.property_resolution import (
    RecallPropertyResolution,
    RecallPropertyResolutionAction,
)
from jarvis_core.memory.recall_executor import (
    MemoryRecallReadResult,
    RecallAggregateOutcome,
    RecallItemOutcome,
    execute_memory_recall_plan,
)
from jarvis_core.memory.resolution_plan import (
    MemoryResolutionPlan,
    RecallEntityReferenceResolution,
    RecallPropertyQueryResolution,
)


class FakeCanonicalReadStore:
    def __init__(
        self,
        *,
        facts=(),
        relations=(),
    ):
        self.facts = tuple(facts)
        self.relations = tuple(relations)
        self.calls = []

    def assert_readable(self):
        return None

    def query_current_facts(
        self,
        *,
        subject_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_current_facts",
                subject_entity_ids,
                property_ids,
            )
        )
        return self.facts

    def query_historical_facts(
        self,
        *,
        subject_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_historical_facts",
                subject_entity_ids,
                property_ids,
            )
        )
        return self.facts

    def query_facts_as_of_revision(
        self,
        *,
        revision,
        subject_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_facts_as_of_revision",
                revision,
                subject_entity_ids,
                property_ids,
            )
        )
        return self.facts

    def query_current_relations(
        self,
        *,
        source_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_current_relations",
                source_entity_ids,
                property_ids,
            )
        )
        return self.relations

    def query_historical_relations(
        self,
        *,
        source_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_historical_relations",
                source_entity_ids,
                property_ids,
            )
        )
        return self.relations

    def query_relations_as_of_revision(
        self,
        *,
        revision,
        source_entity_ids,
        property_ids=None,
    ):
        self.calls.append(
            (
                "query_relations_as_of_revision",
                revision,
                source_entity_ids,
                property_ids,
            )
        )
        return self.relations


def entity_resolution(
    *,
    local_ref,
    action=RecallEntityResolutionAction.EXISTING,
    canonical_id=None,
    query=None,
    trusted_binding=False,
):
    if (
        action
        is RecallEntityResolutionAction.EXISTING
        and canonical_id is None
    ):
        canonical_id = (
            "entity-" + local_ref
        )

    if (
        action
        is not RecallEntityResolutionAction.EXISTING
    ):
        canonical_id = None

    return RecallEntityReferenceResolution(
        local_ref=local_ref,
        query=query,
        resolution=RecallEntityResolution(
            action=action,
            confidence=1.0,
            canonical_id=canonical_id,
        ),
        trusted_binding=trusted_binding,
    )


def property_resolution(
    query,
    *,
    kind,
    action=RecallPropertyResolutionAction.EXISTING,
    canonical_id=None,
):
    if (
        action
        is RecallPropertyResolutionAction.EXISTING
        and canonical_id is None
    ):
        canonical_id = (
            "property-"
            + kind.value.lower()
        )

    if (
        action
        is not RecallPropertyResolutionAction.EXISTING
    ):
        canonical_id = None

    return RecallPropertyQueryResolution(
        kind=kind,
        query=query,
        resolution=RecallPropertyResolution(
            kind=kind,
            action=action,
            confidence=1.0,
            canonical_id=canonical_id,
        ),
    )


def fact_plan(
    *,
    action=RecallPropertyResolutionAction.EXISTING,
    temporal_mode=QueryTemporalMode.CURRENT,
    as_of_revision=None,
):
    prop = PropertyQueryProposal(
        semantic_labels=(
            "preferred_language",
        ),
        semantic_type="property",
    )

    query = MemoryQueryProposal(
        subject_refs=(
            "owner",
        ),
        fact_properties=(
            prop,
        ),
        temporal_mode=temporal_mode,
        as_of_revision=as_of_revision,
    )

    interpretation = MemoryInterpretation(
        operation=MemoryOperation.RECALL,
        confidence=1.0,
        explicit_memory_request=False,
        query=query,
    )

    return MemoryResolutionPlan(
        interpretation=interpretation,
        recall_entities=(
            entity_resolution(
                local_ref="owner",
                canonical_id="owner-id",
                trusted_binding=True,
            ),
        ),
        recall_fact_properties=(
            property_resolution(
                prop,
                kind=PropertyKind.FACT,
                action=action,
                canonical_id=(
                    "property-language"
                    if action
                    is RecallPropertyResolutionAction.EXISTING
                    else None
                ),
            ),
        ),
    )


def relation_plan(
    *,
    property_action=(
        RecallPropertyResolutionAction.EXISTING
    ),
    target_action=(
        RecallEntityResolutionAction.EXISTING
    ),
    temporal_mode=QueryTemporalMode.HISTORICAL,
):
    prop = PropertyQueryProposal(
        semantic_labels=(
            "relationship",
        ),
        semantic_type="relationship",
    )

    target_query = EntityQueryProposal(
        local_ref="target",
        semantic_labels=(
            "target person",
        ),
        semantic_type="person",
    )

    query = MemoryQueryProposal(
        subject_refs=(
            "owner",
        ),
        entity_queries=(
            target_query,
        ),
        relation_properties=(
            prop,
        ),
        target_refs=(
            "target",
        ),
        temporal_mode=temporal_mode,
    )

    interpretation = MemoryInterpretation(
        operation=MemoryOperation.RECALL,
        confidence=1.0,
        explicit_memory_request=False,
        query=query,
    )

    return MemoryResolutionPlan(
        interpretation=interpretation,
        recall_entities=(
            entity_resolution(
                local_ref="owner",
                canonical_id="owner-id",
                trusted_binding=True,
            ),
            entity_resolution(
                local_ref="target",
                action=target_action,
                canonical_id=(
                    "target-id"
                    if target_action
                    is RecallEntityResolutionAction.EXISTING
                    else None
                ),
                query=target_query,
                trusted_binding=False,
            ),
        ),
        recall_relation_properties=(
            property_resolution(
                prop,
                kind=PropertyKind.RELATION,
                action=property_action,
                canonical_id=(
                    "property-relationship"
                    if property_action
                    is RecallPropertyResolutionAction.EXISTING
                    else None
                ),
            ),
        ),
    )


class Memory1RecallExecutorTests(
    unittest.TestCase
):
    def test_result_is_immutable(
        self,
    ):
        fact = SimpleNamespace(
            id="fact-1"
        )

        result = execute_memory_recall_plan(
            fact_plan(),
            store=FakeCanonicalReadStore(
                facts=(
                    fact,
                )
            ),
        )

        self.assertIsInstance(
            result,
            MemoryRecallReadResult,
        )

        self.assertEqual(
            result.facts,
            (
                fact,
            ),
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            result.facts = ()

    def test_rejects_non_recall_plan_before_reads(
        self,
    ):
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.NONE,
                confidence=1.0,
                explicit_memory_request=False,
            )
        )

        store = FakeCanonicalReadStore()

        with self.assertRaises(
            MemoryValidationError
        ):
            execute_memory_recall_plan(
                plan,
                store=store,
            )

        self.assertEqual(
            store.calls,
            [],
        )

    def test_ambiguous_entity_is_uncertain_without_item_read(
        self,
    ):
        plan = relation_plan(
            target_action=(
                RecallEntityResolutionAction
                .AMBIGUOUS
            )
        )

        store = FakeCanonicalReadStore()
        result = execute_memory_recall_plan(
            plan,
            store=store,
        )

        self.assertEqual(
            tuple(item.outcome for item in result.items),
            (RecallItemOutcome.UNCERTAIN,),
        )
        self.assertEqual(result.aggregate, RecallAggregateOutcome.NONE_AVAILABLE)
        self.assertEqual(store.calls, [])

    def test_ambiguous_property_is_uncertain_without_item_read(
        self,
    ):
        plan = fact_plan(
            action=(
                RecallPropertyResolutionAction
                .AMBIGUOUS
            )
        )

        store = FakeCanonicalReadStore()
        result = execute_memory_recall_plan(
            plan,
            store=store,
        )

        self.assertEqual(
            tuple(item.outcome for item in result.items),
            (RecallItemOutcome.UNCERTAIN,),
        )
        self.assertEqual(result.aggregate, RecallAggregateOutcome.NONE_AVAILABLE)
        self.assertEqual(store.calls, [])

    def test_current_fact_reads_resolved_ids(
        self,
    ):
        fact = SimpleNamespace(
            id="fact-1"
        )

        store = FakeCanonicalReadStore(
            facts=(
                fact,
            )
        )

        result = execute_memory_recall_plan(
            fact_plan(),
            store=store,
        )

        self.assertEqual(
            result.facts,
            (
                fact,
            ),
        )

        self.assertEqual(
            result.relations,
            (),
        )

        self.assertEqual(
            store.calls,
            [
                (
                    "query_current_facts",
                    (
                        "owner-id",
                    ),
                    (
                        "property-language",
                    ),
                ),
            ],
        )

    def test_missed_fact_property_does_not_broaden(
        self,
    ):
        plan = fact_plan(
            action=(
                RecallPropertyResolutionAction
                .MISS
            )
        )

        store = FakeCanonicalReadStore(
            facts=(
                SimpleNamespace(
                    id="must-not-leak"
                ),
            )
        )

        result = execute_memory_recall_plan(
            plan,
            store=store,
        )

        self.assertEqual(
            result.facts,
            (),
        )

        self.assertEqual(
            store.calls,
            [],
        )

    def test_historical_relation_filters_target(
        self,
    ):
        wanted = SimpleNamespace(
            id="relation-1",
            target_entity_id="target-id",
        )

        unrelated = SimpleNamespace(
            id="relation-2",
            target_entity_id="other-id",
        )

        store = FakeCanonicalReadStore(
            relations=(
                wanted,
                unrelated,
            )
        )

        result = execute_memory_recall_plan(
            relation_plan(),
            store=store,
        )

        self.assertEqual(
            result.relations,
            (
                wanted,
            ),
        )

        self.assertEqual(
            store.calls,
            [
                (
                    "query_historical_relations",
                    (
                        "owner-id",
                    ),
                    (
                        "property-relationship",
                    ),
                ),
            ],
        )

    def test_as_of_revision_fact_dispatch(
        self,
    ):
        fact = SimpleNamespace(
            id="fact-as-of"
        )

        store = FakeCanonicalReadStore(
            facts=(
                fact,
            )
        )

        result = execute_memory_recall_plan(
            fact_plan(
                temporal_mode=(
                    QueryTemporalMode
                    .AS_OF_REVISION
                ),
                as_of_revision=2,
            ),
            store=store,
        )

        self.assertEqual(
            result.facts,
            (
                fact,
            ),
        )

        self.assertEqual(
            store.calls,
            [
                (
                    "query_facts_as_of_revision",
                    2,
                    (
                        "owner-id",
                    ),
                    (
                        "property-language",
                    ),
                ),
            ],
        )

    def test_missed_relation_property_does_not_broaden(
        self,
    ):
        plan = relation_plan(
            property_action=(
                RecallPropertyResolutionAction
                .MISS
            )
        )

        store = FakeCanonicalReadStore(
            relations=(
                SimpleNamespace(
                    id="must-not-leak",
                    target_entity_id="target-id",
                ),
            )
        )

        result = execute_memory_recall_plan(
            plan,
            store=store,
        )

        self.assertEqual(
            result.relations,
            (),
        )

        self.assertEqual(
            store.calls,
            [],
        )

    def test_unscoped_property_recall_fails_closed(
        self,
    ):
        query = MemoryQueryProposal(
            subject_refs=(
                "owner",
            ),
        )

        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(
                entity_resolution(
                    local_ref="owner",
                    canonical_id="owner-id",
                    trusted_binding=True,
                ),
            ),
        )

        store = FakeCanonicalReadStore()

        with self.assertRaisesRegex(
            MemoryValidationError,
            "explicit property query",
        ):
            execute_memory_recall_plan(
                plan,
                store=store,
            )

        self.assertEqual(
            store.calls,
            [],
        )

    def test_executor_has_no_write_legacy_or_mint_dependency(
        self,
    ):
        import jarvis_core.memory.recall_executor as module

        source = inspect.getsource(
            module
        )

        forbidden = (
            "begin_transaction",
            "create_fact",
            "create_relation",
            "create_entity",
            "create_property",
            "new_memory_id",
            "_mint_identity",
            "UnifiedMemoryIndex",
            "memory_retrieval",
            "MemoryGroundingExecutor",
            "StructuredRequest",
            "JARVIS_MEMORY_GROUNDING_EVIDENCE",
        )

        for token in forbidden:
            with self.subTest(
                token=token
            ):
                self.assertNotIn(
                    token,
                    source,
                )

        self.assertIn(
            "query_current_facts",
            source,
        )

        self.assertIn(
            "query_historical_facts",
            source,
        )

        self.assertIn(
            "query_facts_as_of_revision",
            source,
        )

        self.assertIn(
            "query_current_relations",
            source,
        )

        self.assertIn(
            "query_historical_relations",
            source,
        )

        self.assertIn(
            "query_relations_as_of_revision",
            source,
        )


if __name__ == "__main__":
    unittest.main()
