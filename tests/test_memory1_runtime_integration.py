from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPO_ROOT = Path(
    __file__
).resolve().parents[1]

CLI_PATH = (
    REPO_ROOT
    / "jarvis_core/cli.py"
)


def expr_text(
    node: ast.AST | None,
) -> str:
    if node is None:
        return ""

    return ast.unparse(
        node
    )


def call_name(
    node: ast.AST,
) -> str:
    if isinstance(
        node,
        ast.Name,
    ):
        return node.id

    if isinstance(
        node,
        ast.Attribute,
    ):
        prefix = call_name(
            node.value
        )

        if prefix:
            return (
                prefix
                + "."
                + node.attr
            )

        return node.attr

    return ""


def assign_targets(
    node: ast.AST,
):
    if isinstance(
        node,
        ast.Name,
    ):
        return (
            node.id,
        )

    if isinstance(
        node,
        (
            ast.Tuple,
            ast.List,
        ),
    ):
        result = []

        for element in node.elts:
            result.extend(
                assign_targets(
                    element
                )
            )

        return tuple(
            result
        )

    if isinstance(
        node,
        ast.Attribute,
    ):
        return (
            expr_text(
                node
            ),
        )

    return ()


class Memory1RuntimeIntegrationTests(
    unittest.TestCase
):
    @classmethod
    def setUpClass(
        cls,
    ) -> None:
        cls.source = (
            CLI_PATH.read_text(
                encoding="utf-8"
            )
        )

        cls.tree = ast.parse(
            cls.source,
            filename=str(
                CLI_PATH
            ),
        )

        main_nodes = [
            node
            for node
            in cls.tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "main"
            )
        ]

        assert len(
            main_nodes
        ) == 1

        cls.main = (
            main_nodes[
                0
            ]
        )

        process_nodes = [
            node
            for node
            in ast.walk(
                cls.main
            )
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "process_request"
            )
        ]

        assert len(
            process_nodes
        ) == 1

        cls.process = (
            process_nodes[
                0
            ]
        )

        route_nodes = [
            node
            for node
            in cls.tree.body
            if (
                isinstance(
                    node,
                    ast.FunctionDef,
                )
                and node.name
                == "route_runtime_request"
            )
        ]

        assert len(
            route_nodes
        ) == 1

        cls.route = (
            route_nodes[
                0
            ]
        )

        cls.main_source = (
            ast.get_source_segment(
                cls.source,
                cls.main,
            )
            or ""
        )

        cls.process_source = (
            ast.get_source_segment(
                cls.source,
                cls.process,
            )
            or ""
        )

        cls.route_source = (
            ast.get_source_segment(
                cls.source,
                cls.route,
            )
            or ""
        )

    # 01
    def test_memory1_runtime_dependencies_live_in_main(
        self,
    ) -> None:
        imported = set()

        for node in ast.walk(
            self.main
        ):
            if not isinstance(
                node,
                ast.ImportFrom,
            ):
                continue

            for alias in node.names:
                imported.add(
                    alias.name
                )

        required = {
            "CanonicalMemoryStore",
            "MemoryAuthority",
            "SourceType",
            "InterpreterContext",
            "MemoryOperation",
            "TrustedTwoStageSemanticMemoryAdapter",
            "utc_now",
            "ensure_canonical_owner",
            "QwenSemanticIdentityMatcher",
            "JarvisQwenMemoryModel",
            "build_memory_resolution_plan",
            "remember_plan_has_ambiguous_identity",
            "TrustedWriteExecutionContext",
            "execute_memory_resolution_plan",
            "MemoryTurnResult",
            "RememberTurnOutcome",
            "RememberTurnResult",
            "build_remember_turn_result",
            "build_memory1_remember_response_context",
        }

        self.assertTrue(
            required.issubset(
                imported
            )
        )

    # 02
    def test_memory1_store_is_constructed_after_brain(
        self,
    ) -> None:
        brain_lines = []

        store_lines = []

        for node in ast.walk(
            self.main
        ):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            name = call_name(
                node.func
            )

            if name == "JarvisBrain":
                brain_lines.append(
                    node.lineno
                )

            if name == "CanonicalMemoryStore":
                store_lines.append(
                    node.lineno
                )

        self.assertEqual(
            len(
                brain_lines
            ),
            1,
        )

        self.assertEqual(
            len(
                store_lines
            ),
            1,
        )

        self.assertLess(
            brain_lines[
                0
            ],
            store_lines[
                0
            ],
        )

    # 03
    def test_memory1_reuses_brain_client_and_settings_model(
        self,
    ) -> None:
        assignments = {}

        for node in ast.walk(
            self.main
        ):
            if not isinstance(
                node,
                ast.Assign,
            ):
                continue

            for target in node.targets:
                for name in assign_targets(
                    target
                ):
                    assignments[
                        name
                    ] = node.value

        qwen_call = assignments[
            "memory1_qwen_model"
        ]

        self.assertIsInstance(
            qwen_call,
            ast.Call,
        )

        self.assertEqual(
            call_name(
                qwen_call.func
            ),
            "JarvisQwenMemoryModel",
        )

        self.assertEqual(
            expr_text(
                qwen_call.args[
                    0
                ]
            ),
            "brain.client",
        )

        keyword_map = {
            keyword.arg:
                expr_text(
                    keyword.value
                )
            for keyword
            in qwen_call.keywords
        }

        self.assertEqual(
            keyword_map.get(
                "model"
            ),
            "settings.model",
        )

        adapter_call = assignments[
            "memory1_adapter"
        ]

        adapter_keywords = {
            keyword.arg:
                expr_text(
                    keyword.value
                )
            for keyword
            in adapter_call.keywords
        }

        self.assertEqual(
            adapter_keywords.get(
                "model_id"
            ),
            "settings.model",
        )

    # 04
    def test_memory1_does_not_build_second_local_client(
        self,
    ) -> None:
        calls = {
            call_name(
                node.func
            )
            for node
            in ast.walk(
                self.main
            )
            if isinstance(
                node,
                ast.Call,
            )
        }

        self.assertNotIn(
            "build_local_client",
            calls,
        )

        self.assertNotIn(
            "NativeLlamaClient",
            calls,
        )

        self.assertNotIn(
            "OllamaLocalCompatClient",
            calls,
        )

        self.assertNotIn(
            "JarvisLocalClient",
            calls,
        )

    # 05
    def test_owner_bootstrap_and_binding_are_single_startup_values(
        self,
    ) -> None:
        source = (
            self.main_source
        )

        self.assertEqual(
            source.count(
                "ensure_canonical_owner("
            ),
            1,
        )

        self.assertEqual(
            source.count(
                '.canonical_id_for(\n            "owner"'
            ),
            1,
        )

    # 06
    def test_process_request_captures_occurred_at_at_entry(
        self,
    ) -> None:
        body = (
            self.process.body
        )

        self.assertGreaterEqual(
            len(
                body
            ),
            3,
        )

        self.assertIsInstance(
            body[
                1
            ],
            ast.Assign,
        )

        self.assertEqual(
            assign_targets(
                body[
                    1
                ].targets[
                    0
                ]
            ),
            (
                "memory1_occurred_at",
            ),
        )

        self.assertEqual(
            expr_text(
                body[
                    1
                ].value
            ),
            "utc_now()",
        )

        self.assertEqual(
            assign_targets(
                body[
                    2
                ].targets[
                    0
                ]
            ),
            (
                "command_started",
            ),
        )

    # 07
    def test_interpreter_context_uses_trusted_owner_context(
        self,
    ) -> None:
        calls = [
            node
            for node
            in ast.walk(
                self.process
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and call_name(
                    node.func
                )
                == "InterpreterContext"
            )
        ]

        self.assertEqual(
            len(
                calls
            ),
            1,
        )

        keywords = {
            keyword.arg:
                expr_text(
                    keyword.value
                )
            for keyword
            in calls[
                0
            ].keywords
        }

        self.assertEqual(
            keywords.get(
                "locale"
            ),
            "'pt-PT'",
        )

        self.assertEqual(
            keywords.get(
                "default_subject_ref"
            ),
            "'owner'",
        )

        self.assertEqual(
            keywords.get(
                "current_time"
            ),
            "memory1_occurred_at",
        )

        self.assertEqual(
            keywords.get(
                "known_entity_refs"
            ),
            "memory1_owner_bindings.local_refs()",
        )

    # 08
    def test_adapter_interprets_the_owner_turn(
        self,
    ) -> None:
        calls = [
            node
            for node
            in ast.walk(
                self.process
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and call_name(
                    node.func
                )
                == "memory1_adapter.interpret"
            )
        ]

        self.assertEqual(
            len(
                calls
            ),
            1,
        )

        call = calls[
            0
        ]

        self.assertEqual(
            expr_text(
                call.args[
                    0
                ]
            ),
            "user_text",
        )

        keyword_map = {
            keyword.arg:
                expr_text(
                    keyword.value
                )
            for keyword
            in call.keywords
        }

        self.assertEqual(
            keyword_map.get(
                "context"
            ),
            "memory1_context",
        )

    # 09
    def test_only_remember_enters_canonical_write_branch(
        self,
    ) -> None:
        remember_write_branches = []

        for node in ast.walk(self.process):
            if not isinstance(node, ast.If):
                continue
            if (
                expr_text(node.test)
                != "memory1_interpretation.operation is MemoryOperation.REMEMBER"
            ):
                continue

            branch_calls = {
                call_name(call.func)
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            }

            if "execute_memory_resolution_plan" in branch_calls:
                remember_write_branches.append((node, branch_calls))

        self.assertEqual(len(remember_write_branches), 1)
        _, branch_calls = remember_write_branches[0]
        self.assertIn("build_memory_resolution_plan", branch_calls)
        self.assertIn("execute_memory_resolution_plan", branch_calls)
        self.assertNotIn("execute_memory_recall_plan", branch_calls)

    def test_resolution_plan_uses_canonical_store_for_both_registries(
        self,
    ) -> None:
        calls = [
            node
            for node
            in ast.walk(
                self.process
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and call_name(
                    node.func
                )
                == "build_memory_resolution_plan"
            )
        ]

        # RECALL and REMEMBER each own one
        # mutually exclusive resolution path.
        self.assertEqual(
            len(
                calls
            ),
            2,
        )

        for call in calls:
            keywords = {
                keyword.arg:
                    expr_text(
                        keyword.value
                    )
                for keyword
                in call.keywords
            }

            self.assertEqual(
                keywords.get(
                    "matcher"
                ),
                "memory1_matcher",
            )

            self.assertEqual(
                keywords.get(
                    "entity_registry"
                ),
                "memory1_store",
            )

            self.assertEqual(
                keywords.get(
                    "property_registry"
                ),
                "memory1_store",
            )

            self.assertEqual(
                keywords.get(
                    "trusted_entity_bindings"
                ),
                "memory1_owner_bindings",
            )

    # 11
    def test_write_context_is_core_owned(
        self,
    ) -> None:
        calls = [
            node
            for node
            in ast.walk(
                self.process
            )
            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and call_name(
                    node.func
                )
                == "TrustedWriteExecutionContext"
            )
        ]

        self.assertEqual(
            len(
                calls
            ),
            1,
        )

        keywords = {
            keyword.arg:
                expr_text(
                    keyword.value
                )
            for keyword
            in calls[
                0
            ].keywords
        }

        expected = {
            "raw_text":
                "user_text",

            "source_type":
                "SourceType.OWNER_TURN",

            "authority":
                "memory1_authority",

            "occurred_at":
                "memory1_occurred_at",

            "recorded_at":
                "memory1_recorded_at",

            "actor_entity_id":
                "memory1_owner_id",

            "speaker_entity_id":
                "memory1_owner_id",

            "conversation_id":
                "None",

            "sequence":
                "None",
        }

        self.assertEqual(
            keywords,
            expected,
        )

    # 12
    def test_authority_is_derived_only_from_explicit_memory_request(
        self,
    ) -> None:
        assignments = []

        for node in ast.walk(
            self.process
        ):
            if not isinstance(
                node,
                ast.Assign,
            ):
                continue

            targets = {
                name
                for target
                in node.targets
                for name
                in assign_targets(
                    target
                )
            }

            if (
                "memory1_authority"
                in targets
            ):
                assignments.append(
                    node
                )

        self.assertEqual(
            len(
                assignments
            ),
            1,
        )

        expression = expr_text(
            assignments[
                0
            ].value
        )

        self.assertIn(
            "memory1_interpretation.explicit_memory_request",
            expression,
        )

        self.assertIn(
            "MemoryAuthority.OWNER_EXPLICIT",
            expression,
        )

        self.assertIn(
            "MemoryAuthority.CONVERSATION_DERIVED",
            expression,
        )

    # 13
    def test_recorded_at_is_captured_before_executor(
        self,
    ) -> None:
        recorded_line = None
        executor_line = None

        for node in ast.walk(
            self.process
        ):
            if isinstance(
                node,
                ast.Assign,
            ):
                targets = {
                    name
                    for target
                    in node.targets
                    for name
                    in assign_targets(
                        target
                    )
                }

                if (
                    "memory1_recorded_at"
                    in targets
                ):
                    self.assertEqual(
                        expr_text(
                            node.value
                        ),
                        "utc_now()",
                    )

                    recorded_line = (
                        node.lineno
                    )

            if (
                isinstance(
                    node,
                    ast.Call,
                )
                and call_name(
                    node.func
                )
                == "execute_memory_resolution_plan"
            ):
                executor_line = (
                    node.lineno
                )

        self.assertIsNotNone(
            recorded_line
        )

        self.assertIsNotNone(
            executor_line
        )

        self.assertLess(
            recorded_line,
            executor_line,
        )

    # 14
    def test_durable_remember_success_events_are_typed(
        self,
    ) -> None:
        process_source = ast.unparse(self.process)

        self.assertIn(
            "memory1_remember_result.outcome is RememberTurnOutcome.COMMITTED",
            process_source,
        )
        self.assertIn(
            "MEMORY1_RUNTIME_WRITE_COMMITTED",
            process_source,
        )
        self.assertIn(
            "memory1_remember_result.outcome is RememberTurnOutcome.NO_CHANGE_IDEMPOTENT",
            process_source,
        )
        self.assertIn(
            "MEMORY1_RUNTIME_WRITE_IDEMPOTENT",
            process_source,
        )
        self.assertIn(
            "MEMORY1_RUNTIME_WRITE_NOT_COMMITTED",
            process_source,
        )

    def test_memory1_interpretation_failures_are_typed_and_bugs_propagate(
        self,
    ) -> None:
        memory_tries = []

        for node in ast.walk(self.process):
            if not isinstance(node, ast.Try):
                continue
            source = ast.unparse(node)
            if "memory1_adapter.interpret" in source:
                memory_tries.append(node)

        self.assertEqual(len(memory_tries), 1)
        block = memory_tries[0]
        self.assertEqual(len(block.handlers), 3)

        handler_types = [expr_text(handler.type) for handler in block.handlers]
        self.assertEqual(
            handler_types,
            ["MemoryAvailabilityError", "MemoryModelContractError", "Exception"],
        )

        availability_source = ast.unparse(block.handlers[0])
        schema_source = ast.unparse(block.handlers[1])
        generic_source = ast.unparse(block.handlers[2])

        self.assertIn("MemoryInterpretationStatus.MODEL_FAILURE", availability_source)
        self.assertIn(
            "build_memory1_interpretation_fail_closed_context",
            availability_source,
        )
        self.assertIn("MemoryInterpretationStatus.SCHEMA_INVALID", schema_source)
        self.assertIn(
            "build_memory1_interpretation_fail_closed_context",
            schema_source,
        )
        self.assertIn("MEMORY1_RUNTIME_ERROR", generic_source)
        self.assertTrue(
            any(isinstance(node, ast.Raise) for node in ast.walk(block.handlers[2]))
        )

    # 16
    def test_memory1_recall_and_remember_complete_before_answer_route(
        self,
    ):
        process = self.source[
            self.source.index(
                "def process_request"
            ):
        ]

        pre = process.index(
            "# MEMORY1_RUNTIME_PRE_ROUTE_V1"
        )
        recall_read = process.index(
            "execute_memory_recall_plan("
        )
        remember_write = process.index(
            "execute_memory_resolution_plan("
        )
        route = process.index(
            "answer, route, hybrid = "
            "route_runtime_request("
        )

        self.assertLess(pre, recall_read)
        self.assertLess(pre, remember_write)
        self.assertLess(recall_read, route)
        self.assertLess(remember_write, route)
        self.assertEqual(process.count("memory1_adapter.interpret("), 1)
        self.assertNotIn(
            "# MEMORY1_RUNTIME_REMEMBER_WRITE_V1",
            process,
        )
        self.assertIn(
            "memory_grounding_context=",
            process[route:route + 1400],
        )

    def test_route_and_owner_source_domain_remain_unchanged(
        self,
    ) -> None:
        forbidden = (
            "CanonicalMemoryStore",
            "memory1_",
            "execute_memory_resolution_plan",
            "MemoryTurnResult",
            "RememberTurnOutcome",
            "RememberTurnResult",
            "build_remember_turn_result",
            "build_memory1_remember_response_context",
            "ensure_canonical_owner",
        )

        for token in forbidden:
            self.assertNotIn(
                token,
                self.route_source,
            )

        default_source = None

        for argument, default in zip(
            self.process.args.kwonlyargs,
            self.process.args.kw_defaults,
        ):
            if argument.arg == "source":
                default_source = (
                    ast.literal_eval(
                        default
                    )
                )

        self.assertEqual(
            default_source,
            "terminal",
        )

        sources = set()

        for node in ast.walk(
            self.main
        ):
            if not isinstance(
                node,
                ast.Call,
            ):
                continue

            if (
                call_name(
                    node.func
                )
                != "process_request"
            ):
                continue

            source = (
                default_source
            )

            for keyword in node.keywords:
                if keyword.arg == "source":
                    source = (
                        ast.literal_eval(
                            keyword.value
                        )
                    )

            sources.add(
                source
            )

        self.assertEqual(
            sources,
            {
                "terminal",
            },
        )


if __name__ == "__main__":
    unittest.main()
