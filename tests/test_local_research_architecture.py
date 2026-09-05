import json
import unittest
import ast
from pathlib import Path
from unittest.mock import patch

from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridRoutePolicy
from jarvis_core.services.local_research import LocalResearchEngine


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class DummyBrain:
    pass


class LocalResearchArchitectureTests(unittest.TestCase):
    def test_external_ai_defaults_are_disabled(self):
        settings = Settings()
        self.assertFalse(settings.external_ai_enabled)
        self.assertFalse(settings.cloud_enabled)
        self.assertFalse(settings.cloud_fallback_on_local_error)
        self.assertFalse(settings.performance_cloud_offload_under_pressure)
        self.assertTrue(settings.external_ai_complex_only)
        self.assertFalse(settings.external_ai_auto_escalate_complex)

    def test_explicit_external_ai_disable_forces_cloud_off(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "external_ai_enabled": False,
                "cloud_enabled": True,
                "hybrid_mode": "cloud",
                "cloud_fallback_on_local_error": True,
                "performance_cloud_offload_under_pressure": True,
            }), encoding="utf-8")
            settings = Settings.load(path)
            self.assertFalse(settings.cloud_enabled)
            self.assertEqual(settings.hybrid_mode, "local")
            self.assertFalse(settings.cloud_fallback_on_local_error)
            self.assertFalse(settings.performance_cloud_offload_under_pressure)

    def test_router_hard_blocks_all_explicit_external_ai_requests(self):
        policy = HybridRoutePolicy(Settings())
        for query in (
            "/cloud explica isto",
            "/sol resolve isto",
            "Usa o ChatGPT para analisar isto",
            "Consulta outra inteligência artificial para responder",
        ):
            self.assertEqual(policy.decide(query, True).route, "external_ai_blocked")
        self.assertEqual(policy.decide("Analisa profundamente esta arquitetura", True).route, "local")

    def test_web_routes_to_research_not_external_ai(self):
        decision = HybridRoutePolicy(Settings()).decide("Pesquisa na Internet notícias de hoje", True)
        self.assertEqual(decision.route, "research")
        self.assertTrue(decision.use_web)

    def test_private_and_local_targets_are_blocked(self):
        engine = LocalResearchEngine(Settings(), DummyEvents(), DummyBrain())
        with self.assertRaises(ValueError):
            engine._validate_public_url("http://127.0.0.1/admin")
        with patch("jarvis_core.services.local_research.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("192.168.1.1", 80))]):
            with self.assertRaises(ValueError):
                engine._validate_public_url("http://router.example/")

    def test_research_synthesis_has_no_tool_schema(self):
        source = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")

        tree = ast.parse(source)

        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "synthesize_research"
        )

        block = ast.get_source_segment(
            source,
            method,
        )

        self.assertIsNotNone(block)
        self.assertIn(
            "UNTRUSTED_SOURCE_TEXT",
            block,
        )
        self.assertNotIn(
            'kwargs["tools"]',
            block,
        )
        self.assertNotIn(
            "self.tools.execute",
            block,
        )

    def test_setup_cloud_cannot_enable_external_ai(self):
        script = Path("setup_cloud.ps1").read_text(encoding="utf-8-sig").lower()
        self.assertIn("external ai hard block", script)
        self.assertNotIn("'external_ai_enabled':true", script)
        self.assertNotIn("'cloud_enabled':true", script)
        self.assertNotIn("setup_secret openai", script)


    def test_schema_migration_normalizes_preserved_019_cloud_flags(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "cloud_enabled": True,
                "hybrid_mode": "auto",
                "cloud_fallback_on_local_error": True,
                "performance_cloud_offload_under_pressure": True,
            }), encoding="utf-8")
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["external_ai_enabled"])
            self.assertFalse(data["cloud_enabled"])
            self.assertEqual(data["hybrid_mode"], "local")
            self.assertFalse(data["cloud_fallback_on_local_error"])
            self.assertFalse(data["performance_cloud_offload_under_pressure"])
            self.assertTrue(data["external_ai_complex_only"])
            self.assertFalse(data["external_ai_auto_escalate_complex"])
            self.assertGreaterEqual(result["forced_local_first_count"], 1)

    def test_schema_migration_revokes_legacy_external_ai_opt_in(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "external_ai_enabled": True,
                "cloud_enabled": True,
                "expert_escalation_enabled": True,
                "hybrid_mode": "local",
            }), encoding="utf-8")
            Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(data["external_ai_enabled"])
            self.assertFalse(data["cloud_enabled"])
            self.assertFalse(data["expert_escalation_enabled"])
            self.assertFalse(data["external_ai_auto_escalate_complex"])

    def test_legacy_cloud_client_has_hard_external_ai_gate(self):
        cloud = Path("jarvis_core/core/cloud_brain.py").read_text(encoding="utf-8")
        start = cloud.index("def _client_or_raise")
        end = cloud.index("def _api_function_tools", start)
        block = cloud[start:end]
        self.assertIn('external_ai_enabled', block)
        self.assertIn('EXTERNAL_AI_DISABLED', block)


if __name__ == "__main__":
    unittest.main()
