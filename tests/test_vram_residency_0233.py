import json
import tempfile
import unittest
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from threading import RLock

# Keep this contract runnable in release-validation environments where the
# optional/runtime Ollama package is not installed. The tested Brain instance
# receives a dedicated fake client below.
fake_ollama = types.ModuleType("ollama")
fake_ollama.Client = object
fake_ollama.ResponseError = RuntimeError
sys.modules.setdefault("ollama", fake_ollama)

fake_winreg = types.ModuleType("winreg")
fake_winreg.HKEY_LOCAL_MACHINE = object()
fake_winreg.HKEY_CURRENT_USER = object()
fake_winreg.KEY_READ = 0
fake_winreg.KEY_WOW64_64KEY = 0
sys.modules.setdefault("winreg", fake_winreg)

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.config import Settings


class FakeEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class FakeClient:
    def __init__(self, running=None):
        self.running = list(running or [])
        self.generate_calls = []

    def ps(self):
        return {
            "models": [
                {
                    "model": name,
                    "size": 10_000,
                    "size_vram": 7_000,
                    "expires_at": "later",
                }
                for name in self.running
            ]
        }

    def generate(self, **kwargs):
        self.generate_calls.append(dict(kwargs))
        name = kwargs.get("model")
        if kwargs.get("keep_alive") == 0 and name in self.running:
            self.running.remove(name)
        return {"done": True, "done_reason": "unload"}


class VramResidencyTests(unittest.TestCase):
    def _brain(self):
        brain = JarvisBrain.__new__(JarvisBrain)
        brain.settings = SimpleNamespace(
            model="qwen3:8b",
            vision_model="qwen2.5vl:7b",
            ollama_keep_alive="5m",
            vision_keep_alive="2m",
            ollama_release_on_shutdown=True,
        )
        brain.events = FakeEvents()
        brain.client = FakeClient(["qwen3:8b", "qwen2.5vl:7b", "other-app:model"])
        brain._lock = RLock()
        brain._model_loaded = True
        brain._loaded_models = {"qwen3:8b", "qwen2.5vl:7b"}
        return brain

    def test_release_all_unloads_only_configured_jarvis_models(self):
        brain = self._brain()
        result = brain.release_all_models(reason="test", include_configured=True)
        self.assertTrue(result["ok"])
        self.assertEqual(
            set(result["released_models"]),
            {"qwen3:8b", "qwen2.5vl:7b"},
        )
        self.assertEqual(brain.client.running, ["other-app:model"])
        self.assertTrue(
            all(call.get("keep_alive") == 0 for call in brain.client.generate_calls)
        )
        self.assertFalse(brain._model_loaded)
        self.assertEqual(brain._loaded_models, set())

    def test_residency_status_reports_only_configured_vram(self):
        brain = self._brain()
        status = brain.residency_status()
        self.assertEqual(status["keep_alive"], "5m")
        self.assertEqual(status["vision_keep_alive"], "2m")
        self.assertEqual(len(status["running_configured"]), 2)
        self.assertEqual(status["configured_vram_bytes"], 14_000)

    def test_previous_5m_default_migrates_to_30m_but_custom_value_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "old.json"
            old.write_text(json.dumps({"ollama_keep_alive": "5m"}), encoding="utf-8")
            result = Settings.ensure_file_schema(old)
            data = json.loads(old.read_text(encoding="utf-8"))
            self.assertEqual(data["ollama_keep_alive"], "30m")
            self.assertTrue(data["ollama_release_on_shutdown"])
            self.assertEqual(data["vision_keep_alive"], "2m")
            self.assertIn("ollama_keep_alive", result["resource_migrated"])

            custom = Path(tmp) / "custom.json"
            custom.write_text(json.dumps({"ollama_keep_alive": "12m"}), encoding="utf-8")
            Settings.ensure_file_schema(custom)
            custom_data = json.loads(custom.read_text(encoding="utf-8"))
            self.assertEqual(custom_data["ollama_keep_alive"], "12m")

    def test_cli_shutdown_and_manual_commands_release_all_models(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('/vram status', cli)
        self.assertIn('/vram release', cli)
        self.assertIn('reason="jarvis_shutdown"', cli)
        self.assertGreaterEqual(cli.count("brain.release_all_models("), 2)

    def test_launcher_has_crash_safe_native_cleanup(self):
        text = Path("run.ps1").read_text(encoding="utf-8")
        self.assertIn("Stop-JarvisNativeBrain", text)
        self.assertIn("native_llama_runtime.json", text)
        self.assertIn("finally", text)
        self.assertIn("Stop-JarvisOllamaCompatModel", text)
        self.assertIn("/api/generate", text)
        self.assertIn("keep_alive=0", text)

    def test_vision_uses_short_keep_alive_and_releases_separate_native_runtime(self):
        vision_text = Path("jarvis_core/skills/builtin/vision.py").read_text(encoding="utf-8")
        runtime_text = Path("jarvis_core/core/local_vision.py").read_text(encoding="utf-8")
        self.assertIn("vision_keep_alive", vision_text)
        self.assertIn("self.native.shutdown", vision_text)
        self.assertIn("_schedule_idle_shutdown", runtime_text)
        self.assertIn('reason="vision_keep_alive_expired"', runtime_text)
        self.assertNotIn('keep_alive="10m"', vision_text)


if __name__ == "__main__":
    unittest.main()
