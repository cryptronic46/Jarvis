import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis_core.core.config import Settings
from jarvis_core.core.local_vision import NativeVisionClient, NativeVisionRuntime, NativeVisionStatus
from jarvis_core.services.local_research import LocalResearchEngine


class _Events:
    def __init__(self):
        self.rows = []
    def emit(self, name, **payload):
        self.rows.append((name, payload))


class AcceptanceHotfixV3Tests(unittest.TestCase):
    def test_owner_selected_direct_root_reaches_local_synthesis_even_if_prefilter_is_weak(self):
        settings = SimpleNamespace(
            local_research_enabled=True,
            local_research_fetch_max_bytes=200000,
            local_research_timeout_seconds=2.0,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=1,
            model="qwen-test",
        )
        local = Mock()
        local.synthesize_research.return_value = "A página indica a versão atual do Python. [S1]"
        engine = LocalResearchEngine(settings, _Events(), local)
        engine._validate_public_url = lambda url: url
        # Simulates a real page whose first readable window is generic and does
        # not repeat the Portuguese relevance terms. The OWNER selected it.
        engine._get = lambda url, *, max_bytes, timeout: (
            ("<html><title>Downloads</title><body>" + ("Release downloads and documentation. " * 8) + "</body></html>").encode(),
            "text/html",
            "https://www.python.org/downloads/",
        )
        result = engine.research_url(
            "https://www.python.org/downloads/",
            query="Estuda o URL e diz-me qual é a versão atual do Python.",
            topic="a versão atual do Python",
            deep=False,
        )
        self.assertTrue(result.ok)
        local.synthesize_research.assert_called_once()

    def test_direct_root_still_honors_semantic_rejection_from_local_synthesis(self):
        settings = SimpleNamespace(
            local_research_enabled=True,
            local_research_fetch_max_bytes=200000,
            local_research_timeout_seconds=2.0,
            local_research_source_max_chars=5000,
            local_research_direct_source_max_chars=4500,
            local_research_direct_max_pages=1,
            model="qwen-test",
        )
        local = Mock()
        local.synthesize_research.return_value = "[[RESEARCH_RELEVANCE_REJECTED]]"
        engine = LocalResearchEngine(settings, _Events(), local)
        engine._validate_public_url = lambda url: url
        engine._get = lambda url, *, max_bytes, timeout: (
            ("<html><title>Generic</title><body>" + ("Unrelated readable public content. " * 8) + "</body></html>").encode(),
            "text/html",
            "https://example.org/page/",
        )
        result = engine.research_url(
            "https://example.org/page/",
            query="Estuda isto sobre Python.",
            topic="Python",
            deep=False,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "LOCAL_SYNTHESIS_RELEVANCE_REJECTED")

    def test_setup_vision_pins_native_model_and_mmproj_hashes(self):
        text = Path("setup_vision.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("ggml-org/Qwen2.5-VL-3B-Instruct-GGUF", text)
        self.assertIn("5037fcf163dd95d1e41d1974465f0898ed108ca2", text)
        self.assertIn("d02fe9b69ad8cadbbd228e387667af66612c44bed29ffc8eb1e7caf9ac486c12", text)
        self.assertIn("980c9b2f78c04e6cff93d277ada09e768394f112d75db3b4e9dea8a69f9fb904", text)
        self.assertIn("Assert-Sha256", text)
        self.assertNotIn("ollama pull", text.lower())
        self.assertNotIn("get-command ollama", text.lower())

    def test_native_vision_runtime_is_loopback_and_requires_both_model_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "llama-server.exe"
            model = root / "vision.gguf"
            mmproj = root / "mmproj.gguf"
            settings = SimpleNamespace(
                native_llama_server_path=str(exe),
                vision_native_model_path=str(model),
                vision_native_mmproj_path=str(mmproj),
                vision_native_port=11436,
                vision_native_state_path=str(root / "state.json"),
            )
            runtime = NativeVisionRuntime(settings)
            self.assertEqual(runtime.host, "127.0.0.1")
            ok, error = runtime.configured()
            self.assertFalse(ok)
            self.assertEqual(error, "VISION_MODEL_NOT_INSTALLED")
            model.write_bytes(b"x")
            ok, error = runtime.configured()
            self.assertFalse(ok)
            self.assertEqual(error, "VISION_MMPROJ_NOT_INSTALLED")
            mmproj.write_bytes(b"x")
            ok, error = runtime.configured()
            self.assertFalse(ok)
            self.assertEqual(error, "VISION_LLAMA_RUNTIME_NOT_INSTALLED")
            exe.write_bytes(b"x")
            self.assertEqual(runtime.configured(), (True, None))

    def test_native_vision_client_sends_openai_multimodal_image_url_locally(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "screen.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
            settings = SimpleNamespace(
                vision_native_port=11436,
                vision_native_max_tokens=333,
                vision_native_request_timeout_seconds=12.0,
            )
            client = NativeVisionClient(settings)
            client.runtime.ensure_started = Mock(return_value=NativeVisionStatus(
                True, 1, "http://127.0.0.1:11436", "m.gguf", "mm.gguf", True
            ))
            captured = {}

            def fake_json(url, payload, timeout):
                captured["url"] = url
                captured["payload"] = payload
                captured["timeout"] = timeout
                return {"choices": [{"message": {"content": "Vejo uma janela do PowerShell."}}]}

            with patch.object(NativeVisionClient, "_json", side_effect=fake_json):
                text = client.analyze(image, prompt="O que vês?", system="Analisa localmente.")
            self.assertIn("PowerShell", text)
            self.assertEqual(captured["url"], "http://127.0.0.1:11436/chat/completions")
            self.assertEqual(captured["payload"]["model"], "jarvis-vision")
            parts = captured["payload"]["messages"][1]["content"]
            image_part = [row for row in parts if row.get("type") == "image_url"][0]
            self.assertTrue(image_part["image_url"]["url"].startswith("data:image/unknown;base64,"))
            self.assertEqual(parts[0].get("type"), "image_url")
            self.assertNotIn("tools", captured["payload"])


    def test_native_vision_keep_alive_releases_separate_runtime(self):
        settings = SimpleNamespace(vision_keep_alive="2m")
        client = NativeVisionClient(settings)
        client.runtime.shutdown = Mock(return_value={"ok": True, "released": True})
        self.assertEqual(client._duration_seconds("2m"), 120.0)
        self.assertEqual(client._duration_seconds("30s"), 30.0)
        fake_timer = Mock()
        fake_timer.daemon = False
        with patch("jarvis_core.core.local_vision.Timer", return_value=fake_timer) as timer_cls:
            client._schedule_idle_shutdown()
        timer_cls.assert_called_once_with(120.0, client._expire_idle_runtime)
        self.assertTrue(fake_timer.daemon)
        fake_timer.start.assert_called_once()
        client._expire_idle_runtime()
        client.runtime.shutdown.assert_called_with(reason="vision_keep_alive_expired")

    def test_legacy_vision_tag_migrates_to_native_model_label(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text('{"vision_model":"qwen2.5vl:7b"}', encoding="utf-8")
            result = Settings.ensure_file_schema(path)
            data = __import__("json").loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["vision_model"], "Qwen2.5-VL-3B-Instruct-Q4_K_M")
            self.assertIn("vision_model", result["vision_migrated"])
            self.assertEqual(data["vision_native_port"], 11436)


if __name__ == "__main__":
    unittest.main()
