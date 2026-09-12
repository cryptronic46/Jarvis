from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
from dataclasses import (
    FrozenInstanceError,
    replace,
)
from pathlib import Path
from uuid import UUID

import jarvis_core.memory.entity_resolution as entity_resolution_module

from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)
from jarvis_core.memory.entity_resolution import (
    CanonicalEntityCatalogReader,
    EntitySemanticContext,
)
from jarvis_core.memory.enums import (
    MemoryNamespace,
    MemoryStatus,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.models import (
    Entity,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    IdentitySelection,
)


class FakeEntityRegistry:
    def __init__(
        self,
        entities=(),
        *,
        missing_on_get=False,
    ):
        self.entities = tuple(
            entities
        )

        self.missing_on_get = (
            missing_on_get
        )

        self.get_calls = []
        self.list_calls = 0

    def get_entity(
        self,
        entity_id,
    ):
        self.get_calls.append(
            entity_id
        )

        if self.missing_on_get:
            return None

        for entity in self.entities:
            if (
                entity.id
                == entity_id
            ):
                return entity

        return None

    def list_entities(
        self,
    ):
        self.list_calls += 1
        return self.entities


class RecordingMatcher:
    def __init__(
        self,
        action,
        *,
        index=0,
    ):
        self.action = action
        self.index = index
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
                confidence=0.99,
                selected_handle=(
                    candidates[
                        self.index
                    ]
                    .handle
                ),
            )

        return IdentitySelection(
            action=self.action,
            confidence=0.99,
        )


def make_entity(
    *,
    name,
    entity_type="PERSON",
    aliases=(),
    status=MemoryStatus.ACTIVE,
    namespace=MemoryNamespace.PERSON,
):
    created = Entity.create(
        namespace=namespace,
        canonical_name=name,
        entity_type=entity_type,
        aliases=tuple(
            aliases
        ),
    )

    if (
        status
        is MemoryStatus.ACTIVE
    ):
        return created

    return replace(
        created,
        status=status,
    )


class Memory1RegistryBackedEntityResolutionTests(
    unittest.TestCase,
):
    def test_semantic_context_is_frozen_and_narrow(
        self,
    ):
        context = (
            EntitySemanticContext(
                semantic_labels=(
                    "semantic entity",
                ),
                semantic_type="PERSON",
            )
        )

        self.assertEqual(
            tuple(
                context
                .__dataclass_fields__
            ),
            (
                "semantic_labels",
                "semantic_type",
            ),
        )

        self.assertFalse(
            hasattr(
                context,
                "canonical_id",
            )
        )

        self.assertFalse(
            hasattr(
                context,
                "namespace",
            )
        )

        self.assertFalse(
            hasattr(
                context,
                "namespace_hint",
            )
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            context.semantic_type = (
                "DEVICE"
            )

    def test_semantic_context_fails_closed(
        self,
    ):
        bad_cases = (
            {
                "semantic_labels":
                    (),
                "semantic_type":
                    "PERSON",
            },
            {
                "semantic_labels":
                    (
                        "entity",
                        "entity",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "semantic_labels":
                    (
                        " entity ",
                    ),
                "semantic_type":
                    "PERSON",
            },
            {
                "semantic_labels":
                    (
                        "entity",
                    ),
                "semantic_type":
                    " PERSON ",
            },
        )

        for case in bad_cases:
            with self.subTest(
                case=case
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    EntitySemanticContext(
                        **case
                    )

    def test_reader_requires_read_only_registry_surface(
        self,
    ):
        class MissingAll:
            pass

        class MissingList:
            def get_entity(
                self,
                entity_id,
            ):
                return None

        class MissingGet:
            def list_entities(
                self,
            ):
                return ()

        for registry in (
            MissingAll(),
            MissingList(),
            MissingGet(),
        ):
            with self.subTest(
                registry=type(
                    registry
                ).__name__
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    CanonicalEntityCatalogReader(
                        registry
                    )

    def test_catalog_uses_only_persisted_entity_semantics(
        self,
    ):
        first = make_entity(
            name="ENTITY ONE",
            aliases=(
                "ENTITY ALIAS",
            ),
        )

        second = make_entity(
            name="DEVICE ONE",
            entity_type="DEVICE",
            namespace=(
                MemoryNamespace.DEVICE
            ),
        )

        inactive = make_entity(
            name="OLD ENTITY",
            status=(
                MemoryStatus.RETRACTED
            ),
        )

        registry = (
            FakeEntityRegistry(
                (
                    first,
                    second,
                    inactive,
                )
            )
        )

        reader = (
            CanonicalEntityCatalogReader(
                registry
            )
        )

        catalog = (
            reader
            .build_entity_catalog(
                EntitySemanticContext(
                    semantic_labels=(
                        "completely unrelated",
                    ),
                    semantic_type=(
                        "UNRELATED"
                    ),
                )
            )
        )

        self.assertEqual(
            catalog.domain,
            CanonicalIdentityDomain.ENTITY,
        )

        self.assertEqual(
            len(
                catalog.candidates
            ),
            2,
        )

        self.assertEqual(
            catalog
            .candidates[0]
            .semantic_labels,
            (
                "ENTITY ONE",
                "ENTITY ALIAS",
            ),
        )

        self.assertEqual(
            catalog
            .candidates[0]
            .semantic_type,
            "PERSON",
        )

        self.assertEqual(
            catalog
            .candidates[1]
            .semantic_labels,
            (
                "DEVICE ONE",
            ),
        )

        self.assertEqual(
            catalog
            .candidates[1]
            .semantic_type,
            "DEVICE",
        )

        self.assertEqual(
            registry.list_calls,
            1,
        )

    def test_duplicate_persisted_labels_fail_closed(
        self,
    ):
        malformed = make_entity(
            name="ENTITY ONE",
            aliases=(
                "ENTITY ONE",
            ),
        )

        reader = (
            CanonicalEntityCatalogReader(
                FakeEntityRegistry(
                    (
                        malformed,
                    )
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            reader.build_entity_catalog(
                EntitySemanticContext(
                    semantic_labels=(
                        "entity",
                    ),
                    semantic_type=(
                        "PERSON"
                    ),
                )
            )

    def test_matcher_never_sees_canonical_entity_ids(
        self,
    ):
        stored = make_entity(
            name="STORED ENTITY",
            aliases=(
                "STORED ALIAS",
            ),
        )

        matcher = RecordingMatcher(
            IdentityResolutionAction
            .EXISTING
        )

        reader = (
            CanonicalEntityCatalogReader(
                FakeEntityRegistry(
                    (
                        stored,
                    )
                )
            )
        )

        result = (
            reader
            .resolve_entity_identity(
                matcher,
                (
                    "same semantic entity",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.canonical_id,
            stored.id,
        )

        call = matcher.calls[0]

        self.assertEqual(
            call[
                "domain"
            ],
            CanonicalIdentityDomain
            .ENTITY,
        )

        self.assertEqual(
            call[
                "semantic_labels"
            ],
            (
                "same semantic entity",
            ),
        )

        self.assertEqual(
            call[
                "semantic_type"
            ],
            "PERSON",
        )

        candidate = (
            call[
                "candidates"
            ][0]
        )

        self.assertFalse(
            hasattr(
                candidate,
                "canonical_id",
            )
        )

        self.assertEqual(
            candidate.semantic_labels,
            (
                "STORED ENTITY",
                "STORED ALIAS",
            ),
        )

    def test_existing_selection_is_revalidated_by_registry(
        self,
    ):
        stored = make_entity(
            name="STORED ENTITY"
        )

        registry = (
            FakeEntityRegistry(
                (
                    stored,
                )
            )
        )

        reader = (
            CanonicalEntityCatalogReader(
                registry
            )
        )

        result = (
            reader
            .resolve_entity_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .EXISTING
                ),
                (
                    "stored entity",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .EXISTING,
        )

        self.assertEqual(
            registry.get_calls,
            [
                stored.id
            ],
        )

    def test_missing_existing_selection_fails_closed(
        self,
    ):
        stored = make_entity(
            name="STORED ENTITY"
        )

        reader = (
            CanonicalEntityCatalogReader(
                FakeEntityRegistry(
                    (
                        stored,
                    ),
                    missing_on_get=True,
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            reader.resolve_entity_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .EXISTING
                ),
                (
                    "stored entity",
                ),
                "PERSON",
            )

    def test_new_resolution_is_transient_core_identity(
        self,
    ):
        registry = (
            FakeEntityRegistry()
        )

        reader = (
            CanonicalEntityCatalogReader(
                registry
            )
        )

        result = (
            reader
            .resolve_entity_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .NEW
                ),
                (
                    "new entity",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .NEW,
        )

        self.assertIsNotNone(
            result.canonical_id
        )

        UUID(
            result.canonical_id
        )

        self.assertEqual(
            registry.entities,
            (),
        )

        self.assertEqual(
            registry.get_calls,
            [],
        )

    def test_ambiguous_resolution_has_no_identity(
        self,
    ):
        reader = (
            CanonicalEntityCatalogReader(
                FakeEntityRegistry()
            )
        )

        result = (
            reader
            .resolve_entity_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                (
                    "ambiguous entity",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .AMBIGUOUS,
        )

        self.assertIsNone(
            result.canonical_id
        )

    def test_store_list_entities_is_read_only_unfiltered_api(
        self,
    ):
        source = inspect.getsource(
            CanonicalMemoryStore
            .list_entities
        )

        self.assertIn(
            "SELECT",
            source,
        )

        self.assertIn(
            "FROM entities",
            source,
        )

        for forbidden in (
            "INSERT",
            "UPDATE",
            "DELETE",
            "MemoryStatus",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )

        with (
            tempfile
            .TemporaryDirectory()
        ) as temp:
            store = (
                CanonicalMemoryStore(
                    Path(temp)
                    / "memory.sqlite3"
                )
            )

            self.assertEqual(
                store.list_entities(),
                (),
            )

    def test_entity_resolution_has_no_store_or_write_dependency(
        self,
    ):
        source = inspect.getsource(
            entity_resolution_module
        )

        tree = ast.parse(
            source
        )

        imports = []

        calls = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imports.extend(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                if node.module:
                    imports.append(
                        node.module
                    )

            elif isinstance(
                node,
                ast.Call,
            ):
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

        self.assertNotIn(
            "re",
            imports,
        )

        self.assertFalse(
            any(
                item.endswith(
                    "canonical_store"
                )
                for item
                in imports
            )
        )

        self.assertFalse(
            any(
                item.endswith(
                    "entity_bindings"
                )
                for item
                in imports
            )
        )

        for forbidden in (
            "create_entity",
            "commit",
            "begin",
            "transaction",
            "execute",
        ):
            self.assertNotIn(
                forbidden,
                calls,
            )

    def test_no_case_specific_semantic_repairs(
        self,
    ):
        source = inspect.getsource(
            entity_resolution_module
        ).lower()

        for forbidden in (
            "spotify",
            "preferred_color",
            "preference_for_color",
            "idade",
            "esposa",
            "wife",
            "tiago",
            "namespace_hint",
        ):
            self.assertNotIn(
                forbidden,
                source,
            )


if __name__ == "__main__":
    unittest.main()
