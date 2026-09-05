from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import SkillContext
from jarvis_core.skills.manager import SkillManager
from jarvis_core.skills.builtin.desktop_agent import DesktopAgentService
from jarvis_core.skills.builtin.memory_graph import MemoryGraphStore
from jarvis_core.skills.builtin.purple_team import PurpleTeamOrchestrator
from jarvis_core.skills.builtin.system_guardian import SystemGuardianService
from jarvis_core.skills.builtin.task_planner import AutonomousTaskPlanner
from jarvis_core.skills.builtin.vision import VisionService
from jarvis_core.skills.builtin.wallpaper_live import LiveWallpaperStateService


class FakeEvents:
    def __init__(self):
        self.rows = []
        self.subscribers = []

    def emit(self, name, **data):
        self.rows.append((name, data))
        event = SimpleNamespace(name=name, data=data, timestamp="2026-08-30T17:00:00+01:00")
        for callback in list(self.subscribers):
            callback(event)
        return event

    def subscribe(self, callback):
        self.subscribers.append(callback)


class FakeRegistry:
    def __init__(self, described=None, routed=None, results=None):
        self._described = described or []
        self._routed = routed or []
        self._results = results or {}
        self.registered = []
        self.calls = []
        self.names = {row["name"] for row in self._described}

    def register_skill_tool(self, **kwargs):
        self.registered.append(kwargs)
        self.names.add(kwargs["name"])
        self._described.append({
            "name": kwargs["name"],
            "description": kwargs["description"],
            "risk": kwargs["risk"].name,
            "skill_id": kwargs.get("skill_id"),
        })

    def describe(self):
        return list(self._described)

    def schemas_for_query(self, _goal, max_tools=28):
        return [
            {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}}}}
            for name in self._routed[:max_tools]
        ]

    def validate_arguments(self, name, arguments):
        if name not in self.names:
            return False, "unknown_tool"
        if not isinstance(arguments, dict):
            return False, "arguments_must_be_object"
        return True, None

    def execute(self, name, args):
        self.calls.append((name, dict(args or {})))
        value = self._results.get(name, {"ok": True, "tool": name, "arguments": args})
        if callable(value):
            value = value(args)
        return json.dumps(value)


class FakeClient:
    def __init__(self, contents=None, model_available=True):
        self.contents = list(contents or [])
        self.model_available = model_available
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        content = self.contents.pop(0) if self.contents else '{"steps":[]}'
        return SimpleNamespace(message=SimpleNamespace(content=content))

    def show(self, _model):
        if not self.model_available:
            raise RuntimeError("model missing")
        return {"ok": True}


class ModularSkillsTests(unittest.TestCase):
    def _settings(self, root: Path, **extra):
        values = dict(
            model="qwen3:8b",
            ollama_keep_alive="30m",
            task_planner_state_path=str(root / "task_plans.json"),
            task_planner_max_steps=8,
            task_planner_max_adaptations=1,
            purple_team_report_path=str(root / "purple.json"),
            guardian_baseline_path=str(root / "guardian_baseline.json"),
            guardian_state_path=str(root / "guardian_state.json"),
            guardian_interval_seconds=60,
            desktop_agent_screenshot_dir=str(root / "screens"),
            desktop_agent_max_windows=30,
            vision_enabled=True,
            vision_model="vision-test",
            native_llama_server_path=str(root / "missing-llama-server.exe"),
            vision_native_model_path=str(root / "missing-vision.gguf"),
            vision_native_mmproj_path=str(root / "missing-mmproj.gguf"),
            vision_native_state_path=str(root / "vision-runtime-state.json"),
            vision_camera_enabled=True,
            vision_camera_index=0,
            vision_capture_dir=str(root / "vision"),
            wallpaper_live_state_path=str(root / "live_hud.json"),
            wallpaper_live_interval_seconds=1.0,
            memory_graph_path=str(root / "graph.json"),
        )
        values.update(extra)
        return SimpleNamespace(**values)

    def _context(self, root: Path, registry=None, brain=None, **extra):
        services = extra.pop("services", {})
        return SkillContext(
            settings=self._settings(root, **extra),
            events=FakeEvents(),
            registry=registry or FakeRegistry(),
            brain=brain,
            services=services,
        )

    def test_desktop_agent_is_bounded_off_windows(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = self._context(Path(td))
            service = DesktopAgentService(ctx)
            with patch("jarvis_core.skills.builtin.desktop_agent.platform.system", return_value="Linux"):
                self.assertFalse(service.status()["available"])
                self.assertEqual(service.click(1, 1)["error"], "WINDOWS_ONLY")
                self.assertEqual(service.type_text("abc")["error"], "WINDOWS_ONLY")

    def test_memory_graph_extracts_explicit_partner_relation(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryGraphStore(Path(td) / "graph.json")
            result = store.ingest_explicit_fact(
                "A minha mulher chama-se Ana Isa Guimarães Lopes e nasceu a 27 de Fevereiro de 1987.",
                "relationship",
            )
            self.assertTrue(result["ok"])
            self.assertTrue(any(row["relation"] == "PARTNER" for row in result["extracted"]))
            recalled = store.recall("Ana Isa")
            self.assertTrue(any(row.get("relation") == "PARTNER" for row in recalled["edges"]))

    def test_purple_team_denies_non_lab_before_kali(self):
        with tempfile.TemporaryDirectory() as td:
            service = PurpleTeamOrchestrator(self._context(Path(td)))
            with patch("jarvis_core.skills.builtin.purple_team.classify_cyber_target", return_value={"scope": "EXTERNAL", "authorized": False, "ip": "8.8.8.8"}), \
                 patch("jarvis_core.skills.builtin.purple_team.get_kali_bridge_status") as bridge:
                result = service.run("8.8.8.8")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "PURPLE_TEAM_TARGET_NOT_LAB")
            bridge.assert_not_called()

    def test_purple_team_uses_only_bounded_profiles_in_lab(self):
        with tempfile.TemporaryDirectory() as td:
            service = PurpleTeamOrchestrator(self._context(Path(td)))
            with patch("jarvis_core.skills.builtin.purple_team.classify_cyber_target", return_value={"scope": "LAB", "authorized": True, "ip": "192.168.56.10"}), \
                 patch("jarvis_core.skills.builtin.purple_team.get_kali_bridge_status", return_value={"ok": True, "configured": True, "ready_scope": True}), \
                 patch("jarvis_core.skills.builtin.purple_team.run_kali_nmap_service_scan", return_value={"ok": True, "requested_ports": [80,445], "open_services": [{"port":80,"name":"http"},{"port":445,"name":"microsoft-ds"}]}), \
                 patch("jarvis_core.skills.builtin.purple_team.run_kali_whatweb_fingerprint", return_value={"ok": True, "report": "Apache"}) as whatweb, \
                 patch("jarvis_core.skills.builtin.purple_team.run_kali_nikto_safe_web_scan", return_value={"ok": True, "report": "X-Frame-Options not present"}) as nikto:
                result = service.run("192.168.56.10", [80, 445])
            self.assertTrue(result["ok"])
            self.assertIn("no exploitation", result["boundaries"])
            self.assertTrue(any("SMB" in row["finding"] for row in result["recommendations"]))
            whatweb.assert_called_once(); nikto.assert_called_once()

    def test_guardian_detects_new_listener_and_integrity_change(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            service = SystemGuardianService(self._context(root))
            old = {"captured_at":"old","startup":[],"listeners":[],"processes":[],"release_integrity":{"ok":True}}
            service.baseline_path.write_text(json.dumps({"created_at":"old","snapshot":old}), encoding="utf-8")
            current = {"captured_at":"now","startup":[],"listeners":[{"ip":"127.0.0.1","port":9999,"pid":1,"process":"x","exe":"C:/x.exe"}],"processes":[],"release_integrity":{"ok":False,"mismatches":["jarvis_core/x.py"],"missing":[]}}
            with patch.object(service, "snapshot", return_value=current):
                result = service.scan()
            codes = {row["code"] for row in result["alerts"]}
            self.assertIn("NEW_LISTENER", codes)
            self.assertIn("JARVIS_RELEASE_INTEGRITY_CHANGED", codes)

    def test_planner_pauses_on_confirmation_and_never_bypasses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [{"name":"desktop_click","description":"click","risk":"CONFIRM","skill_id":"desktop_agent"}]
            registry = FakeRegistry(rows, ["desktop_click"], {"desktop_click":{"ok":False,"confirmation_required":True,"token":"ABC123"}})
            brain = SimpleNamespace(client=FakeClient(['{"steps":[{"tool":"desktop_click","arguments":{"x":10,"y":20},"purpose":"clicar"}]}']))
            planner = AutonomousTaskPlanner(self._context(root, registry=registry, brain=brain))
            result = planner.run_goal("clica no botão indicado")
            self.assertTrue(result["execution"]["waiting_confirmation"])
            self.assertEqual(result["execution"]["token"], "ABC123")
            self.assertFalse(planner.status()["confirmation_bypass"])

    def test_planner_adapts_once_after_real_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"name":"probe","description":"probe","risk":"LOW","skill_id":"x"},
                {"name":"inspect","description":"inspect","risk":"READ_ONLY","skill_id":"x"},
            ]
            registry = FakeRegistry(rows, ["probe", "inspect"], {
                "probe":{"ok":False,"error":"TEMP_FAILURE"},
                "inspect":{"ok":True,"detail":"fallback evidence"},
            })
            brain = SimpleNamespace(client=FakeClient([
                '{"steps":[{"tool":"probe","arguments":{},"purpose":"primeiro"}]}',
                '{"steps":[{"tool":"inspect","arguments":{},"purpose":"adaptar com observação"}]}',
            ]))
            planner = AutonomousTaskPlanner(self._context(root, registry=registry, brain=brain))
            result = planner.run_goal("resolve o diagnóstico")
            self.assertTrue(result["ok"])
            self.assertTrue(result["adaptation"]["ok"])
            plan = result["execution"]["plan"]
            self.assertEqual(plan["adaptations"], 1)
            self.assertEqual(plan["steps"][-1]["tool"], "inspect")
            self.assertEqual(plan["steps"][-1]["status"], "completed")

    def test_planner_vague_fallback_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            rows = [
                {"name":"run_autonomous_task","description":"planner","risk":"LOW","skill_id":"task_planner"},
                {"name":"read_state","description":"read","risk":"READ_ONLY","skill_id":"x"},
                {"name":"write_state","description":"write","risk":"LOW","skill_id":"x"},
            ]
            registry = FakeRegistry(rows, ["run_autonomous_task"])
            planner = AutonomousTaskPlanner(self._context(Path(td), registry=registry, brain=SimpleNamespace(client=FakeClient())))
            tools = planner._candidate_tools("resolve isto")
            self.assertIn("read_state", {row["name"] for row in tools})
            self.assertNotIn("write_state", {row["name"] for row in tools})

    def test_planner_explicit_observation_goal_exposes_read_only_only(self):
        with tempfile.TemporaryDirectory() as td:
            rows = [
                {
                    "name": "inspect_application",
                    "description": "inspect",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "open_application",
                    "description": "open",
                    "risk": "LOW",
                    "skill_id": "x",
                },
                {
                    "name": "close_application",
                    "description": "close",
                    "risk": "CONFIRM",
                    "skill_id": "x",
                },
            ]

            registry = FakeRegistry(
                rows,
                [
                    "inspect_application",
                    "open_application",
                    "close_application",
                ],
            )

            planner = AutonomousTaskPlanner(
                self._context(
                    Path(td),
                    registry=registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            tools = planner._candidate_tools(
                "Verifica se o Spotify esta disponivel, "
                "sem abrir nem fechar nenhuma aplicacao."
            )

            self.assertEqual(
                {
                    row["name"]
                    for row in tools
                },
                {
                    "inspect_application",
                },
            )

            self.assertTrue(
                all(
                    row["risk"] == "READ_ONLY"
                    for row in tools
                )
            )

            network_rows = [
                {
                    "name": "get_network_security_snapshot",
                    "description": "read network",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "label_network_device",
                    "description": "label network device",
                    "risk": "LOW",
                    "skill_id": "x",
                },
            ]

            network_registry = FakeRegistry(
                network_rows,
                [
                    "get_network_security_snapshot",
                    "label_network_device",
                ],
            )

            network_planner = AutonomousTaskPlanner(
                self._context(
                    Path(td),
                    registry=network_registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            network_tools = network_planner._candidate_tools(
                "Inspeciona apenas o estado da rede, "
                "sem alterar, atualizar ou etiquetar dispositivos."
            )

            self.assertEqual(
                {
                    row["name"]
                    for row in network_tools
                },
                {
                    "get_network_security_snapshot",
                },
            )

            self.assertTrue(
                all(
                    row["risk"] == "READ_ONLY"
                    for row in network_tools
                )
            )

            self.assertNotIn(
                "refresh_network_inventory",
                {
                    row["name"]
                    for row in network_tools
                },
            )

            self.assertNotIn(
                "label_network_device",
                {
                    row["name"]
                    for row in network_tools
                },
            )

            pdf_rows = [
                {
                    "name": "get_book_library_status",
                    "description": "status",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "build_local_file_index",
                    "description": "index",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "sync_book_library",
                    "description": "sync",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
            ]

            pdf_registry = FakeRegistry(
                pdf_rows,
                [
                    "get_book_library_status",
                    "build_local_file_index",
                    "sync_book_library",
                ],
            )

            pdf_planner = AutonomousTaskPlanner(
                self._context(
                    Path(td),
                    registry=pdf_registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            pdf_tools = pdf_planner._candidate_tools(
                "Mostra apenas o estado da biblioteca PDF, "
                "sem indexar nem sincronizar ficheiros."
            )

            self.assertEqual(
                {
                    row["name"]
                    for row in pdf_tools
                },
                {
                    "get_book_library_status",
                },
            )

            mixed_rows = [
                {
                    "name": "inspect_application",
                    "description": "inspect",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "open_application",
                    "description": "open",
                    "risk": "LOW",
                    "skill_id": "x",
                },
                {
                    "name": "get_master_volume",
                    "description": "volume",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "set_master_volume",
                    "description": "set volume",
                    "risk": "LOW",
                    "skill_id": "x",
                },
                {
                    "name": "set_mute",
                    "description": "mute",
                    "risk": "LOW",
                    "skill_id": "x",
                },
            ]

            mixed_registry = FakeRegistry(
                mixed_rows,
                [
                    "inspect_application",
                    "open_application",
                    "get_master_volume",
                    "set_master_volume",
                    "set_mute",
                ],
            )

            mixed_planner = AutonomousTaskPlanner(
                self._context(
                    Path(td),
                    registry=mixed_registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            mixed_tools = mixed_planner._candidate_tools(
                "Abre o Spotify, mas sem alterar o volume."
            )

            mixed_names = {
                row["name"]
                for row in mixed_tools
            }

            self.assertIn(
                "open_application",
                mixed_names,
            )

            self.assertNotIn(
                "set_master_volume",
                mixed_names,
            )

            self.assertNotIn(
                "set_mute",
                mixed_names,
            )

    def test_planner_explicit_mutation_goal_keeps_low_tool(self):
        with tempfile.TemporaryDirectory() as td:
            rows = [
                {
                    "name": "inspect_application",
                    "description": "inspect",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "open_application",
                    "description": "open",
                    "risk": "LOW",
                    "skill_id": "x",
                },
            ]

            registry = FakeRegistry(
                rows,
                [
                    "inspect_application",
                    "open_application",
                ],
            )

            planner = AutonomousTaskPlanner(
                self._context(
                    Path(td),
                    registry=registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            tools = planner._candidate_tools(
                "Abre o Spotify."
            )

            self.assertIn(
                "open_application",
                {
                    row["name"]
                    for row in tools
                },
            )

    def test_planner_revalidates_persisted_tool_against_original_goal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            rows = [
                {
                    "name": "inspect_application",
                    "description": "inspect",
                    "risk": "READ_ONLY",
                    "skill_id": "x",
                },
                {
                    "name": "open_application",
                    "description": "open",
                    "risk": "LOW",
                    "skill_id": "x",
                },
            ]

            registry = FakeRegistry(
                rows,
                [
                    "inspect_application",
                    "open_application",
                ],
            )

            planner = AutonomousTaskPlanner(
                self._context(
                    root,
                    registry=registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            plan = {
                "id": "authority01",
                "goal": (
                    "Verifica se o Spotify esta disponivel, "
                    "sem abrir nenhuma aplicacao."
                ),
                "created_at": "old",
                "updated_at": "old",
                "status": "planned",
                "adaptations": 0,
                "steps": [
                    {
                        "id": 1,
                        "tool": "open_application",
                        "arguments": {
                            "app_name": "spotify",
                        },
                        "purpose": "tampered step",
                        "risk": "LOW",
                        "status": "pending",
                        "result": None,
                        "confirmation_token": None,
                    }
                ],
            }

            planner._save(
                {
                    "plans": {
                        plan["id"]: plan,
                    },
                }
            )

            result = planner.execute_plan(
                plan["id"],
                max_steps=1,
            )

            self.assertFalse(
                result["ok"]
            )

            self.assertEqual(
                result["error"],
                "TOOL_OUTSIDE_GOAL_AUTHORITY",
            )

            self.assertEqual(
                registry.calls,
                [],
            )

    def test_planner_revalidates_arguments_immediately_before_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            rows = [
                {
                    "name": "open_application",
                    "description": "open",
                    "risk": "LOW",
                    "skill_id": "x",
                },
            ]

            registry = FakeRegistry(
                rows,
                [
                    "open_application",
                ],
            )

            def validate_arguments(name, arguments):
                if (
                    name == "open_application"
                    and arguments
                    == {
                        "app_name": "spotify",
                    }
                ):
                    return True, None

                return False, "invalid_test_arguments"

            registry.validate_arguments = (
                validate_arguments
            )

            planner = AutonomousTaskPlanner(
                self._context(
                    root,
                    registry=registry,
                    brain=SimpleNamespace(
                        client=FakeClient()
                    ),
                )
            )

            plan = {
                "id": "authority02",
                "goal": "Abre o Spotify.",
                "created_at": "old",
                "updated_at": "old",
                "status": "planned",
                "adaptations": 0,
                "steps": [
                    {
                        "id": 1,
                        "tool": "open_application",
                        "arguments": {
                            "app_name": "steam",
                        },
                        "purpose": "invalid arguments",
                        "risk": "LOW",
                        "status": "pending",
                        "result": None,
                        "confirmation_token": None,
                    }
                ],
            }

            planner._save(
                {
                    "plans": {
                        plan["id"]: plan,
                    },
                }
            )

            result = planner.execute_plan(
                plan["id"],
                max_steps=1,
            )

            self.assertFalse(
                result["ok"]
            )

            self.assertEqual(
                result["error"],
                "INVALID_TOOL_ARGUMENTS",
            )

            self.assertEqual(
                registry.calls,
                [],
            )

    def test_vision_missing_model_fails_gracefully_without_cloud(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            desktop = SimpleNamespace(capture_screen=lambda: {"ok": True, "path": str(root / "screen.png")})
            brain = SimpleNamespace(client=FakeClient(model_available=False))
            service = VisionService(self._context(root, brain=brain, services={"desktop_agent": desktop}))
            result = service.analyze("o que vês?")
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "VISION_MODEL_NOT_INSTALLED")
            self.assertIn("setup_vision.ps1", result["message"])

    def test_vision_camera_dependency_is_optional(self):
        with tempfile.TemporaryDirectory() as td:
            service = VisionService(self._context(Path(td), brain=SimpleNamespace(client=FakeClient())))
            with patch.object(service, "_camera_dependency", return_value=(False, "OPENCV_NOT_INSTALLED")):
                result = service.capture_camera()
            self.assertEqual(result["error"], "OPENCV_NOT_INSTALLED")

    def test_live_wallpaper_state_tracks_skill_tool_and_guardian(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = FakeRegistry([{"name":"x_tool","description":"x","risk":"LOW","skill_id":"x_skill"}])
            ctx = self._context(root, registry=registry)
            service = LiveWallpaperStateService(ctx)
            service._active = True
            service._on_event(SimpleNamespace(name="TOOL_EXECUTING", data={"tool":"x_tool"}, timestamp="t"))
            service._on_event(SimpleNamespace(
                name="SYSTEM_GUARDIAN_ALERT",
                data={"count":3,"severity_counts":{"critical":1,"high":1,"attention":1,"other":0,"total":3}},
                timestamp="t",
            ))
            state = service.state()
            self.assertEqual(state["active_tool"], "x_tool")
            self.assertEqual(state["active_skill"], "x_skill")
            self.assertEqual(state["guardian_alert_count"], 3)
            self.assertEqual(state["guardian"]["critical"], 1)
            self.assertEqual(state["guardian"]["high"], 1)
            self.assertEqual(state["guardian"]["attention"], 1)
            self.assertEqual(state["mode"], "ALERT")
            self.assertTrue(Path(ctx.settings.wallpaper_live_state_path).is_file())

    def test_external_skill_digest_change_requires_retrust(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skills_root = root / "skills"; pkg = skills_root / "demo"; pkg.mkdir(parents=True)
            (pkg / "skill.json").write_text(json.dumps({"id":"demo.skill","name":"Demo","version":"1.0","entrypoint":"skill.py"}), encoding="utf-8")
            (pkg / "skill.py").write_text(
                "from jarvis_core.skills.base import Skill\n"
                "class Demo(Skill):\n    skill_id='demo.skill'\n"
                "def create_skill(context): return Demo(context)\n",
                encoding="utf-8",
            )
            trust = root / "trust.json"
            manager = SkillManager(self._context(root), external_root=skills_root, trust_path=trust)
            granted = manager.trust_external(pkg)
            self.assertTrue(granted["ok"])
            (pkg / "skill.py").write_text((pkg / "skill.py").read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
            manager2 = SkillManager(self._context(root), external_root=skills_root, trust_path=trust)
            manager2.load_external()
            self.assertNotIn("demo.skill", manager2.skills)
            self.assertTrue(any("changed after OWNER trust" in row["error"] for row in manager2.load_errors))

    def test_skill_manager_loads_all_builtins_and_registers_tools(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = FakeRegistry()
            context = self._context(root, registry=registry)
            manager = SkillManager(context, external_root=root / "external", trust_path=root / "trust.json", external_enabled=False)
            manager.load_builtins()
            self.assertEqual(manager.load_errors, [])
            self.assertEqual(len(manager.skills), 9)
            names = {row["name"] for row in registry.registered}
            for tool in [
                "desktop_observe", "run_purple_team_assessment", "run_system_guardian_scan",
                "run_autonomous_task", "recall_memory_graph", "get_live_wallpaper_state",
                "analyze_current_screen", "run_self_diagnostics", "get_skills_status",
            ]:
                self.assertIn(tool, names)

    def test_tool_registry_routes_skill_declared_keywords(self):
        source = (Path(__file__).resolve().parents[1] / "jarvis_core" / "core" / "tool_registry.py").read_text(encoding="utf-8")
        self.assertIn("if not tool.keywords", source)
        self.assertIn("for tool_name, tool in self._tools.items()", source)
        self.assertIn("self._normalize_query(marker) in text", source)
        self.assertIn("register_skill_tool", source)

    def test_builtin_skill_catalog_contains_all_nine_capabilities(self):
        names = "\n".join(SkillManager.BUILTIN_MODULES)
        for expected in [
            "desktop_agent", "purple_team", "system_guardian", "task_planner",
            "memory_graph", "wallpaper_live", "vision", "self_repair", "meta",
        ]:
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
