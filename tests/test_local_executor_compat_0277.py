import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.core.local_llm import JarvisLocalClient, LocalLLMError


class _BlockedNative:
    def chat(self, **kwargs):
        raise LocalLLMError("llama-server rejected by Windows (0xC0E90002: Bad Image / Code Integrity)")
    def list(self):
        return SimpleNamespace(models=[])
    def show(self, model):
        raise LocalLLMError("native unavailable")
    def ps(self):
        return SimpleNamespace(models=[])
    def generate(self, **kwargs):
        return {"ok": True}
    def shutdown(self, reason="shutdown"):
        return {"ok": True, "released": True}
    runtime = SimpleNamespace(status=lambda: SimpleNamespace(running=False, model_path="models/llm/qwen3-8b.gguf"))


class _Compat:
    def __init__(self):
        self.calls = 0
    def health(self, require_model=True):
        return {"ok": True, "online": True, "model_ok": True}
    def chat(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(message=SimpleNamespace(content="LOCAL_OK", thinking="", tool_calls=[]), done_reason="stop", eval_count=1, model="qwen3:8b")
    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="qwen3:8b")])
    def show(self, model):
        return {"ok": True}
    def ps(self):
        return SimpleNamespace(models=[])
    def generate(self, **kwargs):
        return {"ok": True}
    def shutdown(self, reason="shutdown"):
        return {"ok": True, "released": True}


class LocalExecutorCompat0277Tests(unittest.TestCase):
    def test_code_integrity_failure_falls_back_to_loopback_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(local_llm_executor_state_path=str(Path(tmp) / "executor.json"))
            compat = _Compat()
            client = JarvisLocalClient(settings, native_client=_BlockedNative(), compat_client=compat)
            result = client.chat(model="qwen3:8b", messages=[{"role":"user","content":"olá"}])
            self.assertEqual(result.message.content, "LOCAL_OK")
            self.assertEqual(client.executor_status()["selected"], "ollama_local_compat")
            self.assertEqual(compat.calls, 1)
            self.assertTrue((Path(tmp) / "executor.json").is_file())

    def test_fallback_can_be_disabled_without_enabling_cloud(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(local_llm_allow_ollama_compat=False, local_llm_executor_state_path=str(Path(tmp) / "executor.json"))
            client = JarvisLocalClient(settings, native_client=_BlockedNative(), compat_client=_Compat())
            with self.assertRaises(LocalLLMError):
                client.chat(model="qwen3:8b", messages=[])
            self.assertFalse(settings.external_ai_enabled)
            self.assertFalse(settings.cloud_enabled)

    def test_runtime_setup_tries_verified_vulkan_before_compat(self):
        text = Path("setup_native_brain.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("530f57d2a874ce017827c1e5a926812b9d5de4667248575d1372b1c0acf94d83", text)
        self.assertLess(text.index("Install-PinnedNativeRuntime 'vulkan'"), text.index("Test-OllamaCompatExecutor", text.index("$probe = Invoke-NativeRuntimeProbe")))
        self.assertIn("JARVIS remains the orchestration brain", text)

    def test_security_baseline_accepts_healthy_local_executor_when_standalone_native_is_blocked(self):
        text = Path("repair_security_baseline.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("local_executor", text)
        self.assertIn("COMPAT_OK", text)
        self.assertIn("-and -not $Audit.local_executor.ok", text)

    def test_no_ollama_python_sdk_dependency_is_reintroduced(self):
        req = Path("requirements.txt").read_text(encoding="utf-8").lower()
        llm = Path("jarvis_core/core/local_llm.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("ollama==", req)
        self.assertNotIn("import ollama", llm)
        self.assertIn("/api/chat", llm)
        self.assertIn("/api/generate", llm)


if __name__ == "__main__":
    unittest.main()
