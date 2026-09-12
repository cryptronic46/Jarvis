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

import jarvis_core.memory.entity_resolution as entity_resolution_module

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
from jarvis_core.memory.entity_resolution import (
    CanonicalEntityCatalogReader,
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    IdentitySelection,
)


def make_entity(
    *,
    canonical_name="Example Person",
    aliases=("Example",),
    entity_type="PERSON",
    status=MemoryStatus.ACTIVE,
):
    entity = Entity.create(
        namespace=(
            MemoryNamespace.PERSON
        ),
        canonical_name=canonical_name,
        entity_type=entity_type,
        aliases=aliases,
    )

    if (
        entity.status
        is status
    ):
        return entity

    return replace(
        entity,
        status=status,
    )


class FakeRegistry:
    def __init__(
        self,
        entities=(),
        *,
        get_override_marker=None,
    ):
        self.entities = tuple(
            entities
        )

        self.get_override_marker = (
            get_override_marker
        )

        self.list_calls = 0
        self.get_calls = []

    def list_entities(
        self,
    ):
        self.list_calls += 1
        return self.entities

    def get_entity(
        self,
        entity_id,
    ):
        self.get_calls.append(
            entity_id
        )

        if (
            self.get_override_marker
            is not None
        ):
            return (
                self.get_override_marker
            )

        for entity in (
            self.entities
        ):
            if (
                entity.id
                == entity_id
            ):
                return entity

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


class Memory1RecallEntityResolutionTests(
    unittest.TestCase,
):
    def test_result_is_immutable_and_retrieval_only(
        self,
    ):
        result = RecallEntityResolution(
            action=(
                RecallEntityResolutionAction
                .MISS
            ),
            confidence=0.8,
            canonical_id=None,
        )

        self.assertEqual(
            tuple(
                result
                .__dataclass_fields__
            ),
            (
                "action",
                "confidence",
                "canonical_id",
            ),
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            result.canonical_id = (
                "invalid"
            )

    def test_miss_and_ambiguous_never_carry_identity(
        self,
    ):
        for action in (
            RecallEntityResolutionAction
            .MISS,
            RecallEntityResolutionAction
            .AMBIGUOUS,
        ):
            with self.subTest(
                action=action
            ):
                with self.assertRaises(
                    MemoryValidationError
                ):
                    RecallEntityResolution(
                        action=action,
                        confidence=0.9,
                        canonical_id=(
                            "not-allowed"
                        ),
                    )

    def test_existing_requires_identity(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            RecallEntityResolution(
                action=(
                    RecallEntityResolutionAction
                    .EXISTING
                ),
                confidence=0.9,
                canonical_id=None,
            )

    def test_recall_api_accepts_only_semantic_identity_input(
        self,
    ):
        signature = inspect.signature(
            CanonicalEntityCatalogReader
            .resolve_recall_entity_identity
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
            ),
        )

        for forbidden in (
            "canonical_id",
            "canonical_name",
            "aliases",
            "namespace_hint",
            "namespace",
        ):
            self.assertNotIn(
                forbidden,
                signature.parameters,
            )

    def test_existing_entity_resolves_from_active_catalog(
        self,
    ):
        stored = make_entity(
            canonical_name=(
                "Example Person"
            ),
            aliases=(
                "Example",
                "Example Person Alias",
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
            CanonicalEntityCatalogReader(
                registry
            )
            .resolve_recall_entity_identity(
                matcher,
                (
                    "the example person",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.action,
            RecallEntityResolutionAction
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
            .ENTITY,
        )

        self.assertEqual(
            call[
                "semantic_labels"
            ],
            (
                "the example person",
            ),
        )

        self.assertEqual(
            call[
                "semantic_type"
            ],
            "PERSON",
        )

        self.assertEqual(
            len(
                call[
                    "candidates"
                ]
            ),
            1,
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

        self.assertIn(
            "Example Person",
            candidate
            .semantic_labels,
        )

        self.assertIn(
            "Example",
            candidate
            .semantic_labels,
        )

    def test_new_selection_becomes_miss_without_uuid_mint(
        self,
    ):
        reader = (
            CanonicalEntityCatalogReader(
                FakeRegistry()
            )
        )

        matcher = RecordingMatcher(
            IdentityResolutionAction
            .NEW,
            confidence=0.71,
        )

        with patch(
            "jarvis_core.memory."
            "resolution._mint_identity",
            side_effect=AssertionError(
                "RECALL must not mint "
                "entity identity"
            ),
        ):
            result = (
                reader
                .resolve_recall_entity_identity(
                    matcher,
                    (
                        "unknown person",
                    ),
                    "PERSON",
                )
            )

        self.assertEqual(
            result.action,
            RecallEntityResolutionAction
            .MISS,
        )

        self.assertIsNone(
            result.canonical_id
        )

        self.assertEqual(
            result.confidence,
            0.71,
        )

    def test_ambiguous_selection_remains_explicit(
        self,
    ):
        result = (
            CanonicalEntityCatalogReader(
                FakeRegistry()
            )
            .resolve_recall_entity_identity(
                RecordingMatcher(
                    IdentityResolutionAction
                    .AMBIGUOUS,
                    confidence=0.55,
                ),
                (
                    "ambiguous person",
                ),
                "PERSON",
            )
        )

        self.assertEqual(
            result.action,
            RecallEntityResolutionAction
            .AMBIGUOUS,
        )

        self.assertIsNone(
            result.canonical_id
        )

        self.assertEqual(
            result.confidence,
            0.55,
        )

    def test_existing_entity_disappearing_from_registry_fails_closed(
        self,
    ):
        stored = make_entity()

        class DisappearingRegistry(
            FakeRegistry
        ):
            def get_entity(
                self,
                entity_id,
            ):
                self.get_calls.append(
                    entity_id
                )

                return None

        reader = (
            CanonicalEntityCatalogReader(
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
                .resolve_recall_entity_identity(
                    RecordingMatcher(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    (
                        "example person",
                    ),
                    "PERSON",
                )
            )

    def test_inactive_existing_entity_fails_closed(
        self,
    ):
        active = make_entity()

        inactive = replace(
            active,
            status=(
                MemoryStatus.RETRACTED
            ),
        )

        reader = (
            CanonicalEntityCatalogReader(
                FakeRegistry(
                    (
                        active,
                    ),
                    get_override_marker=(
                        inactive
                    ),
                )
            )
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            (
                reader
                .resolve_recall_entity_identity(
                    RecordingMatcher(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    (
                        "example person",
                    ),
                    "PERSON",
                )
            )

    def test_recall_validation_has_no_namespace_guess(
        self,
    ):
        stored = make_entity()

        reader = (
            CanonicalEntityCatalogReader(
                FakeRegistry(
                    (
                        stored,
                    )
                )
            )
        )

        result = (
            reader
            .validate_existing_recall_entity_contract(
                stored.id
            )
        )

        self.assertEqual(
            result.id,
            stored.id,
        )

        signature = inspect.signature(
            CanonicalEntityCatalogReader
            .validate_existing_recall_entity_contract
        )

        for forbidden in (
            "namespace",
            "namespace_hint",
            "canonical_name",
            "aliases",
        ):
            self.assertNotIn(
                forbidden,
                signature.parameters,
            )

    def test_recall_resolver_has_no_write_or_language_repair_dependency(
        self,
    ):
        source = inspect.getsource(
            CanonicalEntityCatalogReader
            .resolve_recall_entity_identity
        )

        tree = ast.parse(
            textwrap.dedent(
                source
            )
        )

        calls = []

        for node in ast.walk(tree):
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
            "create_entity",
            "commit",
            "transaction",
            "execute",
            "_mint_identity",
        ):
            self.assertNotIn(
                forbidden,
                calls,
            )

        module_source = (
            inspect.getsource(
                entity_resolution_module
            )
            .lower()
        )

        for forbidden in (
            "spotify",
            "preferred_color",
            "preference_for_color",
            "idade",
            "esposa",
        ):
            self.assertNotIn(
                forbidden,
                module_source,
            )


if __name__ == "__main__":
    unittest.main()
