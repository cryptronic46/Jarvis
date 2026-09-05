from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


class _Events:
    def __init__(self):
        self.items = []

    def emit(self, event, **kwargs):
        self.items.append((event, kwargs))


class _Tools:
    def __init__(self):
        self.calls = []
        self.request_started_at = None
        self.names = {
            "open_application",
            "get_current_time",
            "get_synthetic_self_state",
        }

    def validate_arguments(self, name, arguments):
        return True, None

    def execute(self, name, arguments=None, *args, **kwargs):
        arguments = dict(arguments or {})
        self.calls.append((name, arguments))

        if name == "open_application":
            return json.dumps({
                "ok": True,
                "already_running": False,
            })

        if name == "get_current_time":
            return json.dumps({
                "ok": True,
                "time": "17:00",
                "formatted": "17:00",
            })

        return json.dumps({"ok": True})


class _Apps:
    def list_apps(self):
        return [
            {
                "id": "brave",
                "name": "brave",
                "aliases": ["brave"],
            },
            {
                "id": "spotify",
                "name": "spotify",
                "aliases": ["spotify"],
            },
        ]


def _router():
    events = _Events()
    tools = _Tools()

    router = FastCommandRouter(
        events,
        tools,
        _Apps(),
    )

    return router, tools, events


class SemanticFastAuthorityTests(unittest.TestCase):
    def test_capability_question_cannot_execute_fast_tool(self):
        router, tools, _events = _router()

        text = "Sabes abrir o Spotify?"
        request = resolve_semantic_request(text)

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertFalse(result.handled)
        self.assertEqual(tools.calls, [])

    def test_explicit_open_keeps_fast_execution(self):
        router, tools, _events = _router()

        text = "Abre o Spotify"
        request = resolve_semantic_request(text)

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertTrue(result.handled)
        self.assertEqual(
            tools.calls,
            [
                (
                    "open_application",
                    {"app_name": "spotify"},
                )
            ],
        )

    def test_compound_negation_fails_closed(self):
        router, tools, _events = _router()

        text = (
            "N\u00e3o abras o Spotify, "
            "abre o Brave."
        )

        request = resolve_semantic_request(text)

        self.assertEqual(
            request.intent,
            "UNKNOWN",
        )
        self.assertFalse(
            request.requires_tool
        )

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertFalse(result.handled)
        self.assertEqual(tools.calls, [])

    def test_current_time_has_authoritative_contract(self):
        request = resolve_semantic_request(
            "Que horas s\u00e3o?"
        )

        self.assertTrue(
            request.requires_tool
        )
        self.assertEqual(
            request.preferred_tool,
            "get_current_time",
        )
        self.assertEqual(
            request.action,
            "read_time",
        )

    def test_operational_request_without_preferred_tool_is_vetoed(self):
        import json
        from types import SimpleNamespace

        from jarvis_core.core.fast_router import (
            FastCommandRouter,
        )
        from jarvis_core.services.semantic_request import (
            StructuredRequest,
        )

        class FakeEvents:
            def __init__(self):
                self.rows = []

            def emit(self, name, **payload):
                self.rows.append(
                    (
                        name,
                        dict(payload),
                    )
                )

        class FakeTools:
            def __init__(self):
                self.execute_calls = []

            def execute(self, name, arguments):
                self.execute_calls.append(
                    (
                        name,
                        dict(arguments),
                    )
                )

                return json.dumps(
                    {
                        "ok": True,
                    }
                )

        class ProbeRouter(FastCommandRouter):
            def _dispatch_legacy(
                self,
                text,
                *,
                voice_origin=False,
            ):
                self._tool(
                    "open_application",
                    {
                        "app_name": "spotify",
                    },
                )

                return SimpleNamespace(
                    handled=True,
                    response="probe",
                    route="probe_open",
                )

        events = FakeEvents()
        tools = FakeTools()

        router = ProbeRouter(
            events,
            tools,
            SimpleNamespace(),
        )

        request = StructuredRequest(
            raw_text="Abre o Spotify",
            effective_text="Abre o Spotify",
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="open",
            target="spotify",
            requires_tool=True,
            preferred_tool=None,
            tool_arguments=None,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        result = router.dispatch(
            "Abre o Spotify",
            request=request,
        )

        self.assertFalse(
            result.handled
        )

        self.assertEqual(
            tools.execute_calls,
            [],
        )

        vetoes = [
            payload
            for name, payload
            in events.rows
            if name
            == "FAST_PATH_SEMANTIC_VETO"
        ]

        self.assertEqual(
            len(vetoes),
            1,
        )

        self.assertEqual(
            vetoes[0]["reason"],
            "semantic_tool_not_resolved",
        )

        self.assertEqual(
            vetoes[0]["intent"],
            "OPERATIONAL_ACTION",
        )

        self.assertTrue(
            vetoes[0]["requires_tool"]
        )

        self.assertIsNone(
            vetoes[0]["preferred_tool"]
        )

    def test_cli_resolves_semantics_before_fast_dispatch(self):
        source = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")

        route_start = source.index(
            "def route_runtime_request("
        )

        route_end = source.index(
            "\ndef main() -> None:",
            route_start,
        )

        route_block = source[
            route_start:route_end
        ]

        process_start = source.index(
            "    def process_request("
        )

        process_end = source.index(
            "    def handle_voice_command(",
            process_start,
        )

        process_block = source[
            process_start:process_end
        ]

        self.assertEqual(
            route_block.count(
                "resolve_semantic_request("
            ),
            1,
        )

        self.assertEqual(
            route_block.count(
                "fast_router.dispatch("
            ),
            1,
        )

        self.assertEqual(
            route_block.count(
                "hybrid_brain.ask("
            ),
            1,
        )

        semantic_index = route_block.index(
            "resolve_semantic_request("
        )

        fast_index = route_block.index(
            "fast_router.dispatch("
        )

        hybrid_index = route_block.index(
            "hybrid_brain.ask("
        )

        self.assertLess(
            semantic_index,
            fast_index,
        )

        self.assertLess(
            fast_index,
            hybrid_index,
        )

        self.assertEqual(
            route_block.count(
                "request=structured_request"
            ),
            2,
        )

        self.assertEqual(
            process_block.count(
                "route_runtime_request("
            ),
            1,
        )

        self.assertNotIn(
            "resolve_semantic_request(",
            process_block,
        )

        self.assertNotIn(
            "fast_router.dispatch(",
            process_block,
        )

        self.assertNotIn(
            "hybrid_brain.ask(",
            process_block,
        )

    def test_fast_router_has_single_tool_execution_boundary(self):
        source = Path(
            "jarvis_core/core/fast_router.py"
        ).read_text(encoding="utf-8")

        tree = ast.parse(source)
        owners = []

        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue

            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue

                func = child.func

                if not (
                    isinstance(func, ast.Attribute)
                    and func.attr == "execute"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "tools"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "self"
                ):
                    continue

                owners.append(node.name)

        self.assertEqual(
            owners,
            ["_tool"],
        )


if __name__ == "__main__":
    unittest.main()
