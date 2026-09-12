from __future__ import annotations

import inspect
import unittest
from dataclasses import (
    FrozenInstanceError,
)
from types import (
    SimpleNamespace,
)
from unittest.mock import (
    patch,
)

from jarvis_core.memory.entity_bindings import (
    TrustedEntityBindings,
)
from jarvis_core.memory.enums import (
    Cardinality,
    PropertyKind,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    EntityProposal,
    EntityQueryProposal,
    FactProposal,
    MemoryInterpretation,
    MemoryOperation,
    MemoryQueryProposal,
    PropertyProposal,
    PropertyQueryProposal,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
)
from jarvis_core.memory.entity_resolution import (
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from jarvis_core.memory.property_resolution import (
    RecallPropertyResolution,
    RecallPropertyResolutionAction,
)
import jarvis_core.memory.resolution_plan as resolution_plan


class NeverUsedRegistry:
    def __getattr__(
        self,
        name,
    ):
        raise AssertionError(
            "registry unexpectedly used: "
            + name
        )


class NeverUsedMatcher:
    def select_identity(
        self,
        **kwargs,
    ):
        raise AssertionError(
            "matcher unexpectedly used"
        )


class RecordingMatcher:
    def __init__(
        self,
    ):
        self.calls = []

    def select_identity(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        raise AssertionError(
            "real matcher should be "
            "intercepted by fake readers"
        )


class FakeEntityReader:
    instances = []

    def __init__(
        self,
        registry,
    ):
        self.registry = registry
        self.remember_calls = []
        self.recall_calls = []
        self.remember_validation_calls = []
        self.recall_validation_calls = []

        type(self).instances.append(
            self
        )

    def resolve_entity_identity(
        self,
        matcher,
        semantic_labels,
        semantic_type,
    ):
        self.remember_calls.append(
            (
                matcher,
                semantic_labels,
                semantic_type,
            )
        )

        return CanonicalIdentityResolution(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            action=(
                IdentityResolutionAction
                .NEW
            ),
            confidence=0.71,
            canonical_id=(
                "transient-entity-id"
            ),
        )

    def resolve_recall_entity_identity(
        self,
        matcher,
        semantic_labels,
        semantic_type,
    ):
        self.recall_calls.append(
            (
                matcher,
                semantic_labels,
                semantic_type,
            )
        )

        return RecallEntityResolution(
            action=(
                RecallEntityResolutionAction
                .MISS
            ),
            confidence=0.63,
            canonical_id=None,
        )

    def validate_existing_entity_contract(
        self,
        canonical_id,
    ):
        self.remember_validation_calls.append(
            canonical_id
        )

        return SimpleNamespace(
            id=canonical_id
        )

    def validate_existing_recall_entity_contract(
        self,
        canonical_id,
    ):
        self.recall_validation_calls.append(
            canonical_id
        )

        return SimpleNamespace(
            id=canonical_id
        )


class FakePropertyReader:
    instances = []

    def __init__(
        self,
        registry,
    ):
        self.registry = registry
        self.remember_calls = []
        self.recall_calls = []

        type(self).instances.append(
            self
        )

    def resolve_property_identity(
        self,
        matcher,
        semantic_labels,
        semantic_type,
        kind,
        cardinality,
        value_type,
    ):
        self.remember_calls.append(
            (
                matcher,
                semantic_labels,
                semantic_type,
                kind,
                cardinality,
                value_type,
            )
        )

        return CanonicalIdentityResolution(
            domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            action=(
                IdentityResolutionAction
                .NEW
            ),
            confidence=0.74,
            canonical_id=(
                "property_0123456789abcdef0123456789abcdef"
            ),
        )

    def resolve_recall_property_identity(
        self,
        matcher,
        semantic_labels,
        semantic_type,
        kind,
    ):
        self.recall_calls.append(
            (
                matcher,
                semantic_labels,
                semantic_type,
                kind,
            )
        )

        return RecallPropertyResolution(
            kind=kind,
            action=(
                RecallPropertyResolutionAction
                .MISS
            ),
            confidence=0.64,
            canonical_id=None,
        )


def fact_property():
    return PropertyProposal(
        local_ref="age_property",
        semantic_labels=(
            "age",
        ),
        semantic_type="age",
        cardinality=(
            Cardinality.SINGLE_CURRENT
        ),
        value_type=(
            ValueType.INTEGER
        ),
    )


def relation_property():
    return PropertyProposal(
        local_ref="relation_property",
        semantic_labels=(
            "relationship",
        ),
        semantic_type="relationship",
        cardinality=(
            Cardinality.MULTI_CURRENT
        ),
        value_type=None,
    )


def remember_fact(
    *,
    subject_ref="person_ref",
    property_ref="age_property",
):
    return FactProposal(
        subject_ref=subject_ref,
        property_ref=property_ref,
        value=38,
        memory_class=(
            resolution_plan
            .MemoryInterpretation
            .__dataclass_fields__[
                "facts"
            ]
            .default_factory()
            if False
            else __import__(
                "jarvis_core.memory.enums",
                fromlist=[
                    "MemoryClass"
                ],
            )
            .MemoryClass.FACTUAL
        ),
        confidence=0.91,
    )


class Memory1ResolutionPlanContractTests(
    unittest.TestCase,
):
    def setUp(
        self,
    ):
        FakeEntityReader.instances.clear()
        FakePropertyReader.instances.clear()

    def build_plan(
        self,
        interpretation,
        *,
        bindings=None,
        matcher=None,
    ):
        if bindings is None:
            bindings = (
                TrustedEntityBindings(
                    {}
                )
            )

        if matcher is None:
            matcher = (
                RecordingMatcher()
            )

        with (
            patch.object(
                resolution_plan,
                "CanonicalEntityCatalogReader",
                FakeEntityReader,
            ),
            patch.object(
                resolution_plan,
                "CanonicalPropertyCatalogReader",
                FakePropertyReader,
            ),
        ):
            plan = (
                resolution_plan
                .build_memory_resolution_plan(
                    interpretation,
                    matcher=matcher,
                    entity_registry=(
                        object()
                    ),
                    property_registry=(
                        object()
                    ),
                    trusted_entity_bindings=(
                        bindings
                    ),
                )
            )

        return (
            plan,
            matcher,
        )

    def test_plan_data_model_is_frozen(
        self,
    ):
        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.NONE
                ),
                confidence=1.0,
                explicit_memory_request=False,
            )
        )

        plan = (
            resolution_plan
            .MemoryResolutionPlan(
                interpretation=(
                    interpretation
                )
            )
        )

        self.assertEqual(
            tuple(
                plan
                .__dataclass_fields__
            ),
            (
                "interpretation",
                "remember_entities",
                "remember_fact_properties",
                "remember_relation_properties",
                "recall_entities",
                "recall_fact_properties",
                "recall_relation_properties",
                "recall_entity_resolution_failures",
                "recall_property_resolution_failures",
            ),
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            plan.remember_entities = ()

    def test_none_builds_empty_plan_without_readers_or_matcher(
        self,
    ):
        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.NONE
                ),
                confidence=1.0,
                explicit_memory_request=False,
            )
        )

        plan = (
            resolution_plan
            .build_memory_resolution_plan(
                interpretation,
                matcher=NeverUsedMatcher(),
                entity_registry=(
                    NeverUsedRegistry()
                ),
                property_registry=(
                    NeverUsedRegistry()
                ),
                trusted_entity_bindings=(
                    TrustedEntityBindings(
                        {}
                    )
                ),
            )
        )

        self.assertEqual(
            plan.remember_entities,
            (),
        )

        self.assertEqual(
            plan.recall_entities,
            (),
        )

    def test_remember_resolves_unbound_entity_and_fact_property(
        self,
    ):
        from jarvis_core.memory.enums import (
            MemoryClass,
        )

        entity = EntityProposal(
            local_ref="person_ref",
            canonical_name="Person",
            entity_type="person",
        )

        prop = fact_property()

        fact = FactProposal(
            subject_ref="person_ref",
            property_ref="age_property",
            value=38,
            memory_class=(
                MemoryClass.FACTUAL
            ),
            confidence=0.91,
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.REMEMBER
                ),
                confidence=0.99,
                explicit_memory_request=True,
                entities=(
                    entity,
                ),
                fact_properties=(
                    prop,
                ),
                facts=(
                    fact,
                ),
            )
        )

        plan, matcher = (
            self.build_plan(
                interpretation
            )
        )

        self.assertEqual(
            len(
                plan.remember_entities
            ),
            1,
        )

        entity_row = (
            plan.remember_entities[0]
        )

        self.assertEqual(
            entity_row.local_ref,
            "person_ref",
        )

        self.assertFalse(
            entity_row.trusted_binding
        )

        self.assertIs(
            entity_row.proposal,
            entity,
        )

        self.assertIs(
            entity_row.resolution.action,
            IdentityResolutionAction.NEW,
        )

        reader = (
            FakeEntityReader
            .instances[0]
        )

        self.assertEqual(
            reader.remember_calls[
                0
            ][1],
            (
                "Person",
            ),
        )

        self.assertEqual(
            reader.remember_calls[
                0
            ][2],
            "person",
        )

        self.assertEqual(
            len(
                plan
                .remember_fact_properties
            ),
            1,
        )

        property_row = (
            plan
            .remember_fact_properties[0]
        )

        self.assertIs(
            property_row.kind,
            PropertyKind.FACT,
        )

        self.assertIs(
            property_row.proposal,
            prop,
        )

        property_reader = (
            FakePropertyReader
            .instances[0]
        )

        self.assertEqual(
            property_reader
            .remember_calls[0][1:],
            (
                (
                    "age",
                ),
                "age",
                PropertyKind.FACT,
                Cardinality.SINGLE_CURRENT,
                ValueType.INTEGER,
            ),
        )

        self.assertEqual(
            fact.property_ref,
            property_row.local_ref,
        )

    def test_trusted_remember_binding_bypasses_semantic_resolution(
        self,
    ):
        from jarvis_core.memory.enums import (
            MemoryClass,
        )

        prop = fact_property()

        fact = FactProposal(
            subject_ref="owner",
            property_ref="age_property",
            value=38,
            memory_class=(
                MemoryClass.FACTUAL
            ),
            confidence=0.91,
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.REMEMBER
                ),
                confidence=0.99,
                explicit_memory_request=True,
                fact_properties=(
                    prop,
                ),
                facts=(
                    fact,
                ),
            )
        )

        bindings = (
            TrustedEntityBindings(
                {
                    "owner":
                        "canonical-owner",
                }
            )
        )

        plan, _ = (
            self.build_plan(
                interpretation,
                bindings=bindings,
            )
        )

        row = (
            plan.remember_entities[0]
        )

        self.assertTrue(
            row.trusted_binding
        )

        self.assertIsNone(
            row.proposal
        )

        self.assertIs(
            row.resolution.action,
            IdentityResolutionAction.EXISTING,
        )

        self.assertEqual(
            row.resolution.confidence,
            1.0,
        )

        self.assertEqual(
            row.resolution.canonical_id,
            "canonical-owner",
        )

        reader = (
            FakeEntityReader
            .instances[0]
        )

        self.assertEqual(
            reader.remember_calls,
            [],
        )

        self.assertEqual(
            reader.remember_validation_calls,
            [
                "canonical-owner",
            ],
        )

    def test_unused_remember_entity_proposal_fails_closed(
        self,
    ):
        from jarvis_core.memory.enums import (
            MemoryClass,
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.REMEMBER
                ),
                confidence=1.0,
                explicit_memory_request=True,
                entities=(
                    EntityProposal(
                        local_ref="unused_ref",
                        canonical_name="Unused",
                        entity_type="person",
                    ),
                ),
                fact_properties=(
                    fact_property(),
                ),
                facts=(
                    FactProposal(
                        subject_ref="owner",
                        property_ref=(
                            "age_property"
                        ),
                        value=38,
                        memory_class=(
                            MemoryClass.FACTUAL
                        ),
                        confidence=0.9,
                    ),
                ),
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            self.build_plan(
                interpretation,
                bindings=(
                    TrustedEntityBindings(
                        {
                            "owner":
                                "canonical-owner",
                        }
                    )
                ),
            )

    def test_recall_unbound_entity_and_property_preserve_miss(
        self,
    ):
        entity_query = (
            EntityQueryProposal(
                local_ref="person_ref",
                semantic_labels=(
                    "Person",
                ),
                semantic_type="person",
            )
        )

        property_query = (
            PropertyQueryProposal(
                semantic_labels=(
                    "age",
                ),
                semantic_type="age",
            )
        )

        query = (
            MemoryQueryProposal(
                subject_refs=(
                    "person_ref",
                ),
                entity_queries=(
                    entity_query,
                ),
                fact_properties=(
                    property_query,
                ),
            )
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.RECALL
                ),
                confidence=0.95,
                explicit_memory_request=True,
                query=query,
            )
        )

        plan, _ = (
            self.build_plan(
                interpretation
            )
        )

        self.assertEqual(
            len(
                plan.recall_entities
            ),
            1,
        )

        entity_row = (
            plan.recall_entities[0]
        )

        self.assertFalse(
            entity_row.trusted_binding
        )

        self.assertIs(
            entity_row.query,
            entity_query,
        )

        self.assertIs(
            entity_row.resolution.action,
            RecallEntityResolutionAction.MISS,
        )

        self.assertIsNone(
            entity_row.resolution.canonical_id
        )

        self.assertEqual(
            len(
                plan.recall_fact_properties
            ),
            1,
        )

        property_row = (
            plan
            .recall_fact_properties[0]
        )

        self.assertIs(
            property_row.kind,
            PropertyKind.FACT,
        )

        self.assertIs(
            property_row.query,
            property_query,
        )

        self.assertIs(
            property_row.resolution.action,
            RecallPropertyResolutionAction.MISS,
        )

        self.assertIsNone(
            property_row
            .resolution
            .canonical_id
        )

    def test_trusted_recall_binding_requires_no_query_and_uses_confidence_one(
        self,
    ):
        query = (
            MemoryQueryProposal(
                subject_refs=(
                    "owner",
                ),
            )
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.RECALL
                ),
                confidence=0.95,
                explicit_memory_request=True,
                query=query,
            )
        )

        plan, _ = (
            self.build_plan(
                interpretation,
                bindings=(
                    TrustedEntityBindings(
                        {
                            "owner":
                                "canonical-owner",
                        }
                    )
                ),
            )
        )

        row = (
            plan.recall_entities[0]
        )

        self.assertTrue(
            row.trusted_binding
        )

        self.assertIsNone(
            row.query
        )

        self.assertIs(
            row.resolution.action,
            RecallEntityResolutionAction.EXISTING,
        )

        self.assertEqual(
            row.resolution.confidence,
            1.0,
        )

        self.assertEqual(
            row.resolution.canonical_id,
            "canonical-owner",
        )

        reader = (
            FakeEntityReader
            .instances[0]
        )

        self.assertEqual(
            reader.recall_calls,
            [],
        )

        self.assertEqual(
            reader.recall_validation_calls,
            [
                "canonical-owner",
            ],
        )

    def test_bound_recall_query_is_retained_as_evidence_but_not_matched(
        self,
    ):
        evidence = (
            EntityQueryProposal(
                local_ref="owner",
                semantic_labels=(
                    "owner",
                ),
                semantic_type="person",
            )
        )

        query = (
            MemoryQueryProposal(
                subject_refs=(
                    "owner",
                ),
                entity_queries=(
                    evidence,
                ),
            )
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.RECALL
                ),
                confidence=0.95,
                explicit_memory_request=True,
                query=query,
            )
        )

        plan, _ = (
            self.build_plan(
                interpretation,
                bindings=(
                    TrustedEntityBindings(
                        {
                            "owner":
                                "canonical-owner",
                        }
                    )
                ),
            )
        )

        row = (
            plan.recall_entities[0]
        )

        self.assertIs(
            row.query,
            evidence,
        )

        self.assertTrue(
            row.trusted_binding
        )

        self.assertEqual(
            FakeEntityReader
            .instances[0]
            .recall_calls,
            [],
        )

    def test_unbound_recall_reference_without_query_fails_closed(
        self,
    ):
        query = (
            MemoryQueryProposal(
                subject_refs=(
                    "person_ref",
                ),
            )
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.RECALL
                ),
                confidence=0.95,
                explicit_memory_request=True,
                query=query,
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            self.build_plan(
                interpretation
            )

    def test_unused_entity_query_fails_closed(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            MemoryQueryProposal(
                subject_refs=(
                    "owner",
                ),
                entity_queries=(
                    EntityQueryProposal(
                        local_ref=(
                            "unused_ref"
                        ),
                        semantic_labels=(
                            "Unused",
                        ),
                        semantic_type=(
                            "person"
                        ),
                    ),
                ),
            )

    def test_duplicate_entity_references_resolve_once_in_first_use_order(
        self,
    ):
        from jarvis_core.memory.enums import (
            MemoryClass,
        )

        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.REMEMBER
                ),
                confidence=1.0,
                explicit_memory_request=True,
                fact_properties=(
                    fact_property(),
                ),
                facts=(
                    FactProposal(
                        subject_ref="owner",
                        property_ref=(
                            "age_property"
                        ),
                        value=38,
                        memory_class=(
                            MemoryClass.FACTUAL
                        ),
                        confidence=0.9,
                    ),
                    FactProposal(
                        subject_ref="owner",
                        property_ref=(
                            "age_property"
                        ),
                        value=39,
                        memory_class=(
                            MemoryClass.FACTUAL
                        ),
                        confidence=0.9,
                    ),
                ),
            )
        )

        plan, _ = (
            self.build_plan(
                interpretation,
                bindings=(
                    TrustedEntityBindings(
                        {
                            "owner":
                                "canonical-owner",
                        }
                    )
                ),
            )
        )

        self.assertEqual(
            tuple(
                row.local_ref
                for row
                in plan.remember_entities
            ),
            (
                "owner",
            ),
        )

        self.assertEqual(
            FakeEntityReader
            .instances[0]
            .remember_validation_calls,
            [
                "canonical-owner",
            ],
        )

    def test_module_has_no_write_model_or_language_repair_dependencies(
        self,
    ):
        source = inspect.getsource(
            resolution_plan
        )

        forbidden = (
            "canonical_store",
            "CanonicalMemoryStore",
            ".transaction(",
            "canonical_revision",
            "create_entity",
            "create_property",
            "create_fact",
            "create_relation",
            "model_adapter",
            "qwen_model",
            "brain",
            "import re",
            "from re",
            "predicate",
            "synonym",
            "spotify",
            "preferred_color",
        )

        for token in forbidden:
            self.assertNotIn(
                token,
                source,
            )

    def test_unsupported_operation_fails_closed(
        self,
    ):
        interpretation = (
            MemoryInterpretation(
                operation=(
                    MemoryOperation.FORGET
                ),
                confidence=1.0,
                explicit_memory_request=True,
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            resolution_plan.build_memory_resolution_plan(
                interpretation,
                matcher=NeverUsedMatcher(),
                entity_registry=object(),
                property_registry=object(),
                trusted_entity_bindings=(
                    TrustedEntityBindings(
                        {}
                    )
                ),
            )


if __name__ == "__main__":
    unittest.main()
