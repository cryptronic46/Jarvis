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
            "close_application",
            "get_current_time",
            "get_pre_request_telemetry",
            "get_synthetic_self_state",
            "set_master_volume",
            "set_mute",
            "lock_workstation",
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

        if name == "get_pre_request_telemetry":
            return json.dumps({
                "ok": True,
                "cpu_percent": 12.5,
                "memory_used_gib": 8.0,
                "memory_percent": 25.0,
                "gpu": [
                    {
                        "temperature_c": 44,
                        "utilization_percent": 21,
                        "memory_used_mib": 2048,
                        "memory_total_mib": 12288,
                    }
                ],
            })

        if name == "set_master_volume":
            return json.dumps({
                "ok": True,
                "volume_percent": (
                    arguments.get(
                        "percent"
                    )
                ),
            })

        if name in {
            "set_mute",
            "lock_workstation",
            "close_application",
        }:
            return json.dumps({
                "ok": True,
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

    def test_current_telemetry_is_semantically_resolved(
        self,
    ):
        cases = (
            (
                "Qual \u00e9 a temperatura atual da GPU?",
                "read_gpu_telemetry",
                "gpu",
            ),
            (
                "Qual \u00e9 a utiliza\u00e7\u00e3o da CPU agora?",
                "read_cpu_telemetry",
                "cpu",
            ),
            (
                "Quanto estou a usar de RAM?",
                "read_ram_telemetry",
                "ram",
            ),
            (
                (
                    "Faz um resumo do estado "
                    "atual do computador"
                ),
                "read_system_telemetry",
                "system_telemetry",
            ),
            (
                "Mostra CPU RAM GPU",
                "read_combined_telemetry",
                "system_telemetry",
            ),
        )

        for text, action, target in cases:
            with self.subTest(
                text=text
            ):
                request = resolve_semantic_request(
                    text
                )

                self.assertEqual(
                    request.intent,
                    "OPERATIONAL_ACTION",
                )

                self.assertEqual(
                    request.action,
                    action,
                )

                self.assertEqual(
                    request.target,
                    target,
                )

                self.assertEqual(
                    request.preferred_tool,
                    (
                        "get_pre_request_telemetry"
                    ),
                )

                self.assertEqual(
                    request.as_dict()[
                        "tool_arguments"
                    ],
                    {},
                )

                self.assertEqual(
                    request.confidence,
                    0.99,
                )

    def test_structured_telemetry_executes_without_reparsing_text(
        self,
    ):
        cases = (
            (
                "Qual \u00e9 a temperatura atual da GPU?",
                "gpu_status",
            ),
            (
                "Qual \u00e9 a utiliza\u00e7\u00e3o da CPU agora?",
                "cpu_status",
            ),
            (
                "Quanto estou a usar de RAM?",
                "ram_status",
            ),
            (
                (
                    "Faz um resumo do estado "
                    "atual do computador"
                ),
                "system_status",
            ),
            (
                "Mostra CPU RAM GPU",
                "combined_telemetry",
            ),
        )

        for semantic_text, expected_route in cases:
            with self.subTest(
                semantic_text=semantic_text
            ):
                router, tools, _events = (
                    _router()
                )

                request = resolve_semantic_request(
                    semantic_text
                )

                result = router.dispatch(
                    (
                        "texto neutro sem qualquer "
                        "palavra de telemetria"
                    ),
                    request=request,
                )

                self.assertTrue(
                    result.handled
                )

                self.assertEqual(
                    result.route,
                    expected_route,
                )

                self.assertEqual(
                    tools.calls,
                    [
                        (
                            "get_pre_request_telemetry",
                            {},
                        ),
                    ],
                )

    def test_telemetry_action_is_required_for_structured_executor(
        self,
    ):
        from jarvis_core.services.semantic_request import (
            StructuredRequest,
        )

        router, tools, _events = _router()

        request = StructuredRequest(
            raw_text="semantic contract",
            effective_text="semantic contract",
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="unknown_telemetry_action",
            target="system",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        result = router.dispatch(
            "texto completamente neutro",
            request=request,
        )

        self.assertFalse(
            result.handled
        )

        self.assertEqual(
            tools.calls,
            [],
        )

    def test_volume_semantics_own_tool_and_arguments(
        self,
    ):
        router, tools, _events = _router()

        text = "Coloca o volume a 30%"

        request = resolve_semantic_request(
            text
        )

        self.assertEqual(
            request.intent,
            "OPERATIONAL_ACTION",
        )

        self.assertEqual(
            request.preferred_tool,
            "set_master_volume",
        )

        self.assertEqual(
            request.as_dict()[
                "tool_arguments"
            ],
            {
                "percent": 30,
            },
        )

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertTrue(
            result.handled
        )

        self.assertEqual(
            result.route,
            "volume_set",
        )

        self.assertEqual(
            tools.calls,
            [
                (
                    "set_master_volume",
                    {
                        "percent": 30,
                    },
                ),
            ],
        )

    def test_mute_and_unmute_are_semantic_operations(
        self,
    ):
        cases = (
            (
                "Silencia o \u00e1udio",
                True,
                "mute",
            ),
            (
                "Ativa o som",
                False,
                "unmute",
            ),
        )

        for text, muted, route in cases:
            with self.subTest(
                text=text
            ):
                router, tools, _events = (
                    _router()
                )

                request = resolve_semantic_request(
                    text
                )

                self.assertEqual(
                    request.preferred_tool,
                    "set_mute",
                )

                self.assertEqual(
                    request.as_dict()[
                        "tool_arguments"
                    ],
                    {
                        "muted": muted,
                    },
                )

                result = router.dispatch(
                    text,
                    request=request,
                )

                self.assertTrue(
                    result.handled
                )

                self.assertEqual(
                    result.route,
                    route,
                )

                self.assertEqual(
                    tools.calls,
                    [
                        (
                            "set_mute",
                            {
                                "muted": muted,
                            },
                        ),
                    ],
                )

    def test_lock_is_resolved_before_fast_execution(
        self,
    ):
        router, tools, _events = _router()

        text = "Bloqueia o computador"

        request = resolve_semantic_request(
            text
        )

        self.assertEqual(
            request.action,
            "lock",
        )

        self.assertEqual(
            request.preferred_tool,
            "lock_workstation",
        )

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertTrue(
            result.handled
        )

        self.assertEqual(
            result.route,
            "lock_pc",
        )

        self.assertEqual(
            tools.calls,
            [
                (
                    "lock_workstation",
                    {},
                ),
            ],
        )

    def test_close_known_app_has_authoritative_tool_contract(
        self,
    ):
        router, tools, _events = _router()

        text = "Fecha o Brave"

        request = resolve_semantic_request(
            text,
            app_aliases={
                "brave": "brave",
            },
        )

        self.assertEqual(
            request.action,
            "close",
        )

        self.assertEqual(
            request.preferred_tool,
            "close_application",
        )

        self.assertEqual(
            request.as_dict()[
                "tool_arguments"
            ],
            {
                "app_name": "brave",
            },
        )

        result = router.dispatch(
            text,
            request=request,
        )

        self.assertTrue(
            result.handled
        )

        self.assertEqual(
            result.route,
            "app_close",
        )

        self.assertEqual(
            tools.calls,
            [
                (
                    "close_application",
                    {
                        "app_name": "brave",
                    },
                ),
            ],
        )

    def test_structured_request_executes_without_reparsing_text(
        self,
    ):
        from jarvis_core.services.semantic_request import (
            StructuredRequest,
        )

        router, tools, _events = _router()

        request = StructuredRequest(
            raw_text="semantic contract",
            effective_text="semantic contract",
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="set_mute",
            target="master_audio",
            requires_tool=True,
            preferred_tool="set_mute",
            tool_arguments={
                "muted": False,
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

        result = router.dispatch(
            (
                "texto que n\u00e3o cont\u00e9m "
                "qualquer comando de \u00e1udio"
            ),
            request=request,
        )

        self.assertTrue(
            result.handled
        )

        self.assertEqual(
            result.route,
            "unmute",
        )

        self.assertEqual(
            tools.calls,
            [
                (
                    "set_mute",
                    {
                        "muted": False,
                    },
                ),
            ],
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
            "    def terminal_event_printer(",
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
            2,
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
            3,
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


    def test_explicit_memory_write_has_authoritative_semantic_contract(
        self,
    ):
        cases = (
            (
                (
                    "Jarvis, memoriza que o c\u00f3digo "
                    "de valida\u00e7\u00e3o D414 "
                    "\u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo de valida\u00e7\u00e3o "
                    "D414 \u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "memoriza que o c\u00f3digo "
                    "de valida\u00e7\u00e3o D414 "
                    "\u00e9 VERDE-8417"
                ),
                (
                    "o c\u00f3digo de valida\u00e7\u00e3o "
                    "D414 \u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, memoriza isto: "
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, guarda na mem\u00f3ria "
                    "que o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, lembra-te que "
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, quero que te recordes "
                    "que o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo D414 "
                    "\u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, o nome da minha mulher "
                    "\u00e9 ISA e quero que guardes "
                    "essa informa\u00e7\u00e3o na tua "
                    "mem\u00f3ria. Isto \u00e9 uma ordem!"
                ),
                (
                    "o nome da minha mulher "
                    "\u00e9 ISA"
                ),
            ),
            (
                (
                    "Quero que guardes na tua "
                    "mem\u00f3ria que a minha mulher "
                    "se chama ISA."
                ),
                (
                    "a minha mulher se chama ISA"
                ),
            ),
            (
                (
                    "Jarvis, guarda esta "
                    "informa\u00e7\u00e3o na tua "
                    "mem\u00f3ria: o c\u00f3digo "
                    "D415 \u00e9 VERDE-8417."
                ),
                (
                    "o c\u00f3digo D415 "
                    "\u00e9 VERDE-8417"
                ),
            ),
            (
                (
                    "Jarvis, memoriza o nome da minha "
                    "mulher: Ana Isa Guimar\u00e3es Lopes, "
                    "e a data de nascimento: "
                    "27 de Fevereiro de 1987."
                ),
                (
                    "o nome da minha mulher: "
                    "Ana Isa Guimar\u00e3es Lopes, "
                    "e a data de nascimento: "
                    "27 de Fevereiro de 1987"
                ),
            ),
            (
                (
                    "Quero que memorizes o nome da "
                    "minha mulher e a data de "
                    "nascimento dela."
                ),
                (
                    "o nome da minha mulher e a "
                    "data de nascimento dela"
                ),
            ),
            (
                (
                    "Guarda o c\u00f3digo D415 "
                    "\u00e9 VERDE-8417 na tua "
                    "mem\u00f3ria."
                ),
                (
                    "o c\u00f3digo D415 "
                    "\u00e9 VERDE-8417"
                ),
            ),
        )

        for text, expected_fact in cases:
            with self.subTest(
                text=text
            ):
                request = (
                    resolve_semantic_request(
                        text
                    )
                )

                self.assertEqual(
                    request.intent,
                    "OPERATIONAL_ACTION",
                )

                self.assertEqual(
                    request.domain,
                    "owner_memory",
                )

                self.assertEqual(
                    request.subject,
                    "OWNER",
                )

                self.assertEqual(
                    request.action,
                    "remember_owner_fact",
                )

                self.assertEqual(
                    request.target,
                    "OWNER",
                )

                self.assertTrue(
                    request.requires_tool
                )

                self.assertEqual(
                    request.preferred_tool,
                    "remember_user_fact",
                )

                self.assertEqual(
                    request.as_dict()[
                        "tool_arguments"
                    ],
                    {
                        "fact": expected_fact,
                        "category":
                            "user_explicit",
                    },
                )

                self.assertEqual(
                    request.confidence,
                    0.99,
                )


    def test_explicit_memory_write_semantic_boundary_rejects_nonfacts(
        self,
    ):
        cases = (
            "Memoriza isso.",
            (
                "guarda o ficheiro relat\u00f3rio "
                "na pasta documentos"
            ),
        )

        for text in cases:
            with self.subTest(
                text=text
            ):
                request = (
                    resolve_semantic_request(
                        text
                    )
                )

                is_memory_write = (
                    request.intent
                    == "OPERATIONAL_ACTION"
                    and request.domain
                    == "owner_memory"
                    and request.action
                    == "remember_owner_fact"
                    and request.preferred_tool
                    == "remember_user_fact"
                )

                self.assertFalse(
                    is_memory_write
                )

    def test_structured_memory_write_executes_without_reparsing_text(
        self,
    ):
        router, tools, _events = (
            _router()
        )

        semantic_text = (
            "Jarvis, memoriza que o c\u00f3digo "
            "de valida\u00e7\u00e3o D414 "
            "\u00e9 VERDE-8417."
        )

        request = (
            resolve_semantic_request(
                semantic_text
            )
        )

        result = router.dispatch(
            (
                "texto neutro sem qualquer "
                "verbo de mem\u00f3ria"
            ),
            request=request,
        )

        self.assertTrue(
            result.handled
        )

        self.assertEqual(
            result.route,
            "memory_write",
        )

        self.assertEqual(
            tools.calls,
            [
                (
                    "remember_user_fact",
                    {
                        "fact": (
                            "o c\u00f3digo de "
                            "valida\u00e7\u00e3o D414 "
                            "\u00e9 VERDE-8417"
                        ),
                        "category":
                            "user_explicit",
                    },
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
