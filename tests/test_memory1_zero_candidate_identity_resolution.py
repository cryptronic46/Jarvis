from __future__ import annotations

import unittest

from jarvis_core.memory.enums import (
    Cardinality,
    PropertyKind,
    ValueType,
)

from jarvis_core.memory.property_resolution import (
    CanonicalPropertyCatalogReader,
)

from jarvis_core.memory.resolution import (
    CandidateCatalog,
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    IdentitySelection,
    resolve_with_matcher,
)


class EmptyPropertyRegistry:
    def get_property(
        self,
        property_id: str,
    ):
        return None

    def list_properties(
        self,
        *,
        kind=None,
    ):
        return ()


class RecordingMatcher:
    def __init__(
        self,
        selection: IdentitySelection,
    ) -> None:
        self.selection = selection
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

        return self.selection


class ZeroCandidateIdentityResolutionTests(
    unittest.TestCase
):
    def test_generic_empty_catalog_still_calls_matcher_and_preserves_ambiguous(
        self,
    ) -> None:
        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=0.41,
                selected_handle=None,
            )
        )

        result = resolve_with_matcher(
            catalog=(
                CandidateCatalog(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    candidates=(),
                )
            ),
            matcher=matcher,
            semantic_labels=(
                "person",
            ),
            semantic_type=(
                "person"
            ),
        )

        self.assertEqual(
            len(
                matcher.calls
            ),
            1,
        )

        self.assertEqual(
            matcher.calls[0][
                "candidates"
            ],
            (),
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction.AMBIGUOUS,
        )

        self.assertIsNone(
            result.canonical_id
        )

    def test_generic_empty_catalog_still_respects_matcher_new_selection(
        self,
    ) -> None:
        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .NEW
                ),
                confidence=0.83,
                selected_handle=None,
            )
        )

        result = resolve_with_matcher(
            catalog=(
                CandidateCatalog(
                    domain=(
                        CanonicalIdentityDomain
                        .PROPERTY
                    ),
                    candidates=(),
                )
            ),
            matcher=matcher,
            semantic_labels=(
                "preference",
            ),
            semantic_type=(
                "property"
            ),
        )

        self.assertEqual(
            len(
                matcher.calls
            ),
            1,
        )

        self.assertEqual(
            matcher.calls[0][
                "semantic_labels"
            ],
            (
                "preference",
            ),
        )

        self.assertEqual(
            matcher.calls[0][
                "semantic_type"
            ],
            "property",
        )

        self.assertEqual(
            matcher.calls[0][
                "candidates"
            ],
            (),
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction.NEW,
        )

        self.assertIsNotNone(
            result.canonical_id
        )

        self.assertTrue(
            result.canonical_id.startswith(
                "property_"
            )
        )

    def test_empty_fact_property_catalog_is_structurally_new_without_matcher(
        self,
    ) -> None:
        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=0.20,
                selected_handle=None,
            )
        )

        reader = (
            CanonicalPropertyCatalogReader(
                EmptyPropertyRegistry()
            )
        )

        result = (
            reader.resolve_property_identity(
                matcher=matcher,
                semantic_labels=(
                    "preferred_language",
                ),
                semantic_type=(
                    "property"
                ),
                kind=(
                    PropertyKind.FACT
                ),
                cardinality=(
                    Cardinality
                    .SINGLE_CURRENT
                ),
                value_type=(
                    ValueType.STRING
                ),
            )
        )

        self.assertEqual(
            matcher.calls,
            [],
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction.NEW,
        )

        self.assertIsNotNone(
            result.canonical_id
        )

        self.assertTrue(
            result.canonical_id.startswith(
                "property_"
            )
        )

    def test_empty_relation_property_catalog_is_structurally_new_without_matcher(
        self,
    ) -> None:
        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=0.20,
                selected_handle=None,
            )
        )

        reader = (
            CanonicalPropertyCatalogReader(
                EmptyPropertyRegistry()
            )
        )

        result = (
            reader.resolve_property_identity(
                matcher=matcher,
                semantic_labels=(
                    "relationship",
                ),
                semantic_type=(
                    "relationship"
                ),
                kind=(
                    PropertyKind.RELATION
                ),
                cardinality=(
                    Cardinality
                    .MULTI_CURRENT
                ),
                value_type=None,
            )
        )

        self.assertEqual(
            matcher.calls,
            [],
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction.NEW,
        )

        self.assertIsNotNone(
            result.canonical_id
        )

        self.assertTrue(
            result.canonical_id.startswith(
                "property_"
            )
        )


if __name__ == "__main__":
    unittest.main()
