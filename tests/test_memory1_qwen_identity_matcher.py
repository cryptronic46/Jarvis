from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import unittest

import jarvis_core.memory.qwen_identity_matcher as matcher_module

from jarvis_core.memory.errors import (
    MemoryValidationError,
)

from jarvis_core.memory.qwen_identity_matcher import (
    QwenSemanticIdentityMatcher,
)

from jarvis_core.memory.resolution import (
    CandidateCatalog,
    CanonicalIdentityCandidate,
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    ModelCandidateView,
)


class FakeModel:
    def __init__(
        self,
        response: str = (
            '{"action":"NEW",'
            '"confidence":0.9,'
            '"selected_handle":null}'
        ),
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[
            dict[str, object]
        ] = []

    def generate_constrained_json(
        self,
        *,
        system_prompt: str,
        user_text: str,
        context_json: str,
        schema: dict[str, object],
        num_predict: int | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt":
                    system_prompt,

                "user_text":
                    user_text,

                "context_json":
                    context_json,

                "schema":
                    schema,

                "num_predict":
                    num_predict,
            }
        )

        if self.error is not None:
            raise self.error

        return self.response


def make_response(
    action: str,
    confidence: object,
    selected_handle: object,
) -> str:
    return json.dumps(
        {
            "action":
                action,

            "confidence":
                confidence,

            "selected_handle":
                selected_handle,
        },
        separators=(
            ",",
            ":",
        ),
    )


def entity_candidates() -> tuple[
    ModelCandidateView,
    ...,
]:
    return (
        ModelCandidateView(
            handle="candidate_0",
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            semantic_labels=(
                "Tiago",
            ),
            semantic_type="person",
        ),
        ModelCandidateView(
            handle="candidate_1",
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            semantic_labels=(
                "Ana",
            ),
            semantic_type="person",
        ),
    )


class QwenSemanticIdentityMatcherTests(
    unittest.TestCase
):
    def run_matcher(
        self,
        model: FakeModel,
        *,
        candidates: tuple[
            ModelCandidateView,
            ...,
        ]
        | None = None,
    ):
        matcher = (
            QwenSemanticIdentityMatcher(
                model
            )
        )

        return matcher.select_identity(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            semantic_labels=(
                "Tiago",
            ),
            semantic_type="person",
            candidates=(
                entity_candidates()
                if candidates is None
                else candidates
            ),
        )

    def assert_response_fails(
        self,
        raw_response: str,
    ) -> None:
        model = FakeModel(
            raw_response
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            self.run_matcher(
                model
            )

    def module_source(
        self,
    ) -> str:
        return Path(
            matcher_module.__file__
        ).read_text(
            encoding="utf-8"
        )

    def module_tree(
        self,
    ) -> ast.Module:
        return ast.parse(
            self.module_source()
        )

    def test_protocol_signature(
        self,
    ) -> None:
        signature = inspect.signature(
            QwenSemanticIdentityMatcher
            .select_identity
        )

        self.assertEqual(
            tuple(
                signature.parameters
            ),
            (
                "self",
                "domain",
                "semantic_labels",
                "semantic_type",
                "candidates",
            ),
        )

        for name in (
            "domain",
            "semantic_labels",
            "semantic_type",
            "candidates",
        ):
            self.assertIs(
                signature
                .parameters[
                    name
                ]
                .kind,
                inspect.Parameter
                .KEYWORD_ONLY,
            )

        public_methods = [
            name
            for name, member
            in inspect.getmembers(
                QwenSemanticIdentityMatcher,
                predicate=inspect.isfunction,
            )
            if not name.startswith(
                "_"
            )
        ]

        self.assertEqual(
            public_methods,
            [
                "select_identity",
            ],
        )

    def test_existing_valid(
        self,
    ) -> None:
        result = self.run_matcher(
            FakeModel(
                make_response(
                    "EXISTING",
                    0.95,
                    "candidate_0",
                )
            )
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction
            .EXISTING,
        )

        self.assertEqual(
            result.confidence,
            0.95,
        )

        self.assertEqual(
            result.selected_handle,
            "candidate_0",
        )

    def test_new_valid(
        self,
    ) -> None:
        result = self.run_matcher(
            FakeModel(
                make_response(
                    "NEW",
                    0.9,
                    None,
                )
            )
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction
            .NEW,
        )

        self.assertIsNone(
            result.selected_handle
        )

    def test_ambiguous_valid(
        self,
    ) -> None:
        result = self.run_matcher(
            FakeModel(
                make_response(
                    "AMBIGUOUS",
                    0.4,
                    None,
                )
            )
        )

        self.assertIs(
            result.action,
            IdentityResolutionAction
            .AMBIGUOUS,
        )

        self.assertIsNone(
            result.selected_handle
        )

    def test_malformed_json(
        self,
    ) -> None:
        self.assert_response_fails(
            "{"
        )

    def test_top_level_non_object(
        self,
    ) -> None:
        self.assert_response_fails(
            "[]"
        )

    def test_unknown_action(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "MATCH",
                0.9,
                None,
            )
        )

    def test_bool_confidence(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "NEW",
                True,
                None,
            )
        )

    def test_confidence_below_zero(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "NEW",
                -0.1,
                None,
            )
        )

    def test_confidence_above_one(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "NEW",
                1.1,
                None,
            )
        )

    def test_missing_field(
        self,
    ) -> None:
        self.assert_response_fails(
            (
                '{"action":"NEW",'
                '"confidence":0.9}'
            )
        )

    def test_extra_field(
        self,
    ) -> None:
        self.assert_response_fails(
            (
                '{"action":"NEW",'
                '"confidence":0.9,'
                '"selected_handle":null,'
                '"canonical_id":"forbidden"}'
            )
        )

    def test_existing_without_handle(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "EXISTING",
                0.9,
                None,
            )
        )

    def test_new_with_handle(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "NEW",
                0.9,
                "candidate_0",
            )
        )

    def test_ambiguous_with_handle(
        self,
    ) -> None:
        self.assert_response_fails(
            make_response(
                "AMBIGUOUS",
                0.4,
                "candidate_0",
            )
        )

    def test_selected_handle_wrong_type(
        self,
    ) -> None:
        self.assert_response_fails(
            (
                '{"action":"EXISTING",'
                '"confidence":0.9,'
                '"selected_handle":7}'
            )
        )

    def test_model_exception_fail_closed(
        self,
    ) -> None:
        failure = RuntimeError(
            "model failed"
        )

        model = FakeModel(
            error=failure
        )

        with self.assertRaises(
            MemoryValidationError
        ) as caught:
            self.run_matcher(
                model
            )

        self.assertIs(
            caught.exception.__cause__,
            failure,
        )

    def test_canonical_ids_not_exposed(
        self,
    ) -> None:
        secret_id = (
            "opaque-canonical-secret"
        )

        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(
                CanonicalIdentityCandidate(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    canonical_id=(
                        secret_id
                    ),
                    semantic_labels=(
                        "Tiago",
                    ),
                    semantic_type="person",
                ),
            ),
        )

        model = FakeModel(
            make_response(
                "EXISTING",
                0.9,
                "candidate_0",
            )
        )

        self.run_matcher(
            model,
            candidates=(
                catalog.model_views()
            ),
        )

        self.assertEqual(
            len(
                model.calls
            ),
            1,
        )

        call = model.calls[0]

        self.assertNotIn(
            secret_id,
            str(
                call[
                    "context_json"
                ]
            ),
        )

        self.assertNotIn(
            secret_id,
            str(
                call[
                    "system_prompt"
                ]
            ),
        )

        self.assertNotIn(
            secret_id,
            str(
                call[
                    "user_text"
                ]
            ),
        )

    def test_raw_owner_turn_not_available(
        self,
    ) -> None:
        signature = inspect.signature(
            QwenSemanticIdentityMatcher
            .select_identity
        )

        forbidden = {
            "raw_text",
            "user_text",
            "text",
            "message",
            "prompt",
        }

        self.assertTrue(
            forbidden.isdisjoint(
                signature.parameters
            )
        )

        model = FakeModel()

        self.run_matcher(
            model
        )

        self.assertEqual(
            model.calls[0][
                "user_text"
            ],
            (
                "Select the identity resolution "
                "action from the structured context."
            ),
        )

    def test_candidate_fields_exact(
        self,
    ) -> None:
        model = FakeModel()

        self.run_matcher(
            model
        )

        context = json.loads(
            str(
                model.calls[0][
                    "context_json"
                ]
            )
        )

        self.assertEqual(
            set(
                context
            ),
            {
                "domain",
                "semantic_labels",
                "semantic_type",
                "candidates",
            },
        )

        for candidate in context[
            "candidates"
        ]:
            self.assertEqual(
                set(
                    candidate
                ),
                {
                    "handle",
                    "domain",
                    "semantic_labels",
                    "semantic_type",
                },
            )

    def test_one_model_call(
        self,
    ) -> None:
        model = FakeModel()

        self.run_matcher(
            model
        )

        self.assertEqual(
            len(
                model.calls
            ),
            1,
        )

    def test_unknown_handle_rejected_by_catalog(
        self,
    ) -> None:
        catalog = CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=(
                CanonicalIdentityCandidate(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    canonical_id="opaque-id",
                    semantic_labels=(
                        "Tiago",
                    ),
                    semantic_type="person",
                ),
            ),
        )

        model = FakeModel(
            make_response(
                "EXISTING",
                0.9,
                "candidate_999",
            )
        )

        selection = self.run_matcher(
            model,
            candidates=(
                catalog.model_views()
            ),
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            catalog.resolve_selection(
                selection
            )

    def test_no_store_access(
        self,
    ) -> None:
        tree = self.module_tree()

        modules = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                modules.extend(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                modules.append(
                    node.module
                    or ""
                )

        self.assertFalse(
            any(
                "canonical_store"
                in module
                for module
                in modules
            )
        )

    def test_no_transaction_access(
        self,
    ) -> None:
        identifiers = []

        for node in ast.walk(
            self.module_tree()
        ):
            if isinstance(
                node,
                ast.Name,
            ):
                identifiers.append(
                    node.id
                )

            elif isinstance(
                node,
                ast.Attribute,
            ):
                identifiers.append(
                    node.attr
                )

        self.assertFalse(
            any(
                "transaction"
                in name.casefold()
                for name
                in identifiers
            )
        )

    def test_no_id_minting(
        self,
    ) -> None:
        identifiers = []

        for node in ast.walk(
            self.module_tree()
        ):
            if isinstance(
                node,
                ast.Name,
            ):
                identifiers.append(
                    node.id
                )

            elif isinstance(
                node,
                ast.Attribute,
            ):
                identifiers.append(
                    node.attr
                )

        self.assertNotIn(
            "new_memory_id",
            identifiers,
        )

        self.assertNotIn(
            "_mint_identity",
            identifiers,
        )

    def test_no_regex_semantics(
        self,
    ) -> None:
        tree = self.module_tree()

        imported = []

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imported.extend(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                imported.append(
                    node.module
                    or ""
                )

        self.assertNotIn(
            "re",
            imported,
        )

        self.assertNotIn(
            "regex",
            self.module_source()
            .casefold(),
        )

    def test_no_synonym_table(
        self,
    ) -> None:
        self.assertNotIn(
            "synonym",
            self.module_source()
            .casefold(),
        )

    def test_no_phrase_specific_rules(
        self,
    ) -> None:
        source = self.module_source()

        self.assertNotIn(
            "Tiago",
            source,
        )

        self.assertNotIn(
            "Ana",
            source,
        )

        violations = []

        for node in ast.walk(
            ast.parse(
                source
            )
        ):
            if not isinstance(
                node,
                ast.Compare,
            ):
                continue

            expression = ast.unparse(
                node
            )

            if not (
                "semantic_labels"
                in expression
                or "semantic_type"
                in expression
            ):
                continue

            constants = [
                child.value
                for child
                in ast.walk(
                    node
                )
                if (
                    isinstance(
                        child,
                        ast.Constant,
                    )
                    and isinstance(
                        child.value,
                        str,
                    )
                )
            ]

            if constants:
                violations.append(
                    expression
                )

        self.assertEqual(
            violations,
            [],
        )


if __name__ == "__main__":
    unittest.main()
