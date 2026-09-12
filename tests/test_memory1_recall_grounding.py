from __future__ import annotations

import inspect
import json
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from jarvis_core.memory.entity_resolution import (
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from jarvis_core.memory.enums import (
    PropertyKind,
    ValueType,
)
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
)
from jarvis_core.memory.recall_grounding import (
    MEMORY1_RECALL_SCOPE,
    Memory1RecallGrounding,
    build_memory1_recall_grounding,
)
from jarvis_core.memory.resolution_plan import (
    MemoryResolutionPlan,
    RecallEntityReferenceResolution,
    RecallPropertyQueryResolution,
)


def owner_resolution():
    return RecallEntityReferenceResolution(
        local_ref="owner",
        query=None,
        resolution=RecallEntityResolution(
            action=(
                RecallEntityResolutionAction
                .EXISTING
            ),
            confidence=1.0,
            canonical_id="owner-id",
        ),
        trusted_binding=True,
    )


def fact_query():
    return PropertyQueryProposal(
        semantic_labels=(
            "preferred_language",
        ),
        semantic_type="property",
    )


def fact_plan(
    *,
    property_action=(
        RecallPropertyResolutionAction
        .EXISTING
    ),
):
    prop = fact_query()

    query = MemoryQueryProposal(
        subject_refs=(
            "owner",
        ),
        fact_properties=(
            prop,
        ),
        temporal_mode=(
            QueryTemporalMode.CURRENT
        ),
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
            owner_resolution(),
        ),
        recall_fact_properties=(
            RecallPropertyQueryResolution(
                kind=PropertyKind.FACT,
                query=prop,
                resolution=(
                    RecallPropertyResolution(
                        kind=PropertyKind.FACT,
                        action=property_action,
                        confidence=1.0,
                        canonical_id=(
                            "property-language"
                            if property_action
                            is RecallPropertyResolutionAction
                            .EXISTING
                            else None
                        ),
                    )
                ),
            ),
        ),
    )


def canonical_fact(
    *,
    subject_id="owner-id",
    property_id="property-language",
    value="pt-PT",
):
    return SimpleNamespace(
        id="fact-private-id",
        subject_entity_id=(
            subject_id
        ),
        property_id=property_id,
        value=SimpleNamespace(
            value_type=ValueType.STRING,
            value=value,
            unit=None,
            entity_id=None,
        ),
        memory_class="PREFERENCE",
        authority="OWNER_EXPLICIT",
        confidence=1.0,
        valid_from=None,
        valid_until=None,
        recorded_at=None,
    )


def relation_plan():
    prop = PropertyQueryProposal(
        semantic_labels=(
            "relationship",
        ),
        semantic_type="relationship",
    )

    target_query = (
        EntityQueryProposal(
            local_ref="target",
            semantic_labels=(
                "target person",
            ),
            semantic_type="person",
        )
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
        temporal_mode=(
            QueryTemporalMode.CURRENT
        ),
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
            owner_resolution(),
            RecallEntityReferenceResolution(
                local_ref="target",
                query=target_query,
                resolution=(
                    RecallEntityResolution(
                        action=(
                            RecallEntityResolutionAction
                            .EXISTING
                        ),
                        confidence=1.0,
                        canonical_id="target-id",
                    )
                ),
                trusted_binding=False,
            ),
        ),
        recall_relation_properties=(
            RecallPropertyQueryResolution(
                kind=PropertyKind.RELATION,
                query=prop,
                resolution=(
                    RecallPropertyResolution(
                        kind=(
                            PropertyKind.RELATION
                        ),
                        action=(
                            RecallPropertyResolutionAction
                            .EXISTING
                        ),
                        confidence=1.0,
                        canonical_id=(
                            "property-relationship"
                        ),
                    )
                ),
            ),
        ),
    )


class Memory1RecallGroundingTests(
    unittest.TestCase
):
    def test_fact_grounding_uses_existing_hard_scope_markers(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(
                canonical_fact(),
            ),
            relations=(),
        )

        grounding = (
            build_memory1_recall_grounding(
                result
            )
        )

        self.assertIsInstance(
            grounding,
            Memory1RecallGrounding,
        )

        self.assertEqual(
            grounding.memory_scope,
            MEMORY1_RECALL_SCOPE,
        )

        self.assertEqual(
            grounding.evidence_count,
            1,
        )

        self.assertEqual(
            grounding.evidence_status,
            "available",
        )

        self.assertIn(
            "JARVIS_MEMORY_GROUNDING_EVIDENCE",
            grounding.context,
        )

        self.assertIn(
            "memory_scope=memory1_canonical_recall",
            grounding.context,
        )

        self.assertIn(
            "evidence_status=available",
            grounding.context,
        )

        self.assertIn(
            "SCOPED GROUNDING CONTRACT:",
            grounding.context,
        )

    def test_fact_grounding_contains_semantics_and_value_but_no_private_ids(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(
                canonical_fact(),
            ),
            relations=(),
        )

        context = (
            build_memory1_recall_grounding(
                result
            )
            .context
        )

        self.assertIn(
            "preferred_language",
            context,
        )

        self.assertIn(
            "pt-PT",
            context,
        )

        for private_id in (
            "owner-id",
            "property-language",
            "fact-private-id",
        ):
            with self.subTest(
                private_id=private_id
            ):
                self.assertNotIn(
                    private_id,
                    context,
                )

    def test_empty_result_preserves_hard_empty_scope(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(
                property_action=(
                    RecallPropertyResolutionAction
                    .MISS
                )
            ),
            facts=(),
            relations=(),
        )

        grounding = (
            build_memory1_recall_grounding(
                result
            )
        )

        self.assertEqual(
            grounding.evidence_count,
            0,
        )

        self.assertEqual(
            grounding.evidence_status,
            "empty",
        )

        self.assertIn(
            "memory_scope=memory1_canonical_recall",
            grounding.context,
        )

        self.assertIn(
            "evidence_status=empty",
            grounding.context,
        )

        self.assertIn(
            "[NO ADMISSIBLE MEMORY EVIDENCE]",
            grounding.context,
        )

        self.assertIn(
            "Do not fill missing evidence",
            grounding.context,
        )

    def test_grounding_is_deterministic(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(
                canonical_fact(),
            ),
            relations=(),
        )

        first = (
            build_memory1_recall_grounding(
                result
            )
        )

        second = (
            build_memory1_recall_grounding(
                result
            )
        )

        self.assertEqual(
            first,
            second,
        )

    def test_grounding_result_is_immutable(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(),
            relations=(),
        )

        grounding = (
            build_memory1_recall_grounding(
                result
            )
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            grounding.context = "changed"

    def test_relation_grounding_uses_request_local_refs_not_canonical_ids(
        self,
    ):
        relation = SimpleNamespace(
            id="relation-private-id",
            source_entity_id="owner-id",
            property_id=(
                "property-relationship"
            ),
            target_entity_id="target-id",
            memory_class="FACTUAL",
            authority="OWNER_EXPLICIT",
            confidence=1.0,
            valid_from=None,
            valid_until=None,
            recorded_at=None,
        )

        result = MemoryRecallReadResult(
            plan=relation_plan(),
            facts=(),
            relations=(
                relation,
            ),
        )

        grounding = (
            build_memory1_recall_grounding(
                result
            )
        )

        context = grounding.context

        self.assertIn(
            '"kind":"RELATION"',
            context,
        )

        self.assertIn(
            '"source_ref":"owner"',
            context,
        )

        self.assertIn(
            '"target_ref":"target"',
            context,
        )

        self.assertIn(
            '"relationship"',
            context,
        )

        for private_id in (
            "owner-id",
            "target-id",
            "property-relationship",
            "relation-private-id",
        ):
            with self.subTest(
                private_id=private_id
            ):
                self.assertNotIn(
                    private_id,
                    context,
                )

    def test_out_of_scope_fact_subject_fails_closed(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(
                canonical_fact(
                    subject_id=(
                        "unresolved-id"
                    )
                ),
            ),
            relations=(),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "outside",
        ):
            build_memory1_recall_grounding(
                result
            )

    def test_out_of_scope_fact_property_fails_closed(
        self,
    ):
        result = MemoryRecallReadResult(
            plan=fact_plan(),
            facts=(
                canonical_fact(
                    property_id=(
                        "wrong-property-id"
                    )
                ),
            ),
            relations=(),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "outside",
        ):
            build_memory1_recall_grounding(
                result
            )

    def test_non_recall_plan_fails_closed(
        self,
    ):
        plan = MemoryResolutionPlan(
            interpretation=(
                MemoryInterpretation(
                    operation=(
                        MemoryOperation.NONE
                    ),
                    confidence=1.0,
                    explicit_memory_request=False,
                )
            )
        )

        result = MemoryRecallReadResult(
            plan=plan,
            facts=(),
            relations=(),
        )

        with self.assertRaisesRegex(
            MemoryValidationError,
            "RECALL only",
        ):
            build_memory1_recall_grounding(
                result
            )

    def test_adapter_has_no_write_legacy_runtime_or_model_dependency(
        self,
    ):
        import jarvis_core.memory.recall_grounding as module

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
            "JarvisBrain",
            "HybridBrain",
            "client.chat",
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
            "JARVIS_MEMORY_GROUNDING_EVIDENCE",
            source,
        )

        self.assertIn(
            "memory_scope=",
            source,
        )

        self.assertIn(
            "MemoryRecallReadResult",
            source,
        )


if __name__ == "__main__":
    unittest.main()
