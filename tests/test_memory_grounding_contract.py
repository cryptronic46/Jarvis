import inspect
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.memory_grounding import (
    MEMORY_GROUNDING_REGISTRY,
    MEMORY_SCOPE_NAMES,
    OWNER_PERSONAL_MODEL_KINDS,
    MemoryBackend,
    MemoryGroundingExecutor,
    require_memory_grounding_scope,
)
from jarvis_core.services.memory_index import (
    UnifiedMemoryIndex,
)
from jarvis_core.services.memory_retrieval import (
    MemoryRetrievalCoordinator,
)
from jarvis_core.services.semantic_request import (
    StructuredRequest,
)
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class _FakeBackend:
    def search(
        self,
        query,
        *,
        limit=10,
        sources=None,
        kinds=None,
    ):
        return {
            "ok": True,
            "results": [],
        }

    def recent_records(
        self,
        *,
        limit=10,
        sources=None,
        kinds=None,
    ):
        return {
            "ok": True,
            "results": [],
        }


class _LooseBackend:
    """Backend that deliberately ignores requested filters."""

    def __init__(
        self,
        rows,
    ):
        self.rows = [
            dict(
                row
            )
            for row
            in rows
        ]

        self.search_calls = []
        self.recent_calls = []

    def search(
        self,
        query,
        *,
        limit=10,
        sources=None,
        kinds=None,
    ):
        self.search_calls.append({
            "query":
                query,
            "limit":
                limit,
            "sources":
                tuple(
                    sources
                    or ()
                ),
            "kinds":
                tuple(
                    kinds
                    or ()
                ),
        })

        return {
            "ok": True,
            "results":
                self.rows[
                    :limit
                ],
        }

    def recent_records(
        self,
        *,
        limit=10,
        sources=None,
        kinds=None,
    ):
        self.recent_calls.append({
            "limit":
                limit,
            "sources":
                tuple(
                    sources
                    or ()
                ),
            "kinds":
                tuple(
                    kinds
                    or ()
                ),
        })

        return {
            "ok": True,
            "results":
                self.rows[
                    :limit
                ],
        }


class MemoryGroundingContractTests(
    unittest.TestCase
):
    def test_registry_contains_every_declared_scope(
        self,
    ):
        self.assertEqual(
            MEMORY_GROUNDING_REGISTRY.names,
            MEMORY_SCOPE_NAMES,
        )

        self.assertGreaterEqual(
            len(
                MEMORY_SCOPE_NAMES
            ),
            16,
        )

    def test_owner_learning_scope_is_structurally_isolated(
        self,
    ):
        scope = require_memory_grounding_scope(
            "OWNER_LEARNING_GOALS"
        )

        self.assertEqual(
            scope.subject,
            "OWNER",
        )

        self.assertEqual(
            len(
                scope.lanes
            ),
            1,
        )

        lane = scope.lanes[
            0
        ]

        self.assertEqual(
            lane.sources,
            (
                "personal_model",
            ),
        )

        self.assertEqual(
            lane.kinds,
            (
                "owner_learning_goals",
            ),
        )

        self.assertNotIn(
            "jarvis_learning_goals",
            lane.kinds,
        )

        self.assertNotIn(
            "jarvis_directives",
            lane.kinds,
        )

    def test_jarvis_learning_scope_is_structurally_isolated(
        self,
    ):
        scope = require_memory_grounding_scope(
            "JARVIS_LEARNING_GOALS"
        )

        self.assertEqual(
            scope.subject,
            "JARVIS",
        )

        lane = scope.lanes[
            0
        ]

        self.assertEqual(
            lane.kinds,
            (
                "jarvis_learning_goals",
            ),
        )

        self.assertNotIn(
            "owner_learning_goals",
            lane.kinds,
        )

    def test_owner_personal_model_excludes_jarvis_buckets(
        self,
    ):
        scope = require_memory_grounding_scope(
            "OWNER_PERSONAL_MODEL"
        )

        lane = scope.lanes[
            0
        ]

        self.assertEqual(
            lane.kinds,
            OWNER_PERSONAL_MODEL_KINDS,
        )

        self.assertNotIn(
            "jarvis_learning_goals",
            lane.kinds,
        )

        self.assertNotIn(
            "jarvis_directives",
            lane.kinds,
        )

    def test_all_owner_scopes_exclude_jarvis_model_kinds(
        self,
    ):
        forbidden = {
            "jarvis_learning_goals",
            "jarvis_directives",
        }

        for scope in (
            MEMORY_GROUNDING_REGISTRY
            .all()
        ):
            if (
                scope.subject
                != "OWNER"
            ):
                continue

            for lane in scope.lanes:
                if (
                    lane.kinds
                    is None
                ):
                    continue

                with self.subTest(
                    scope=scope.name,
                    lane=lane.name,
                ):
                    self.assertTrue(
                        forbidden.isdisjoint(
                            lane.kinds
                        )
                    )

    def test_full_name_scope_requires_explicit_validator(
        self,
    ):
        scope = require_memory_grounding_scope(
            "OWNER_FULL_NAME"
        )

        self.assertEqual(
            scope.subject,
            "OWNER",
        )

        self.assertEqual(
            scope.missing_reason,
            "owner_full_name_not_stored",
        )

        self.assertTrue(
            all(
                lane.validator
                == "explicit_owner_full_name"
                for lane
                in scope.lanes
            )
        )

    def test_relationship_scope_requires_explicit_validator(
        self,
    ):
        scope = require_memory_grounding_scope(
            "OWNER_RELATIONSHIP"
        )

        self.assertTrue(
            all(
                lane.validator
                == "explicit_owner_relationship"
                for lane
                in scope.lanes
            )
        )

    def test_structured_request_carries_immutable_memory_scope(
        self,
    ):
        request = StructuredRequest(
            raw_text=
                "Qual ? o meu nome completo?",
            effective_text=
                "Qual ? o meu nome completo?",
            intent=
                "GENERAL_CONVERSATION",
            domain=
                "owner_memory",
            subject=
                "OWNER",
            action=
                "discuss_owner_context",
            confidence=
                0.95,
            memory_scope=
                "owner_full_name",
        )

        self.assertEqual(
            request.memory_scope,
            "OWNER_FULL_NAME",
        )

        self.assertEqual(
            request.as_dict()[
                "memory_scope"
            ],
            "OWNER_FULL_NAME",
        )

        with self.assertRaises(
            AttributeError
        ):
            request.memory_scope = (
                "OWNER_PROFILE"
            )

    def test_invalid_memory_scope_fails_closed(
        self,
    ):
        with self.assertRaises(
            ValueError
        ):
            StructuredRequest(
                raw_text="x",
                effective_text="x",
                intent=
                    "GENERAL_CONVERSATION",
                domain=
                    "owner_memory",
                subject="OWNER",
                confidence=0.95,
                memory_scope=
                    "OWNER_DOES_NOT_EXIST",
            )

    def test_backend_protocol_surface_has_source_and_kind_filters(
        self,
    ):
        search_parameters = (
            inspect.signature(
                MemoryBackend.search
            ).parameters
        )

        recent_parameters = (
            inspect.signature(
                MemoryBackend.recent_records
            ).parameters
        )

        index_search_parameters = (
            inspect.signature(
                UnifiedMemoryIndex.search
            ).parameters
        )

        index_recent_parameters = (
            inspect.signature(
                UnifiedMemoryIndex
                .recent_records
            ).parameters
        )

        for parameters in (
            search_parameters,
            recent_parameters,
            index_search_parameters,
            index_recent_parameters,
        ):
            self.assertIn(
                "sources",
                parameters,
            )

            self.assertIn(
                "kinds",
                parameters,
            )

    def test_coordinator_accepts_backend_protocol_without_behavior_change(
        self,
    ):
        backend = (
            _FakeBackend()
        )

        coordinator = (
            MemoryRetrievalCoordinator(
                backend
            )
        )

        self.assertIs(
            coordinator.backend,
            backend,
        )

        self.assertIs(
            coordinator.index,
            backend,
        )

    def test_real_fts_backend_filters_by_kind_before_rerank(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            path = (
                Path(td)
                / "memory.sqlite3"
            )

            index = (
                UnifiedMemoryIndex(
                    path
                )
            )

            conn = index._connect(
                path
            )

            try:
                index._initialize_schema(
                    conn
                )

                index._insert(
                    conn,
                    source=
                        "personal_model",
                    source_id=
                        "owner-learning",
                    kind=
                        "owner_learning_goals",
                    title=
                        "OWNER learning",
                    text=
                        "redes",
                    tags=
                        "owner learning redes",
                )

                index._insert(
                    conn,
                    source=
                        "personal_model",
                    source_id=
                        "jarvis-learning",
                    kind=
                        "jarvis_learning_goals",
                    title=
                        "JARVIS learning",
                    text=
                        "redes",
                    tags=
                        "jarvis learning redes",
                )

                conn.commit()

            finally:
                conn.close()

            result = index.search(
                "redes",
                limit=10,
                sources=(
                    "personal_model",
                ),
                kinds=(
                    "owner_learning_goals",
                ),
            )

            self.assertTrue(
                result.get(
                    "ok"
                )
            )

            self.assertEqual(
                result.get(
                    "kinds"
                ),
                [
                    "owner_learning_goals",
                ],
            )

            rows = list(
                result.get(
                    "results"
                )
                or []
            )

            self.assertEqual(
                len(
                    rows
                ),
                1,
            )

            self.assertEqual(
                rows[0].get(
                    "kind"
                ),
                "owner_learning_goals",
            )


    def test_semantic_owner_queries_receive_memory_scopes(
        self,
    ):
        cases = (
            (
                "Jarvis, como me chamo?",
                "OWNER_PROFILE",
            ),
            (
                "Jarvis, qual \u00e9 o meu nome completo?",
                "OWNER_FULL_NAME",
            ),
            (
                "Jarvis, o que sabes realmente sobre mim?",
                "OWNER_FACTUAL_SUMMARY",
            ),
            (
                "Jarvis, mostra a minha mem\u00f3ria.",
                "OWNER_MEMORY_OVERVIEW",
            ),
            (
                "Jarvis, que objetivos tenho?",
                "OWNER_GOALS",
            ),
            (
                (
                    "Jarvis, quais s\u00e3o os meus "
                    "objetivos de aprendizagem?"
                ),
                "OWNER_LEARNING_GOALS",
            ),
            (
                "Jarvis, onde moro?",
                "OWNER_HOME",
            ),
            (
                (
                    "Jarvis, que modelo pessoal "
                    "tens de mim?"
                ),
                "OWNER_PERSONAL_MODEL",
            ),
            (
                "Jarvis, o que pensas de mim?",
                "OWNER_VIEW",
            ),
            (
                "Jarvis, quem \u00e9 a minha mulher?",
                "OWNER_RELATIONSHIP",
            ),
            (
                "Jarvis, qual era o c\u00f3digo de teste?",
                "OWNER_EXPLICIT_FACT",
            ),
        )

        for text, expected in cases:
            with self.subTest(
                text=text
            ):
                request = (
                    resolve_semantic_request(
                        text
                    )
                )

                self.assertEqual(
                    request.subject,
                    "OWNER",
                )

                self.assertEqual(
                    request.memory_scope,
                    expected,
                )

                self.assertEqual(
                    request.action,
                    "discuss_owner_context",
                )

    def test_recent_explicit_recall_receives_temporal_scope(
        self,
    ):
        request = (
            resolve_semantic_request(
                (
                    "Jarvis, recorda o que te pedi "
                    "para guardar na mem\u00f3ria local "
                    "h\u00e1 pouco."
                )
            )
        )

        self.assertEqual(
            request.memory_scope,
            "OWNER_RECENT_EXPLICIT",
        )

        self.assertEqual(
            request.action,
            "recall_recent_explicit_memory",
        )

    def test_jarvis_learning_query_receives_jarvis_scope(
        self,
    ):
        request = (
            resolve_semantic_request(
                (
                    "Jarvis, quais s\u00e3o os teus "
                    "objetivos de aprendizagem?"
                )
            )
        )

        self.assertEqual(
            request.intent,
            "IDENTITY_DIALOGUE",
        )

        self.assertEqual(
            request.subject,
            "JARVIS",
        )

        self.assertEqual(
            request.action,
            "discuss_identity",
        )

        self.assertEqual(
            request.memory_scope,
            "JARVIS_LEARNING_GOALS",
        )

    def test_scope_assignment_does_not_change_operational_semantics(
        self,
    ):
        request = (
            resolve_semantic_request(
                "Jarvis, abre o Brave."
            )
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertIsNone(
            request.memory_scope
        )


    def test_executor_reapplies_source_and_kind_boundaries(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "owner-learning",
                "source":
                    "personal_model",
                "kind":
                    "owner_learning_goals",
                "text":
                    "redes",
            },
            {
                "id":
                    "jarvis-learning",
                "source":
                    "personal_model",
                "kind":
                    "jarvis_learning_goals",
                "text":
                    "redes",
            },
            {
                "id":
                    "wrong-source",
                "source":
                    "explicit_fact",
                "kind":
                    "owner_learning_goals",
                "text":
                    "redes",
            },
        ])

        result = (
            MemoryGroundingExecutor(
                backend
            ).execute(
                "OWNER_LEARNING_GOALS",
                (
                    "Jarvis, quais s\\u00e3o os "
                    "meus objetivos de aprendizagem?"
                ),
            )
        )

        self.assertTrue(
            result.get(
                "retrieved"
            )
        )

        rows = list(
            result.get(
                "results"
            )
            or []
        )

        self.assertEqual(
            len(
                rows
            ),
            1,
        )

        self.assertEqual(
            rows[0].get(
                "id"
            ),
            "owner-learning",
        )

        self.assertEqual(
            rows[0].get(
                "kind"
            ),
            "owner_learning_goals",
        )

    def test_executor_rejects_partial_name_and_wife_full_name(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "owner-profile",
                "source":
                    "user_profile",
                "kind":
                    "profile",
                "text":
                    "name=Tiago",
            },
            {
                "id":
                    "wife-name",
                "source":
                    "explicit_fact",
                "kind":
                    "user_explicit",
                "text":
                    (
                        "o nome completo da minha "
                        "mulher e Ana Isa "
                        "Guimaraes Lopes"
                    ),
            },
        ])

        result = (
            MemoryGroundingExecutor(
                backend
            ).execute(
                "OWNER_FULL_NAME",
                (
                    "Jarvis, qual \\u00e9 o meu "
                    "nome completo?"
                ),
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            result.get(
                "reason"
            ),
            "owner_full_name_not_stored",
        )

        self.assertEqual(
            result.get(
                "evidence_status"
            ),
            "missing",
        )

        self.assertEqual(
            result.get(
                "results"
            ),
            [],
        )

    def test_executor_accepts_explicit_owner_full_name(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "owner-full-name",
                "source":
                    "explicit_fact",
                "kind":
                    "user_explicit",
                "text":
                    (
                        "o meu nome completo e "
                        "Tiago Resende da Silva"
                    ),
            },
        ])

        result = (
            MemoryGroundingExecutor(
                backend
            ).execute(
                "OWNER_FULL_NAME",
                (
                    "Jarvis, qual \\u00e9 o meu "
                    "nome completo?"
                ),
            )
        )

        self.assertTrue(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            len(
                result.get(
                    "results"
                )
                or []
            ),
            1,
        )

    def test_executor_strips_jarvis_vocative_before_relevance_backend(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "partner",
                "source":
                    "memory_graph",
                "kind":
                    "edge",
                "text":
                    (
                        "source=OWNER\\n"
                        "relation=PARTNER\\n"
                        "target=ISA"
                    ),
            },
        ])

        result = (
            MemoryGroundingExecutor(
                backend
            ).execute(
                "OWNER_RELATIONSHIP",
                (
                    "Jarvis, quem \\u00e9 "
                    "a minha mulher?"
                ),
            )
        )

        self.assertTrue(
            result.get(
                "retrieved"
            )
        )

        self.assertGreaterEqual(
            len(
                backend.search_calls
            ),
            1,
        )

        for call in (
            backend.search_calls
        ):
            self.assertFalse(
                call[
                    "query"
                ].lower().startswith(
                    "jarvis"
                )
            )

    def test_scope_rules_are_immutable_contract_data(
        self,
    ):
        full_name = (
            require_memory_grounding_scope(
                "OWNER_FULL_NAME"
            )
        )

        owner_learning = (
            require_memory_grounding_scope(
                "OWNER_LEARNING_GOALS"
            )
        )

        self.assertTrue(
            full_name.rules
        )

        self.assertTrue(
            owner_learning.rules
        )

        with self.assertRaises(
            AttributeError
        ):
            full_name.rules = ()


    def test_coordinator_uses_scope_and_preserves_missing_evidence_contract(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "profile",
                "source":
                    "user_profile",
                "kind":
                    "profile",
                "text":
                    "name=Tiago",
            },
            {
                "id":
                    "wife",
                "source":
                    "explicit_fact",
                "kind":
                    "user_explicit",
                "text":
                    (
                        "o nome completo da minha "
                        "mulher e Ana Isa "
                        "Guimaraes Lopes"
                    ),
            },
        ])

        request = StructuredRequest(
            raw_text=
                "qual e o meu nome completo",
            effective_text=
                "qual e o meu nome completo",
            intent=
                "GENERAL_CONVERSATION",
            domain=
                "owner_memory",
            subject=
                "OWNER",
            action=
                "discuss_owner_context",
            confidence=
                0.95,
            memory_scope=
                "OWNER_FULL_NAME",
        )

        result = (
            MemoryRetrievalCoordinator(
                backend
            ).context_for_request(
                request
            )
        )

        self.assertFalse(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            result.get(
                "evidence_status"
            ),
            "missing",
        )

        self.assertEqual(
            result.get(
                "reason"
            ),
            "owner_full_name_not_stored",
        )

        context = str(
            result.get(
                "context"
            )
            or ""
        )

        self.assertIn(
            "memory_scope=OWNER_FULL_NAME",
            context,
        )

        self.assertIn(
            "evidence_status=missing",
            context,
        )

        self.assertIn(
            "[NO ADMISSIBLE MEMORY EVIDENCE]",
            context,
        )

        self.assertNotIn(
            "name=Tiago",
            context,
        )

        self.assertNotIn(
            "Ana Isa",
            context,
        )

    def test_coordinator_allows_jarvis_identity_scope_without_owner_leak(
        self,
    ):
        backend = _LooseBackend([
            {
                "id":
                    "owner-learning",
                "source":
                    "personal_model",
                "kind":
                    "owner_learning_goals",
                "text":
                    "redes",
            },
            {
                "id":
                    "jarvis-learning",
                "source":
                    "personal_model",
                "kind":
                    "jarvis_learning_goals",
                "text":
                    "Rust",
            },
        ])

        request = StructuredRequest(
            raw_text=
                (
                    "quais sao os teus "
                    "objetivos de aprendizagem"
                ),
            effective_text=
                (
                    "quais sao os teus "
                    "objetivos de aprendizagem"
                ),
            intent=
                "IDENTITY_DIALOGUE",
            domain=
                "jarvis_self",
            subject=
                "JARVIS",
            action=
                "discuss_identity",
            confidence=
                0.95,
            memory_scope=
                "JARVIS_LEARNING_GOALS",
        )

        result = (
            MemoryRetrievalCoordinator(
                backend
            ).context_for_request(
                request
            )
        )

        self.assertTrue(
            result.get(
                "retrieved"
            )
        )

        self.assertEqual(
            result.get(
                "kinds"
            ),
            [
                "jarvis_learning_goals",
            ],
        )

        context = str(
            result.get(
                "context"
            )
            or ""
        )

        self.assertIn(
            "Rust",
            context,
        )

        self.assertNotIn(
            "kind=owner_learning_goals",
            context,
        )


if __name__ == "__main__":
    unittest.main()
