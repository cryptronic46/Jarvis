from __future__ import annotations

import ast
import inspect
import textwrap
import unittest
from dataclasses import (
    FrozenInstanceError,
    replace,
)
from unittest.mock import patch
from uuid import uuid4

import jarvis_core.memory.property_resolution as property_resolution_module

from jarvis_core.memory.enums import (
    Cardinality,
    MemoryStatus,
    PropertyKind,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.models import (
    CanonicalProperty,
)
from jarvis_core.memory.property_resolution import (
    CanonicalPropertyCatalogReader,
    RecallPropertyResolution,
    RecallPropertyResolutionAction,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    IdentitySelection,
)


def make_property(
    *,
    kind=PropertyKind.FACT,
    labels=("age",),
    semantic_type="property",
    status=MemoryStatus.ACTIVE,
    cardinality=Cardinality.SINGLE_CURRENT,
    value_type=ValueType.INTEGER,
):
    if (
        kind
        is PropertyKind.RELATION
    ):
        value_type = None

    return CanonicalProperty(
        id=(
            "property_"
            + uuid4().hex
        ),
        kind=kind,
        semantic_labels=tuple(
            labels
        ),
        semantic_type=semantic_type,
        cardinality=cardinality,
        value_type=value_type,
        status=status,
    )


class FakeRegistry:
    def __init__(
        self,
        properties=(),
        *,
        get_override=None,
    ):
        self.properties = tuple(
            properties
        )

        self.get_override = (
            get_override
        )

        self.list_calls = []
        self.get_calls = []

    def list_properties(
        self,
        *,
        kind=None,
    ):
        self.list_calls.append(
            kind
        )

        if kind is None:
            return self.properties

        return tuple(
            item
            for item
            in self.properties
            if (
                item.kind
                is kind
            )
        )

    def get_property(
        self,
        property_id,
    ):
        self.get_calls.append(
            property_id
        )

        if (
            self.get_override
            is not None
        ):
            return self.get_override

        for item in (
            self.properties
        ):
            if (
                item.id
                == property_id
            ):
                return item

        return None


class RecordingMatcher:
    def __init__(
        self,
        action,
        *,
        index=0,
        confidence=0.93,
    ):
        self.action = action
        self.index = index
        self.confidence = confidence
        self.calls = []

    def select_identity(
        self,
        *,
        domain,
        semantic_labels,
        semantic_type,
        candidates,
    ):
        self.calls.append(
            {
                "domain":
                    domain,

                "semantic_labels":
                    semantic_labels,

                "semantic_type":
                    semantic_type,

                "candidates":
                    candidates,
            }
        )

        if (
            self.action
            is IdentityResolutionAction
            .EXISTING
        ):
            return IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .EXISTING
                ),
                confidence=(
                    self.confidence
                ),
                selected_handle=(
                    candidates[
                        self.index
                    ]
                    .handle
                ),
            )

        return IdentitySelection(
            action=self.action,
            confidence=(
                self.confidence
            ),
        )


class Memory1RecallPropertyResolutionTests(
    unittest.TestCase,
):
    def test_result_is_immutable_and_retrieval_only(
        self,
    ):
        result = (
            RecallPropertyResolution(
                kind=(
                    PropertyKind.FACT
                ),
                action=(
                    RecallPropertyResolutionAction
                    .MISS
                ),
                confidence=0.8,
                canonical_id=None,
            )
        )

        self.assertEqual(
            tuple(
                result
                .__dataclass_fields__
            ),
            (
                "kind",
                "action",
                "confidence",
                "canonical_id",
            ),
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            result.canonical_id = (
                "property_invalid"
            )

    def test_miss_and_ambiguous_never_carry_id(
        self,
    ):
        for action in (
            RecallPropertyResolutionAction
            .MISS,
            RecallPropertyResolutionAction
            .AMBIGUOUS,
        ):
            with self.assertRaises(
                MemoryValidationError
            ):
                RecallPropertyResolution(
                    kind=(
                        PropertyKind.FACT
                    ),
                    action=action,
                    confidence=0.9,
                    canonical_id=(
                        "property_"
                        + uuid4().hex
                    ),
                )

    def test_existing_requires_id(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            RecallPropertyResolution(
                kind=(
                    PropertyKind.FACT
                ),
                action=(
                    RecallPropertyResolutionAction
                    .EXISTING
                ),
                confidence=0.9,
                canonical_id=None,
            )

    def test_api_has_no_write_structure_parameters(
        self,
    ):
        signature = inspect.signature(
            CanonicalPropertyCatalogReader
            .resolve_recall_property_identity
        )

        self.assertEqual(
            tuple(
                signature.parameters
            ),
            (
                "self",
                "matcher",
                "semantic_labels",
                "semantic_type",
                "kind",
            ),
        )

        self.assertNotIn(
            "cardinality",
            signature.parameters,
        )

        self.assertNotIn(
            "value_type",
            signature.parameters,
        )

    def test_existing_fact_resolves_without_defaults(
        self,
    ):
        stored = make_property(
            labels=(
                "age",
                "owner age",
            ),
            cardinality=(
                Cardinality
                .TEMPORAL_SINGLE
            ),
            value_type=(
                ValueType.INTEGER
            ),
        )

        registry = FakeRegistry(
            (
                stored,
            )
        )

        matcher = RecordingMatcher(
            IdentityResolutionAction
            .EXISTING
        )

        result = (
            CanonicalPropertyCatalogReader(
                registry
            )
            .resolve_recall_property_identity(
                matcher,
                (
                    "person age",
                ),
                "property",
                PropertyKind.FACT,
            )
        )

        self.assertEqual(
            result.action,
            RecallPropertyResolutionAction
            .EXISTING,
        )

        self.assertEqual(
            result.canonical_id,
            stored.id,
        )

        self.assertEqual(
            registry.get_calls,
            [
                stored.id
            ],
        )

        call = matcher.calls[0]

        self.assertEqual(
            call[
                "domain"
            ],
            CanonicalIdentityDomain
            .PROPERTY,
        )

        self.assertEqual(
            call[
                "semantic_labels"
            ],
            (
                "person age",
            ),
        )

        self.assertFalse(
            hasattr(
                call[
                    "candidates"
                ][0],
                "canonical_id",
            )
        )

    def test_fact_relation_catalogs_remain_separate(
        self,
    ):
        fact = make_property(
            labels=(
                "age",
            )
        )

        relation = make_property(
            kind=(
                PropertyKind.RELATION
            ),
            labels=(
                "parent",
            ),
        )

        registry = FakeRegistry(
            (
                fact,
                relation,
            )
        )

        matcher = RecordingMatcher(
            IdentityResolutionAction
            .EXISTING
        )

        result = (
            CanonicalPropertyCatalogReader(
                registry
            )
            .resolve_recall_property_identity(
                matcher,
                (
                    "parent",
                ),
                "relation",
                PropertyKind.RELATION,
            )
        )

        self.assertEqual(
            result.canonical_id,
            relation.id,
        )

        self.assertEqual(
            registry.list_calls,
            [
                PropertyKind.RELATION
            ],
        )

        self.assertEqual(
            len(
                matcher.calls[0][
                    "candidates"
                ]
            ),
            1,
        )

    def test_new_becomes_miss_without_mint(
        self,
    ):
        matcher = RecordingMatcher(
            IdentityResolutionAction
            .NEW,
            confidence=0.71,
        )

        with patch(
            "jarvis_core.memory."
            "resolution._mint_identity",
            side_effect=AssertionError(
                "RECALL cannot mint identity"
            ),
        ):
            result = (
                CanonicalPropertyCatalogReader(
                    FakeRegistry()
                )
                .resolve_recall_property_identity(
                    matcher,
                    (
                        "unknown property",
                    ),
                    "property",
                    PropertyKind.FACT,
                )
            )

        self.assertEqual(
            result.action,
            RecallPropertyResolutionAction
            .MISS,
        )

        self.assertIsNone(
            result.canonical_id
        )

        self.assertEqual(
            result.confidence,
            0.71,
        )

    def test_ambiguous_remains_explicit(
        self,
    ):
        result = (
            CanonicalPropertyCatalogReader(
                FakeRegistry()
            )
            .resolve_recall_property_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .AMBIGUOUS,
                    confidence=0.55,
                ),
                (
                    "ambiguous property",
                ),
                "property",
                PropertyKind.FACT,
            )
        )

        self.assertEqual(
            result.action,
            RecallPropertyResolutionAction
            .AMBIGUOUS,
        )

        self.assertIsNone(
            result.canonical_id
        )

    def test_disappearing_existing_fails_closed(
        self,
    ):
        stored = make_property()

        class DisappearingRegistry(
            FakeRegistry
        ):
            def get_property(
                self,
                property_id,
            ):
                self.get_calls.append(
                    property_id
                )
                return None

        reader = (
            CanonicalPropertyCatalogReader(
                DisappearingRegistry(
                    (
                        stored,
                    )
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                reader
                .resolve_recall_property_identity(
                    RecordingMatcher(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    (
                        "age",
                    ),
                    "property",
                    PropertyKind.FACT,
                )
            )

    def test_validation_checks_exists_active_kind_only(
        self,
    ):
        stored = make_property(
            cardinality=(
                Cardinality
                .TEMPORAL_MULTI
            ),
            value_type=(
                ValueType.JSON
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                FakeRegistry(
                    (
                        stored,
                    )
                )
            )
        )

        result = (
            reader
            .validate_existing_recall_property_contract(
                stored.id,
                PropertyKind.FACT,
            )
        )

        self.assertEqual(
            result.id,
            stored.id,
        )

        signature = inspect.signature(
            CanonicalPropertyCatalogReader
            .validate_existing_recall_property_contract
        )

        self.assertNotIn(
            "cardinality",
            signature.parameters,
        )

        self.assertNotIn(
            "value_type",
            signature.parameters,
        )

    def test_inactive_existing_fails_closed(
        self,
    ):
        active = make_property()

        inactive = replace(
            active,
            status=(
                MemoryStatus.RETRACTED
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                FakeRegistry(
                    (
                        active,
                    ),
                    get_override=inactive,
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                reader
                .resolve_recall_property_identity(
                    RecordingMatcher(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    (
                        "age",
                    ),
                    "property",
                    PropertyKind.FACT,
                )
            )

    def test_wrong_kind_fails_closed(
        self,
    ):
        relation = make_property(
            kind=(
                PropertyKind.RELATION
            ),
            labels=(
                "parent",
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                FakeRegistry(
                    (
                        relation,
                    ),
                    get_override=relation,
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                reader
                .validate_existing_recall_property_contract(
                    relation.id,
                    PropertyKind.FACT,
                )
            )

    def test_no_write_or_case_specific_dependency(
        self,
    ):
        method_source = inspect.getsource(
            CanonicalPropertyCatalogReader
            .resolve_recall_property_identity
        )

        method_tree = ast.parse(
            textwrap.dedent(
                method_source
            )
        )

        calls = []

        for node in ast.walk(
            method_tree
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

        for forbidden in (
            "create_property",
            "commit",
            "transaction",
            "execute",
            "_mint_identity",
        ):
            self.assertNotIn(
                forbidden,
                calls,
            )

        module_source = inspect.getsource(
            property_resolution_module
        ).lower()

        for forbidden in (
            "spotify",
            "preferred_color",
            "preference_for_color",
            "idade",
        ):
            self.assertNotIn(
                forbidden,
                module_source,
            )


if __name__ == "__main__":
    unittest.main()
