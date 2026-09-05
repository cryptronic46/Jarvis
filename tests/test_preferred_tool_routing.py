from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.tool_registry import ToolRegistry
from jarvis_core.services.semantic_request import StructuredRequest


class _ProbeTools:
    def __init__(self):
        self.exact_calls = []
        self.query_calls = []
        self.validation_calls = []
        self.validation_result = (True, None)

    def validate_arguments(self, name, arguments):
        self.validation_calls.append(
            (name, dict(arguments))
        )
        return self.validation_result

    def schemas_for_names(self, names, *, max_tools=20):
        self.exact_calls.append(
            (list(names), max_tools)
        )
        return [{
            "type": "function",
            "function": {
                "name": names[0],
            },
        }]

    def schemas_for_query(self, query, *, max_tools=20):
        self.query_calls.append(
            (query, max_tools)
        )
        return [{
            "type": "function",
            "function": {
                "name": "heuristic_tool",
            },
        }]


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class PreferredToolRoutingTests(unittest.TestCase):
    def _request(
        self,
        *,
        requires_tool,
        preferred_tool=None,
        tool_arguments=None,
    ):
        return StructuredRequest(
            raw_text="Abre o Spotify",
            effective_text="Abre o Spotify",
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="open",
            target="spotify",
            requires_tool=requires_tool,
            preferred_tool=preferred_tool,
            tool_arguments=tool_arguments,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    def test_no_tool_request_exposes_no_tools(self):
        tools = _ProbeTools()
        brain = SimpleNamespace(
            tools=tools,
            events=_Events(),
        )

        result = JarvisBrain._select_tool_schemas(
            brain,
            request=self._request(
                requires_tool=False,
            ),
            effective_query="Abre o Spotify",
            max_tools=20,
        )

        self.assertEqual(result, [])
        self.assertEqual(tools.exact_calls, [])
        self.assertEqual(tools.query_calls, [])

    def test_preferred_tool_uses_exact_name_only(self):
        tools = _ProbeTools()
        brain = SimpleNamespace(
            tools=tools,
            events=_Events(),
        )

        result = JarvisBrain._select_tool_schemas(
            brain,
            request=self._request(
                requires_tool=True,
                preferred_tool="open_application",
                tool_arguments={
                    "app_name": "spotify",
                },
            ),
            effective_query="Abre o Spotify",
            max_tools=20,
        )

        self.assertEqual(
            tools.exact_calls,
            [(["open_application"], 20)],
        )
        self.assertEqual(tools.query_calls, [])
        self.assertEqual(
            result[0]["function"]["name"],
            "open_application",
        )

    def test_invalid_semantic_arguments_fail_closed(self):
        tools = _ProbeTools()
        tools.validation_result = (
            False,
            "required:$.app_name",
        )

        brain = SimpleNamespace(
            tools=tools,
            events=_Events(),
        )

        result = JarvisBrain._select_tool_schemas(
            brain,
            request=self._request(
                requires_tool=True,
                preferred_tool="open_application",
                tool_arguments={},
            ),
            effective_query="Abre o Spotify",
            max_tools=20,
        )

        self.assertEqual(result, [])
        self.assertEqual(
            tools.validation_calls,
            [("open_application", {})],
        )
        self.assertEqual(tools.exact_calls, [])
        self.assertEqual(tools.query_calls, [])

    def test_unresolved_tool_request_uses_query_fallback(self):
        tools = _ProbeTools()
        brain = SimpleNamespace(
            tools=tools,
            events=_Events(),
        )

        result = JarvisBrain._select_tool_schemas(
            brain,
            request=self._request(
                requires_tool=True,
                preferred_tool=None,
            ),
            effective_query="faz esta acao",
            max_tools=7,
        )

        self.assertEqual(tools.exact_calls, [])
        self.assertEqual(
            tools.query_calls,
            [("faz esta acao", 7)],
        )
        self.assertEqual(
            result[0]["function"]["name"],
            "heuristic_tool",
        )

    def test_semantic_arguments_override_model_arguments(self):
        brain = SimpleNamespace()

        execution_name, arguments, reason = (
            JarvisBrain._prepare_tool_execution_call(
                brain,
                request=self._request(
                    requires_tool=True,
                    preferred_tool="open_application",
                    tool_arguments={
                        "app_name": "spotify",
                    },
                ),
                allowed_tool_names={
                    "open_application",
                },
                name="open_application",
                arguments={
                    "app_name": "notepad",
                },
            )
        )

        self.assertIsNone(reason)
        self.assertEqual(
            execution_name,
            "open_application",
        )
        self.assertEqual(
            arguments,
            {"app_name": "spotify"},
        )

    def test_semantic_tool_name_mismatch_is_blocked(self):
        brain = SimpleNamespace()

        execution_name, arguments, reason = (
            JarvisBrain._prepare_tool_execution_call(
                brain,
                request=self._request(
                    requires_tool=True,
                    preferred_tool="open_application",
                    tool_arguments={
                        "app_name": "spotify",
                    },
                ),
                allowed_tool_names={
                    "open_application",
                    "close_application",
                },
                name="close_application",
                arguments={
                    "app_name": "spotify",
                },
            )
        )

        self.assertIsNone(execution_name)
        self.assertEqual(arguments, {})
        self.assertEqual(
            reason,
            "semantic_tool_mismatch",
        )

    def test_unexposed_legacy_tool_is_blocked(self):
        brain = SimpleNamespace()

        execution_name, arguments, reason = (
            JarvisBrain._prepare_tool_execution_call(
                brain,
                request=None,
                allowed_tool_names={
                    "open_application",
                },
                name="close_application",
                arguments={
                    "app_name": "spotify",
                },
            )
        )

        self.assertIsNone(execution_name)
        self.assertEqual(arguments, {})
        self.assertEqual(
            reason,
            "tool_not_exposed",
        )

    def test_exposed_legacy_tool_preserves_model_arguments(self):
        brain = SimpleNamespace()

        execution_name, arguments, reason = (
            JarvisBrain._prepare_tool_execution_call(
                brain,
                request=None,
                allowed_tool_names={
                    "open_application",
                },
                name="open_application",
                arguments='{"app_name":"spotify"}',
            )
        )

        self.assertIsNone(reason)
        self.assertEqual(
            execution_name,
            "open_application",
        )
        self.assertEqual(
            arguments,
            {"app_name": "spotify"},
        )

    def test_agent_loop_uses_prepared_call_for_registry_execution(self):
        tree = ast.parse(
            Path(
                "jarvis_core/core/brain.py"
            ).read_text(encoding="utf-8")
        )

        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name == "_ask_locked"
        )

        tool_loop = next(
            node
            for node in ast.walk(method)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "tool_calls"
        )

        prepare_calls = []
        execute_calls = []

        for node in ast.walk(tool_loop):
            if not isinstance(node, ast.Call):
                continue

            func = node.func

            if (
                isinstance(func, ast.Attribute)
                and func.attr
                == "_prepare_tool_execution_call"
            ):
                prepare_calls.append(node)

            if (
                isinstance(func, ast.Attribute)
                and func.attr == "execute"
                and isinstance(
                    func.value,
                    ast.Attribute,
                )
                and func.value.attr == "tools"
                and isinstance(
                    func.value.value,
                    ast.Name,
                )
                and func.value.value.id == "self"
            ):
                execute_calls.append(node)

        self.assertEqual(
            len(prepare_calls),
            1,
        )
        self.assertEqual(
            len(execute_calls),
            1,
        )

        prepare_call = prepare_calls[0]
        execute_call = execute_calls[0]

        self.assertLess(
            prepare_call.lineno,
            execute_call.lineno,
        )

        self.assertEqual(
            len(execute_call.args),
            2,
        )

        self.assertIsInstance(
            execute_call.args[0],
            ast.Name,
        )
        self.assertEqual(
            execute_call.args[0].id,
            "execution_name",
        )

        self.assertIsInstance(
            execute_call.args[1],
            ast.Name,
        )
        self.assertEqual(
            execute_call.args[1].id,
            "execution_arguments",
        )

    def test_blocked_tool_call_cannot_reach_registry_execute(self):
        tree = ast.parse(
            Path(
                "jarvis_core/core/brain.py"
            ).read_text(encoding="utf-8")
        )

        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_ask_locked"
        )

        tool_loop = next(
            node
            for node in ast.walk(method)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Name)
            and node.iter.id == "tool_calls"
        )

        block_if = next(
            node
            for node in ast.walk(tool_loop)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "block_reason"
        )

        self.assertTrue(
            any(
                isinstance(node, ast.Continue)
                for node in ast.walk(block_if)
            )
        )

        execute_call = next(
            node
            for node in ast.walk(tool_loop)
            if isinstance(node, ast.Call)
            and isinstance(
                node.func,
                ast.Attribute,
            )
            and node.func.attr == "execute"
            and isinstance(
                node.func.value,
                ast.Attribute,
            )
            and node.func.value.attr == "tools"
        )

        self.assertLess(
            block_if.lineno,
            execute_call.lineno,
        )

    def test_registry_exact_names_is_fail_closed(self):
        events = _Events()

        registry = SimpleNamespace(
            _tools={
                "open_application": SimpleNamespace(
                    schema={
                        "type": "function",
                        "function": {
                            "name": "open_application",
                        },
                    }
                ),
                "close_application": SimpleNamespace(
                    schema={
                        "type": "function",
                        "function": {
                            "name": "close_application",
                        },
                    }
                ),
            },
            events=events,
        )

        result = ToolRegistry.schemas_for_names(
            registry,
            [
                "open_application",
                "missing_tool",
                "open_application",
            ],
            max_tools=20,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["function"]["name"],
            "open_application",
        )

        self.assertEqual(len(events.rows), 1)
        name, data = events.rows[0]

        self.assertEqual(
            name,
            "TOOL_SCHEMA_SELECTION",
        )
        self.assertEqual(
            data["mode"],
            "exact_names",
        )
        self.assertEqual(
            data["tools"],
            ["open_application"],
        )
        self.assertEqual(
            data["unknown"],
            ["missing_tool"],
        )


if __name__ == "__main__":
    unittest.main()
