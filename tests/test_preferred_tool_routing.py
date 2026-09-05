from __future__ import annotations

import unittest
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
