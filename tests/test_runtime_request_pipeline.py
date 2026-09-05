from pathlib import Path
from types import SimpleNamespace
import ast
import unittest

from jarvis_core.cli import route_runtime_request


APP_ALIASES = {
    "brave": "brave",
    "spotify": "spotify",
    "bloco de notas": "bloco de notas",
    "calculadora": "calculadora",
}


class FakeEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **payload):
        self.rows.append(
            (
                name,
                payload,
            )
        )


class FakeFastRouter:
    def __init__(
        self,
        *,
        handled,
        route="",
        response="",
    ):
        self.handled = handled
        self.route = route
        self.response = response
        self.calls = []

    def dispatch(
        self,
        text,
        *,
        voice_origin=False,
        request=None,
    ):
        self.calls.append(
            {
                "text": text,
                "voice_origin": voice_origin,
                "request": request,
            }
        )

        return SimpleNamespace(
            handled=self.handled,
            route=self.route,
            response=self.response,
        )


class FakeHybridBrain:
    def __init__(
        self,
        *,
        text="resposta local",
        route="LOCAL",
    ):
        self.text = text
        self.route = route
        self.calls = []
        self.results = []

    def ask(
        self,
        text,
        *,
        request=None,
    ):
        self.calls.append(
            {
                "text": text,
                "request": request,
            }
        )

        result = SimpleNamespace(
            text=self.text,
            route=self.route,
        )

        self.results.append(
            result
        )

        return result


class RuntimeRequestPipelineTests(
    unittest.TestCase
):
    def test_fast_path_uses_resolved_semantics_and_skips_hybrid(
        self,
    ):
        events = FakeEvents()

        fast = FakeFastRouter(
            handled=True,
            route="app_open",
            response="brave aberto.",
        )

        hybrid = FakeHybridBrain()

        before_calls = []

        def context_inputs():
            return (
                [],
                dict(APP_ALIASES),
            )

        answer, route, result_hybrid = (
            route_runtime_request(
                "Executa o Brave",
                source="terminal",
                semantic_context_inputs=context_inputs,
                events=events,
                fast_router=fast,
                hybrid_brain=hybrid,
                before_hybrid=lambda: (
                    before_calls.append(True)
                ),
            )
        )

        self.assertEqual(
            answer,
            "brave aberto.",
        )

        self.assertEqual(
            route,
            "FAST/app_open",
        )

        self.assertIsNone(
            result_hybrid
        )

        self.assertEqual(
            len(fast.calls),
            1,
        )

        request = fast.calls[0]["request"]

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            request.action,
            "open",
        )

        self.assertEqual(
            request.target,
            "brave",
        )

        self.assertEqual(
            request.preferred_tool,
            "open_application",
        )

        self.assertEqual(
            request.as_dict()[
                "tool_arguments"
            ],
            {
                "app_name": "brave",
            },
        )

        self.assertEqual(
            hybrid.calls,
            [],
        )

        self.assertEqual(
            before_calls,
            [],
        )

    def test_hybrid_receives_exact_same_structured_request(
        self,
    ):
        events = FakeEvents()

        fast = FakeFastRouter(
            handled=False,
        )

        hybrid = FakeHybridBrain(
            text="continuidade social",
            route="LOCAL/social",
        )

        before_calls = []

        recent = [
            {
                "user": "Provoca-me",
                "assistant": (
                    "Interacao social ativa."
                ),
                "route": (
                    "FAST/social_interaction"
                ),
            }
        ]

        def context_inputs():
            return (
                recent,
                dict(APP_ALIASES),
            )

        answer, route, result_hybrid = (
            route_runtime_request(
                "Mais.",
                source="terminal",
                semantic_context_inputs=context_inputs,
                events=events,
                fast_router=fast,
                hybrid_brain=hybrid,
                before_hybrid=lambda: (
                    before_calls.append(True)
                ),
            )
        )

        self.assertEqual(
            answer,
            "continuidade social",
        )

        self.assertEqual(
            route,
            "LOCAL/social",
        )

        self.assertEqual(
            len(hybrid.results),
            1,
        )

        self.assertIs(
            result_hybrid,
            hybrid.results[0],
        )

        self.assertEqual(
            len(fast.calls),
            1,
        )

        self.assertEqual(
            len(hybrid.calls),
            1,
        )

        fast_request = (
            fast.calls[0]["request"]
        )

        hybrid_request = (
            hybrid.calls[0]["request"]
        )

        self.assertIs(
            fast_request,
            hybrid_request,
        )

        self.assertEqual(
            fast_request.intent,
            "SOCIAL_INTERACTION",
        )

        self.assertFalse(
            fast_request.requires_tool
        )

        self.assertEqual(
            before_calls,
            [True],
        )

    def test_ambiguous_action_remains_fail_closed_into_hybrid(
        self,
    ):
        events = FakeEvents()

        fast = FakeFastRouter(
            handled=False,
        )

        hybrid = FakeHybridBrain()

        def context_inputs():
            return (
                [],
                dict(APP_ALIASES),
            )

        route_runtime_request(
            "Abre isso.",
            source="terminal",
            semantic_context_inputs=context_inputs,
            events=events,
            fast_router=fast,
            hybrid_brain=hybrid,
        )

        request = (
            hybrid.calls[0]["request"]
        )

        self.assertEqual(
            request.intent,
            "UNKNOWN",
        )

        self.assertFalse(
            request.requires_tool
        )

        self.assertIsNone(
            request.preferred_tool
        )

        self.assertIsNone(
            request.target
        )

        self.assertIs(
            fast.calls[0]["request"],
            request,
        )

    def test_voice_origin_is_forwarded_without_changing_semantics(
        self,
    ):
        events = FakeEvents()

        fast = FakeFastRouter(
            handled=False,
        )

        hybrid = FakeHybridBrain()

        def context_inputs():
            return (
                [],
                dict(APP_ALIASES),
            )

        route_runtime_request(
            "O que sabes sobre mim?",
            source="wake",
            semantic_context_inputs=context_inputs,
            events=events,
            fast_router=fast,
            hybrid_brain=hybrid,
        )

        self.assertTrue(
            fast.calls[0][
                "voice_origin"
            ]
        )

        self.assertEqual(
            fast.calls[0][
                "request"
            ].subject,
            "OWNER",
        )

    def test_semantic_event_reports_authoritative_contract(
        self,
    ):
        events = FakeEvents()

        fast = FakeFastRouter(
            handled=False,
        )

        hybrid = FakeHybridBrain()

        def context_inputs():
            return (
                [],
                dict(APP_ALIASES),
            )

        route_runtime_request(
            "Executa o Brave",
            source="terminal",
            semantic_context_inputs=context_inputs,
            events=events,
            fast_router=fast,
            hybrid_brain=hybrid,
        )

        semantic_events = [
            payload
            for name, payload
            in events.rows
            if name
            == "SEMANTIC_REQUEST_RESOLVED"
        ]

        self.assertEqual(
            len(semantic_events),
            1,
        )

        event = semantic_events[0]

        self.assertEqual(
            event["intent"],
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            event["action"],
            "open",
        )

        self.assertEqual(
            event["preferred_tool"],
            "open_application",
        )

        self.assertTrue(
            event["requires_tool"]
        )

    def test_real_cli_process_request_uses_tested_pipeline(
        self,
    ):
        path = Path(
            "jarvis_core/cli.py"
        )

        source = path.read_text(
            encoding="utf-8"
        )

        tree = ast.parse(source)

        process_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(
                node,
                ast.FunctionDef,
            )
            and node.name
            == "process_request"
        ]

        self.assertEqual(
            len(process_nodes),
            1,
        )

        process = process_nodes[0]

        segment = ast.get_source_segment(
            source,
            process,
        )

        self.assertIsNotNone(
            segment
        )

        self.assertIn(
            "route_runtime_request(",
            segment,
        )

        self.assertNotIn(
            "resolve_semantic_request(",
            segment,
        )

        self.assertNotIn(
            "fast_router.dispatch(",
            segment,
        )

        self.assertNotIn(
            "hybrid_brain.ask(",
            segment,
        )


if __name__ == "__main__":
    unittest.main()
