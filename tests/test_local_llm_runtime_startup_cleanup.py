import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis_core.core.local_llm import LocalLLMError, NativeLlamaRuntime


class LocalLlmRuntimeStartupCleanupTests(unittest.TestCase):
    def _runtime(self, root: Path) -> NativeLlamaRuntime:
        executable = root / "llama-server.exe"
        model = root / "qwen.gguf"
        executable.write_bytes(b"test")
        model.write_bytes(b"test")

        settings = SimpleNamespace(
            native_llama_server_path=str(executable),
            native_llama_model_path=str(model),
            native_llama_state_path=str(root / "llm-state.json"),
            log_dir=str(root / "logs"),
            llm_num_ctx=8192,
            native_llama_gpu_layers=0,
            native_llama_threads=1,
            native_llama_flash_attention=False,
            native_llama_start_timeout_seconds=5,
        )

        runtime = NativeLlamaRuntime(settings)
        runtime._health = Mock(return_value=False)
        runtime._write_state = Mock()
        runtime._emit = Mock()
        return runtime

    def test_popen_failure_closes_log_handle_and_clears_reference(self):
        root = Path(tempfile.mkdtemp(prefix="jarvis-llm-popen-fail-"))
        runtime = self._runtime(root)

        try:
            with patch(
                "jarvis_core.core.local_llm.subprocess.Popen",
                side_effect=OSError("synthetic Popen failure"),
            ):
                with self.assertRaises(OSError):
                    runtime.ensure_started()

            self.assertIsNone(
                runtime._log_handle,
                "Popen failure leaked the native LLM log handle",
            )
            self.assertIsNone(runtime._process)
            self.assertFalse(runtime._owned)
        finally:
            handle = runtime._log_handle
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                runtime._log_handle = None
            shutil.rmtree(root, ignore_errors=True)

    def test_early_process_exit_closes_log_handle_and_clears_runtime_state(self):
        root = Path(tempfile.mkdtemp(prefix="jarvis-llm-early-exit-"))
        runtime = self._runtime(root)

        process = Mock()
        process.pid = 43210
        process.returncode = 7
        process.poll.return_value = 7

        try:
            with patch(
                "jarvis_core.core.local_llm.subprocess.Popen",
                return_value=process,
            ):
                with self.assertRaises(LocalLLMError):
                    runtime.ensure_started()

            self.assertIsNone(
                runtime._log_handle,
                "early process exit leaked the native LLM log handle",
            )
            self.assertIsNone(runtime._process)
            self.assertFalse(runtime._owned)
        finally:
            handle = runtime._log_handle
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                runtime._log_handle = None
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
