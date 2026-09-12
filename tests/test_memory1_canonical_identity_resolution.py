from __future__ import annotations

from dataclasses import (
    asdict,
    fields,
)
import ast
import json
from pathlib import Path
import unittest
import uuid

from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.resolution import (
    PROPERTY_ID_PREFIX,
    CanonicalIdentityCandidate,
    CanonicalIdentityDomain,
    CandidateCatalog,
    IdentityResolutionAction,
    IdentitySelection,
    ModelCandidateView,
    resolve_with_matcher,
)


class RecordingMatcher:
    def __init__(
        self,
        selection,
    ):
        self.selection = selection
        self.calls = []

    def select_identity(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        return self.selection


class Memory1CanonicalIdentityResolutionTests(
    unittest.TestCase
):
    def entity_candidate(
        self,
        canonical_id,
        label,
    ):
        return CanonicalIdentityCandidate(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            canonical_id=canonical_id,
            semantic_labels=(
                label,
            ),
            semantic_type=(
                "semantic_entity"
            ),
        )

    def property_candidate(
        self,
        canonical_id,
        label,
    ):
        return CanonicalIdentityCandidate(
            domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            canonical_id=canonical_id,
            semantic_labels=(
                label,
            ),
            semantic_type=(
                "semantic_property"
            ),
        )

    def test_model_candidate_view_has_no_canonical_id_field(
        self,
    ):
        names = {
            item.name
            for item
            in fields(
                ModelCandidateView
            )
        }

        self.assertNotIn(
            "canonical_id",
            names,
        )

    def test_catalog_hides_canonical_ids_from_matcher(
        self,
    ):
        secret_a = str(
            uuid.uuid4()
        )

        secret_b = str(
            uuid.uuid4()
        )

        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(
                self.entity_candidate(
                    secret_a,
                    "semantic_alpha",
                ),
                self.entity_candidate(
                    secret_b,
                    "semantic_beta",
                ),
            ),
        )

        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .EXISTING
                ),
                confidence=0.9,
                selected_handle=(
                    "candidate_0001"
                ),
            )
        )

        result = resolve_with_matcher(
            catalog=catalog,
            matcher=matcher,
            semantic_labels=(
                "semantic_beta_variant",
            ),
            semantic_type=(
                "semantic_entity"
            ),
        )

        payload = json.dumps(
            [
                asdict(
                    item
                )
                for item
                in matcher.calls[0][
                    "candidates"
                ]
            ],
            sort_keys=True,
        )

        self.assertNotIn(
            secret_a,
            payload,
        )

        self.assertNotIn(
            secret_b,
            payload,
        )

        self.assertEqual(
            result.canonical_id,
            secret_b,
        )

    def test_existing_selection_is_mapped_inside_core(
        self,
    ):
        secret = str(
            uuid.uuid4()
        )

        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(
                self.entity_candidate(
                    secret,
                    "semantic_alpha",
                ),
            ),
        )

        result = (
            catalog.resolve_selection(
                IdentitySelection(
                    action=(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    confidence=1.0,
                    selected_handle=(
                        "candidate_0000"
                    ),
                )
            )
        )

        self.assertEqual(
            result.canonical_id,
            secret,
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .EXISTING,
        )

    def test_unknown_candidate_handle_fails_closed(
        self,
    ):
        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(
                self.entity_candidate(
                    str(
                        uuid.uuid4()
                    ),
                    "semantic_alpha",
                ),
            ),
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            catalog.resolve_selection(
                IdentitySelection(
                    action=(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    confidence=0.9,
                    selected_handle=(
                        "candidate_9999"
                    ),
                )
            )

    def test_new_entity_identity_is_core_minted_uuid(
        self,
    ):
        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(),
        )

        result = (
            catalog.resolve_selection(
                IdentitySelection(
                    action=(
                        IdentityResolutionAction
                        .NEW
                    ),
                    confidence=0.9,
                )
            )
        )

        parsed = uuid.UUID(
            result.canonical_id
        )

        self.assertEqual(
            str(
                parsed
            ),
            result.canonical_id,
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .NEW,
        )

    def test_new_property_identity_is_core_minted_predicate(
        self,
    ):
        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            candidates=(),
        )

        result = (
            catalog.resolve_selection(
                IdentitySelection(
                    action=(
                        IdentityResolutionAction
                        .NEW
                    ),
                    confidence=0.91,
                )
            )
        )

        self.assertTrue(
            result.canonical_id.startswith(
                PROPERTY_ID_PREFIX
            )
        )

        raw_uuid = (
            result.canonical_id[
                len(
                    PROPERTY_ID_PREFIX
                ):
            ]
        )

        parsed = uuid.UUID(
            hex=raw_uuid
        )

        self.assertEqual(
            parsed.hex,
            raw_uuid,
        )

    def test_ambiguous_resolution_carries_no_identity(
        self,
    ):
        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(),
        )

        result = (
            catalog.resolve_selection(
                IdentitySelection(
                    action=(
                        IdentityResolutionAction
                        .AMBIGUOUS
                    ),
                    confidence=0.5,
                )
            )
        )

        self.assertIsNone(
            result.canonical_id
        )

        self.assertEqual(
            result.action,
            IdentityResolutionAction
            .AMBIGUOUS,
        )

    def test_existing_selection_requires_handle(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .EXISTING
                ),
                confidence=0.8,
            )

    def test_new_selection_cannot_smuggle_handle(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .NEW
                ),
                confidence=0.8,
                selected_handle=(
                    "candidate_0000"
                ),
            )

    def test_ambiguous_selection_cannot_smuggle_handle(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=0.8,
                selected_handle=(
                    "candidate_0000"
                ),
            )

    def test_catalog_rejects_duplicate_canonical_ids(
        self,
    ):
        repeated = str(
            uuid.uuid4()
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            CandidateCatalog(
                domain=(
                    CanonicalIdentityDomain
                    .ENTITY
                ),
                candidates=(
                    self.entity_candidate(
                        repeated,
                        "semantic_alpha",
                    ),
                    self.entity_candidate(
                        repeated,
                        "semantic_beta",
                    ),
                ),
            )

    def test_catalog_rejects_cross_domain_candidates(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            CandidateCatalog(
                domain=(
                    CanonicalIdentityDomain
                    .ENTITY
                ),
                candidates=(
                    self.property_candidate(
                        (
                            PROPERTY_ID_PREFIX
                            + uuid.uuid4().hex
                        ),
                        "semantic_alpha",
                    ),
                ),
            )

    def test_property_candidate_requires_technical_predicate(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            CanonicalIdentityCandidate(
                domain=(
                    CanonicalIdentityDomain
                    .PROPERTY
                ),
                canonical_id=(
                    "not a valid predicate"
                ),
                semantic_labels=(
                    "semantic_alpha",
                ),
                semantic_type=(
                    "semantic_property"
                ),
            )

    def test_semantic_labels_are_passed_without_phrase_mapping(
        self,
    ):
        labels = (
            "semantic_alpha_variant",
            "semantic_beta_variant",
        )

        matcher = RecordingMatcher(
            IdentitySelection(
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=0.4,
            )
        )

        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            candidates=(),
        )

        resolve_with_matcher(
            catalog=catalog,
            matcher=matcher,
            semantic_labels=labels,
            semantic_type=(
                "semantic_property"
            ),
        )

        self.assertEqual(
            matcher.calls[0][
                "semantic_labels"
            ],
            labels,
        )

    def test_resolution_module_has_no_canonical_write_dependency(
        self,
    ):
        source = Path(
            "jarvis_core/memory/resolution.py"
        ).read_text(
            encoding="utf-8"
        )

        forbidden = (
            "CanonicalMemoryStore",
            "CanonicalMemoryTransaction",
            "begin_transaction",
            "create_fact",
            "create_relation",
            "append_episode",
            "commit(",
            "MemoryCommitReceipt",
        )

        for token in forbidden:
            self.assertNotIn(
                token,
                source,
            )

    def test_resolution_module_has_no_language_regex(
        self,
    ):
        source = Path(
            "jarvis_core/memory/resolution.py"
        ).read_text(
            encoding="utf-8"
        )

        tree = ast.parse(
            source
        )

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                for alias in node.names:
                    self.assertNotIn(
                        alias.name
                        .split(".", 1)[0],
                        {
                            "re",
                            "regex",
                        },
                    )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                root = (
                    (
                        node.module
                        or ""
                    )
                    .split(".", 1)[0]
                )

                self.assertNotIn(
                    root,
                    {
                        "re",
                        "regex",
                    },
                )

    def test_production_source_has_no_case_specific_repairs(
        self,
    ):
        source = Path(
            "jarvis_core/memory/resolution.py"
        ).read_text(
            encoding="utf-8"
        ).lower()

        forbidden = (
            "spotify",
            "marta",
            "preferred_color",
            "favorite_color",
            "has_sister",
            "has_sibling",
            "age_fact",
            "cor_preferida",
        )

        for token in forbidden:
            self.assertNotIn(
                token,
                source,
            )


if __name__ == "__main__":
    unittest.main()
