from __future__ import annotations

import ast
import importlib
import inspect
import tempfile
import unittest
import uuid
from pathlib import Path

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)
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
    PropertySemanticContext,
)
from jarvis_core.memory.resolution import (
    IdentityResolutionAction,
    IdentitySelection,
    PROPERTY_ID_PREFIX,
)


def property_id() -> str:
    return (
        PROPERTY_ID_PREFIX
        + uuid.uuid4().hex
    )


def module_ast():
    module = (
        importlib
        .import_module(
            "jarvis_core.memory."
            "property_resolution"
        )
    )

    source = (
        inspect
        .getsource(
            module
        )
    )

    return (
        source,
        ast.parse(
            source
        ),
    )


def imported_modules(
    tree,
):
    result = []

    for node in ast.walk(
        tree
    ):
        if isinstance(
            node,
            ast.Import,
        ):
            result.extend(
                alias.name
                for alias
                in node.names
            )

        elif isinstance(
            node,
            ast.ImportFrom,
        ):
            if node.module:
                result.append(
                    node.module
                )

    return tuple(
        result
    )


def called_names(
    tree,
):
    result = []

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        function = (
            node.func
        )

        if isinstance(
            function,
            ast.Attribute,
        ):
            result.append(
                function.attr
            )

        elif isinstance(
            function,
            ast.Name,
        ):
            result.append(
                function.id
            )

    return tuple(
        result
    )


class RecordingMatcher:
    def __init__(
        self,
        action: IdentityResolutionAction,
        *,
        selected_handle: str | None = None,
        confidence: float = 0.95,
    ) -> None:
        self.action = action
        self.selected_handle = (
            selected_handle
        )
        self.confidence = (
            confidence
        )
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

        return IdentitySelection(
            action=self.action,
            confidence=(
                self.confidence
            ),
            selected_handle=(
                self.selected_handle
            ),
        )


class RegistrySpy:
    def __init__(
        self,
        properties,
    ) -> None:
        self.properties = tuple(
            properties
        )

        self.calls = []

    def get_property(
        self,
        property_id_value,
    ):
        self.calls.append(
            (
                "get_property",
                property_id_value,
            )
        )

        for property in (
            self.properties
        ):
            if (
                property.id
                == property_id_value
            ):
                return property

        return None

    def list_properties(
        self,
        *,
        kind=None,
    ):
        self.calls.append(
            (
                "list_properties",
                kind,
            )
        )

        if kind is None:
            return (
                self.properties
            )

        return tuple(
            property
            for property
            in self.properties
            if property.kind is kind
        )


class Memory1RegistryBackedPropertyResolutionTests(
    unittest.TestCase,
):
    def fact_property(
        self,
        *,
        cardinality=(
            Cardinality
            .SINGLE_CURRENT
        ),
        value_type=(
            ValueType.STRING
        ),
        status=(
            MemoryStatus.ACTIVE
        ),
    ):
        return CanonicalProperty(
            id=property_id(),
            kind=PropertyKind.FACT,
            semantic_labels=(
                "semantic_alpha",
                "semantic_beta",
            ),
            semantic_type=(
                "scalar_attribute"
            ),
            cardinality=(
                cardinality
            ),
            value_type=(
                value_type
            ),
            status=status,
        )

    def relation_property(
        self,
        *,
        cardinality=(
            Cardinality
            .MULTI_CURRENT
        ),
        status=(
            MemoryStatus.ACTIVE
        ),
    ):
        return CanonicalProperty(
            id=property_id(),
            kind=(
                PropertyKind
                .RELATION
            ),
            semantic_labels=(
                "semantic_relation",
            ),
            semantic_type=(
                "entity_relation"
            ),
            cardinality=(
                cardinality
            ),
            value_type=None,
            status=status,
        )

    def test_semantic_context_is_frozen_and_has_no_canonical_id(
        self,
    ):
        context = (
            PropertySemanticContext(
                semantic_labels=(
                    "alpha",
                    "beta",
                ),
                semantic_type=(
                    "attribute"
                ),
            )
        )

        self.assertFalse(
            hasattr(
                context,
                "canonical_id",
            )
        )

        with self.assertRaises(
            Exception
        ):
            context.semantic_type = (
                "changed"
            )

    def test_property_catalog_uses_registry_and_keeps_kinds_separate(
        self,
    ):
        fact = (
            self.fact_property()
        )

        relation = (
            self.relation_property()
        )

        registry = RegistrySpy(
            (
                fact,
                relation,
            )
        )

        reader = (
            CanonicalPropertyCatalogReader(
                registry
            )
        )

        context = (
            PropertySemanticContext(
                semantic_labels=(
                    "query_label",
                ),
                semantic_type=(
                    "query_type"
                ),
            )
        )

        fact_catalog = (
            reader
            .build_property_catalog(
                PropertyKind.FACT,
                context,
            )
        )

        relation_catalog = (
            reader
            .build_property_catalog(
                PropertyKind.RELATION,
                context,
            )
        )

        self.assertEqual(
            tuple(
                candidate
                .canonical_id
                for candidate
                in fact_catalog
                .candidates
            ),
            (
                fact.id,
            ),
        )

        self.assertEqual(
            tuple(
                candidate
                .canonical_id
                for candidate
                in relation_catalog
                .candidates
            ),
            (
                relation.id,
            ),
        )

    def test_inactive_properties_are_not_match_candidates(
        self,
    ):
        active = (
            self.fact_property()
        )

        inactive = (
            self.fact_property(
                status=(
                    MemoryStatus
                    .QUARANTINED
                )
            )
        )

        registry = RegistrySpy(
            (
                active,
                inactive,
            )
        )

        reader = (
            CanonicalPropertyCatalogReader(
                registry
            )
        )

        catalog = (
            reader
            .build_property_catalog(
                PropertyKind.FACT,
                PropertySemanticContext(
                    semantic_labels=(
                        "query",
                    ),
                    semantic_type=(
                        "attribute"
                    ),
                ),
            )
        )

        self.assertEqual(
            tuple(
                candidate
                .canonical_id
                for candidate
                in catalog
                .candidates
            ),
            (
                active.id,
            ),
        )

    def test_matcher_sees_handles_but_never_canonical_ids(
        self,
    ):
        fact = (
            self.fact_property()
        )

        registry = RegistrySpy(
            (
                fact,
            )
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .EXISTING
            ),
            selected_handle=(
                "candidate_0000"
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                registry
            )
        )

        result = (
            reader
            .resolve_property_identity(
                matcher,
                (
                    "semantic_alpha",
                ),
                "scalar_attribute",
                PropertyKind.FACT,
                (
                    Cardinality
                    .SINGLE_CURRENT
                ),
                ValueType.STRING,
            )
        )

        self.assertEqual(
            result.canonical_id,
            fact.id,
        )

        self.assertEqual(
            len(
                matcher.calls
            ),
            1,
        )

        candidates = (
            matcher.calls[0][
                "candidates"
            ]
        )

        self.assertEqual(
            len(candidates),
            1,
        )

        self.assertFalse(
            hasattr(
                candidates[0],
                "canonical_id",
            )
        )

        self.assertEqual(
            candidates[0].handle,
            "candidate_0000",
        )

    def test_semantic_labels_pass_to_matcher_without_mapping(
        self,
    ):
        fact = (
            self.fact_property()
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .EXISTING
            ),
            selected_handle=(
                "candidate_0000"
            ),
        )

        labels = (
            "first_semantic_label",
            "second_semantic_label",
        )

        reader = (
            CanonicalPropertyCatalogReader(
                RegistrySpy(
                    (
                        fact,
                    )
                )
            )
        )

        reader.resolve_property_identity(
            matcher,
            labels,
            "scalar_attribute",
            PropertyKind.FACT,
            (
                Cardinality
                .SINGLE_CURRENT
            ),
            ValueType.STRING,
        )

        self.assertEqual(
            matcher.calls[0][
                "semantic_labels"
            ],
            labels,
        )

    def test_existing_value_type_mismatch_fails_closed(
        self,
    ):
        fact = (
            self.fact_property(
                value_type=(
                    ValueType.STRING
                )
            )
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .EXISTING
            ),
            selected_handle=(
                "candidate_0000"
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                RegistrySpy(
                    (
                        fact,
                    )
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            reader.resolve_property_identity(
                matcher,
                (
                    "semantic_alpha",
                ),
                "scalar_attribute",
                PropertyKind.FACT,
                (
                    Cardinality
                    .SINGLE_CURRENT
                ),
                ValueType.INTEGER,
            )

    def test_existing_cardinality_mismatch_fails_closed(
        self,
    ):
        fact = (
            self.fact_property(
                cardinality=(
                    Cardinality
                    .SINGLE_CURRENT
                )
            )
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .EXISTING
            ),
            selected_handle=(
                "candidate_0000"
            ),
        )

        reader = (
            CanonicalPropertyCatalogReader(
                RegistrySpy(
                    (
                        fact,
                    )
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            reader.resolve_property_identity(
                matcher,
                (
                    "semantic_alpha",
                ),
                "scalar_attribute",
                PropertyKind.FACT,
                (
                    Cardinality
                    .MULTI_CURRENT
                ),
                ValueType.STRING,
            )

    def test_relation_resolution_forbids_value_type(
        self,
    ):
        relation = (
            self.relation_property()
        )

        reader = (
            CanonicalPropertyCatalogReader(
                RegistrySpy(
                    (
                        relation,
                    )
                )
            )
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .EXISTING
            ),
            selected_handle=(
                "candidate_0000"
            ),
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            reader.resolve_property_identity(
                matcher,
                (
                    "semantic_relation",
                ),
                "entity_relation",
                PropertyKind.RELATION,
                (
                    Cardinality
                    .MULTI_CURRENT
                ),
                ValueType.ENTITY_REF,
            )

    def test_new_resolution_is_core_minted_but_not_persisted(
        self,
    ):
        registry = RegistrySpy(
            ()
        )

        reader = (
            CanonicalPropertyCatalogReader(
                registry
            )
        )

        matcher = RecordingMatcher(
            (
                IdentityResolutionAction
                .NEW
            ),
        )

        result = (
            reader
            .resolve_property_identity(
                matcher,
                (
                    "unseen_semantic",
                ),
                "scalar_attribute",
                PropertyKind.FACT,
                (
                    Cardinality
                    .SINGLE_CURRENT
                ),
                ValueType.STRING,
            )
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction.NEW,
        )

        self.assertTrue(
            (
                result.canonical_id
                or ""
            ).startswith(
                PROPERTY_ID_PREFIX
            )
        )

        self.assertEqual(
            registry.calls,
            [
                (
                    "list_properties",
                    PropertyKind.FACT,
                ),
            ],
        )

    def test_ambiguous_resolution_has_no_canonical_identity(
        self,
    ):
        fact = (
            self.fact_property()
        )

        reader = (
            CanonicalPropertyCatalogReader(
                RegistrySpy(
                    (
                        fact,
                    )
                )
            )
        )

        result = (
            reader
            .resolve_property_identity(
                RecordingMatcher(
                    (
                        IdentityResolutionAction
                        .AMBIGUOUS
                    )
                ),
                (
                    "semantic_alpha",
                ),
                "scalar_attribute",
                PropertyKind.FACT,
                (
                    Cardinality
                    .SINGLE_CURRENT
                ),
                ValueType.STRING,
            )
        )

        self.assertIs(
            result.action,
            (
                IdentityResolutionAction
                .AMBIGUOUS
            ),
        )

        self.assertIsNone(
            result.canonical_id
        )

    def test_reader_uses_only_read_registry_surface(
        self,
    ):
        fact = (
            self.fact_property()
        )

        registry = RegistrySpy(
            (
                fact,
            )
        )

        reader = (
            CanonicalPropertyCatalogReader(
                registry
            )
        )

        reader.resolve_property_identity(
            RecordingMatcher(
                (
                    IdentityResolutionAction
                    .EXISTING
                ),
                selected_handle=(
                    "candidate_0000"
                ),
            ),
            (
                "semantic_alpha",
            ),
            "scalar_attribute",
            PropertyKind.FACT,
            (
                Cardinality
                .SINGLE_CURRENT
            ),
            ValueType.STRING,
        )

        self.assertEqual(
            registry.calls,
            [
                (
                    "list_properties",
                    PropertyKind.FACT,
                ),
                (
                    "get_property",
                    fact.id,
                ),
            ],
        )

    def test_real_store_resolution_does_not_consume_revision(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            path = (
                Path(temp)
                / "memory.sqlite3"
            )

            store = (
                CanonicalMemoryStore(
                    path
                )
            )

            fact = (
                self.fact_property()
            )

            with (
                store
                .begin_transaction()
            ) as transaction:
                transaction.create_property(
                    fact
                )

                receipt = (
                    transaction
                    .commit()
                )

            revision_before = (
                store
                .canonical_revision()
            )

            self.assertEqual(
                revision_before,
                receipt
                .canonical_revision,
            )

            reader = (
                CanonicalPropertyCatalogReader(
                    store
                )
            )

            result = (
                reader
                .resolve_property_identity(
                    RecordingMatcher(
                        (
                            IdentityResolutionAction
                            .EXISTING
                        ),
                        selected_handle=(
                            "candidate_0000"
                        ),
                    ),
                    (
                        "semantic_alpha",
                    ),
                    "scalar_attribute",
                    PropertyKind.FACT,
                    (
                        Cardinality
                        .SINGLE_CURRENT
                    ),
                    ValueType.STRING,
                )
            )

            self.assertEqual(
                result.canonical_id,
                fact.id,
            )

            self.assertEqual(
                store
                .canonical_revision(),
                revision_before,
            )

            new_result = (
                reader
                .resolve_property_identity(
                    RecordingMatcher(
                        (
                            IdentityResolutionAction
                            .NEW
                        )
                    ),
                    (
                        "another_semantic",
                    ),
                    "scalar_attribute",
                    PropertyKind.FACT,
                    (
                        Cardinality
                        .SINGLE_CURRENT
                    ),
                    ValueType.STRING,
                )
            )

            self.assertIs(
                new_result.action,
                (
                    IdentityResolutionAction
                    .NEW
                ),
            )

            self.assertIsNone(
                store.get_property(
                    (
                        new_result
                        .canonical_id
                        or ""
                    )
                )
            )

            self.assertEqual(
                store
                .canonical_revision(),
                revision_before,
            )

    def test_property_resolution_module_has_no_regex_dependency(
        self,
    ):
        _, tree = (
            module_ast()
        )

        imports = (
            imported_modules(
                tree
            )
        )

        forbidden = {
            "re",
            "regex",
        }

        actual = tuple(
            name
            for name
            in imports
            if (
                name in forbidden
                or name.split(
                    "."
                )[0]
                in forbidden
            )
        )

        self.assertEqual(
            actual,
            (),
        )

    def test_property_resolution_module_has_no_case_specific_repairs(
        self,
    ):
        source, _ = (
            module_ast()
        )

        lowered = (
            source.lower()
        )

        for forbidden in (
            "spotify",
            "preferred_color",
            "preference_for_color",
            "favorite_color",
            "favourite_color",
            "marta",
            "wife",
            "sister",
        ):
            self.assertNotIn(
                forbidden,
                lowered,
            )

    def test_property_resolution_module_has_no_write_calls(
        self,
    ):
        _, tree = (
            module_ast()
        )

        calls = set(
            called_names(
                tree
            )
        )

        forbidden = {
            "begin_transaction",
            "create_property",
            "create_fact",
            "create_relation",
            "commit",
        }

        self.assertEqual(
            calls
            & forbidden,
            set(),
        )


if __name__ == "__main__":
    unittest.main()
