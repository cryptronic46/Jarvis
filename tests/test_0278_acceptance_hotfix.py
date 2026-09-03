import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

if "winreg" not in sys.modules:
    fake_winreg = ModuleType("winreg")
    fake_winreg.__getattr__ = lambda name: 0
    sys.modules["winreg"] = fake_winreg

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.config import Settings
from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.core.hybrid_brain import HybridRoutePolicy
from jarvis_core.core.local_llm import NativeLlamaClient
from jarvis_core.core.tool_registry import ToolRegistry
from jarvis_core.services.autonomy import parse_direct_external_learning_order
from jarvis_core.services.local_research import LocalResearchEngine
from jarvis_core.services.user_memory import UserMemoryStore
from jarvis_core.skills.base import SkillContext
from jarvis_core.skills.builtin.desktop_agent import DesktopAgentSkill


class _Events:
    def __init__(self):
        self.rows = []
    def emit(self, name, **payload):
        self.rows.append((name, payload))


class _Security:
    def register(self, *args, **kwargs):
        return None


class _Telemetry:
    def __init__(self, samples=None):
        self.samples = list(samples or [])
    def recent(self, seconds=10):
        return list(self.samples)
    def latest(self):
        return self.samples[-1] if self.samples else {}
    def latest_before(self, _when):
        return self.latest()


class _Tools:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.request_started_at = None
    def execute(self, name, args):
        self.calls.append((name, dict(args or {})))
        return json.dumps(self.responses[name], ensure_ascii=False)


class _Apps:
    def list_apps(self):
        return []
    def diagnose(self, *args, **kwargs):
        return {"ok": True}
    def open(self, *args, **kwargs):
        return {"ok": True}
    def close(self, *args, **kwargs):
        return {"ok": True}


class AcceptanceHotfix0278Tests(unittest.TestCase):
    def test_external_ai_requests_are_hard_blocked(self):
        policy = HybridRoutePolicy(Settings())
        for query in (
            "Consulta outra inteligência artificial para responder à minha próxima pergunta.",
            "Usa o ChatGPT para analisar isto",
            "/cloud explica isto",
            "/sol resolve isto",
        ):
            decision = policy.decide(query, cloud_available=True)
            self.assertEqual(decision.route, "external_ai_blocked")
            self.assertEqual(decision.reason, "external_ai_hard_block")

    def test_legacy_external_ai_settings_are_revoked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "external_ai_enabled": True,
                "cloud_enabled": True,
                "expert_escalation_enabled": True,
                "cloud_fallback_on_local_error": True,
            }), encoding="utf-8")
            Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["external_ai_enabled"])
            self.assertFalse(data["cloud_enabled"])
            self.assertFalse(data["expert_escalation_enabled"])
            self.assertFalse(data["cloud_fallback_on_local_error"])

    def test_web_research_extracts_python_subject(self):
        subject = HybridRoutePolicy(Settings()).research_subject(
            "Pesquisa na web qual é a versão atual do Python e explica-me resumidamente."
        )
        self.assertIn("Python", subject)
        self.assertNotIn("Pesquisa", subject)
        self.assertNotIn("explica-me", subject)

    def test_direct_url_study_extracts_question_and_is_authorized_order(self):
        parsed = parse_direct_external_learning_order(
            "Estuda https://www.python.org/downloads/ e diz-me qual é a versão atual do Python."
        )
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["source_url"], "https://www.python.org/downloads/")
        self.assertIn("Python", parsed["topic"])
        self.assertNotIn("http", parsed["topic"])

    def test_version_words_do_not_make_relevance_filter_reject_python(self):
        details = LocalResearchEngine._relevance_details(
            "a versão atual do Python",
            "Python Downloads | Python.org | Download the latest Python 3 release",
        )
        self.assertTrue(details["ok"])
        self.assertEqual(details["terms"], ["python"])

    def test_memory_recall_returns_most_relevant_fact_not_tail_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            defaults = Path(tmp) / "default.json"
            defaults.write_text('{"name":"Tiago","address_as":"Senhor"}', encoding="utf-8")
            store = UserMemoryStore(Path(tmp) / "memory", defaults)
            for i in range(8):
                store.remember(f"facto irrelevante número {i}")
            store.remember("o código de teste desta sessão é AZUL-4729", "user_explicit")
            for i in range(8, 16):
                store.remember(f"outro facto irrelevante número {i}")
            result = store.recall("código de teste", limit=3)
            self.assertTrue(result["facts"])
            self.assertIn("AZUL-4729", result["facts"][0]["fact"])

    def test_recent_telemetry_is_aggregated_before_llm(self):
        samples = [
            {"sampled_at":"a", "cpu_percent":10, "memory_percent":40, "memory_used_gib":12,
             "gpu":[{"utilization_percent":5, "temperature_c":45, "memory_used_mib":7000}]},
            {"sampled_at":"b", "cpu_percent":20, "memory_percent":42, "memory_used_gib":13,
             "gpu":[{"utilization_percent":15, "temperature_c":47, "memory_used_mib":7100}]},
        ]
        fake = SimpleNamespace(telemetry=_Telemetry(samples))
        result = ToolRegistry._recent_telemetry(fake, 60)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["cpu_percent"]["avg"], 15.0)
        self.assertNotIn("samples", result)

    def test_llama_tool_schema_sanitizer_removes_grammar_constraints(self):
        unsafe = [{"type":"function","function":{
            "name":"desktop_type_text",
            "description":"x",
            "parameters":{"type":"object","properties":{
                "text":{"type":"string","maxLength":2000},
                "count":{"type":"integer","minimum":0,"maximum":3},
                "keys":{"type":"array","items":{"type":"string"},"minItems":1,"maxItems":4},
            },"required":["text"],"additionalProperties":False},
        }}]
        safe = NativeLlamaClient._llama_safe_tools(unsafe)[0]["function"]["parameters"]
        rendered = json.dumps(safe)
        for forbidden in ("maxLength", "minimum", "maximum", "minItems", "maxItems", "additionalProperties"):
            self.assertNotIn(forbidden, rendered)
        self.assertIn('"required"', rendered)

    def test_desktop_keywords_no_longer_route_windows_os_to_every_desktop_tool(self):
        ctx = SkillContext(settings=SimpleNamespace(
            desktop_agent_screenshot_dir="memory/screenshots", desktop_agent_max_windows=50
        ), events=_Events(), registry=None)
        tools = DesktopAgentSkill(ctx).tools()
        for tool in tools:
            self.assertNotIn("windows", tuple(x.lower() for x in tool.keywords))

    def test_system_schema_selection_prefers_only_system_status_for_windows_version(self):
        events = _Events()
        registry = ToolRegistry(events, _Security(), _Telemetry(), _Apps())
        ctx = SkillContext(settings=SimpleNamespace(
            desktop_agent_screenshot_dir="memory/screenshots", desktop_agent_max_windows=50
        ), events=events, registry=registry)
        for tool in DesktopAgentSkill(ctx).tools():
            registry.register_skill_tool(
                name=tool.name, description=tool.description, func=tool.func,
                schema=tool.schema(), risk=tool.risk, keywords=tool.keywords,
                skill_id="desktop_agent",
            )
        names = [x["function"]["name"] for x in registry.schemas_for_query(
            "Qual é a versão do Windows que estou a utilizar?", max_tools=20
        )]
        self.assertIn("get_system_status", names)
        self.assertFalse(any(name.startswith("desktop_") for name in names))

    def test_fast_system_summary_uses_one_telemetry_call_and_includes_gpu(self):
        tools = _Tools({"get_pre_request_telemetry": {
            "cpu_percent": 13.9, "memory_percent": 43.6, "memory_used_gib": 13.82,
            "gpu": [{"utilization_percent": 6, "temperature_c": 43,
                     "memory_used_mib": 7168, "memory_total_mib": 12185}],
        }})
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("Como está o meu computador neste momento? Diz-me CPU, RAM e GPU.")
        self.assertTrue(result.handled)
        self.assertEqual([x[0] for x in tools.calls], ["get_pre_request_telemetry"])
        self.assertIn("GPU", result.response)
        self.assertIn("RAM", result.response)

    def test_fast_desktop_status_and_list_do_not_need_llm_grammar(self):
        tools = _Tools({
            "desktop_agent_status": {"ok": True, "available": True},
            "desktop_list_windows": {"ok": True, "count": 2, "windows": [
                {"title":"Windows PowerShell"}, {"title":"Brave"},
            ]},
        })
        router = FastCommandRouter(_Events(), tools, _Apps())
        status = router.dispatch("Qual é o estado atual do Desktop Agent?")
        listing = router.dispatch("Lista as janelas que estão abertas no meu computador.")
        self.assertTrue(status.handled)
        self.assertTrue(listing.handled)
        self.assertIn("disponível", status.response)
        self.assertIn("Windows PowerShell", listing.response)
        self.assertIn("Brave", listing.response)


    def test_fast_generic_recent_memory_recall_uses_explicit_memory_index(self):
        tools = _Tools({"recall_user_memory": {
            "ok": True, "facts": [{"category":"user_explicit", "fact":"o código de teste desta sessão é AZUL-4729"}],
        }})
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("Recorda o que te pedi para guardar na memória local há pouco.")
        self.assertTrue(result.handled)
        self.assertIn("AZUL-4729", result.response)
        self.assertEqual(tools.calls[0][0], "recall_user_memory")
        self.assertEqual(tools.calls[0][1]["query"], "user_explicit")

    def test_fast_broad_system_status_uses_one_system_tool_and_reports_core_metrics(self):
        tools = _Tools({"get_system_status": {
            "os": {"system":"Windows", "release":"11", "version":"26100"},
            "uptime_seconds": 90061,
            "cpu": {"usage_percent": 12.5},
            "memory": {"used_percent": 44.0, "used_gib": 13.9, "total_gib": 31.7},
            "gpus": [{"utilization_percent": 7}],
        }})
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("Diz-me qual é o estado atual do sistema, incluindo Windows, uptime e informações principais do sistema.")
        self.assertTrue(result.handled)
        self.assertEqual([x[0] for x in tools.calls], ["get_system_status"])
        self.assertIn("Windows 11", result.response)
        self.assertIn("CPU", result.response)
        self.assertIn("RAM", result.response)
        self.assertIn("GPU", result.response)

    def test_fast_screen_request_calls_local_vision_directly(self):
        tools = _Tools({"analyze_current_screen": {
            "ok": True, "analysis": "Está visível uma janela do Windows PowerShell."
        }})
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("Olha para o meu ecrã neste momento e diz-me o que está visível.")
        self.assertTrue(result.handled)
        self.assertEqual([x[0] for x in tools.calls], ["analyze_current_screen"])
        self.assertIn("PowerShell", result.response)

    def test_large_tool_result_is_compacted_before_context(self):
        raw = json.dumps({"ok": True, "rows": [{"value": "x" * 1000} for _ in range(30)]})
        compact = JarvisBrain._compact_tool_result("get_pc_health", raw, max_chars=1800)
        self.assertLessEqual(len(compact), 1900)
        self.assertIn("ok", compact)

    def test_setup_is_quiet_and_cloud_setup_cannot_enable_provider(self):
        setup = Path("setup.ps1").read_text(encoding="utf-8-sig")
        cloud = Path("setup_cloud.ps1").read_text(encoding="utf-8-sig").lower()
        self.assertIn("--disable-pip-version-check -q", setup)
        self.assertIn("unittest discover -s tests -q", setup)
        self.assertIn("external ai hard block", cloud)
        self.assertNotIn("pip install", cloud)
        self.assertNotIn("setup_secret openai", cloud)


if __name__ == "__main__":
    unittest.main()
