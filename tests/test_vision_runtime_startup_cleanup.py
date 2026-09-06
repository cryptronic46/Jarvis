import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

from jarvis_core.core.local_vision import NativeVisionRuntime


class VisionRuntimeStartupCleanupTests(unittest.TestCase):
    def test_popen_failure_closes_log_handle_and_clears_reference(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            executable = root / "llama-server.exe"
            model = root / "vision.gguf"
            mmproj = root / "mmproj.gguf"

            executable.write_bytes(b"x")
            model.write_bytes(b"x")
            mmproj.write_bytes(b"x")

            settings = SimpleNamespace(
                log_dir=str(root / "logs"),
                vision_native_ctx=8192,
                vision_native_gpu_layers=0,
                vision_native_threads=1,
                vision_native_start_timeout_seconds=10,
            )

            runtime = NativeVisionRuntime(settings)
            runtime._health = Mock(return_value=False)
            runtime.configured = Mock(return_value=(True, None))

            with (
                patch.object(
                    NativeVisionRuntime,
                    "executable",
                    new_callable=PropertyMock,
                    return_value=executable,
                ),
                patch.object(
                    NativeVisionRuntime,
                    "model_path",
                    new_callable=PropertyMock,
                    return_value=model,
                ),
                patch.object(
                    NativeVisionRuntime,
                    "mmproj_path",
                    new_callable=PropertyMock,
                    return_value=mmproj,
                ),
                patch(
                    "jarvis_core.core.local_vision.subprocess.Popen",
                    side_effect=OSError("simulated popen failure"),
                ),
            ):
                with self.assertRaises(OSError):
                    runtime.ensure_started()

            self.assertIsNone(
                runtime._log_handle,
                "startup failure must clear the runtime log handle reference",
            )
            self.assertIsNone(runtime._process)
            self.assertFalse(runtime._owned)


    def test_early_process_exit_closes_log_handle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            executable = root / "llama-server.exe"
            model = root / "vision.gguf"
            mmproj = root / "mmproj.gguf"

            executable.write_bytes(b"x")
            model.write_bytes(b"x")
            mmproj.write_bytes(b"x")

            settings = SimpleNamespace(
                log_dir=str(root / "logs"),
                vision_native_ctx=8192,
                vision_native_gpu_layers=0,
                vision_native_threads=1,
                vision_native_start_timeout_seconds=10,
            )

            runtime = NativeVisionRuntime(settings)
            runtime._health = Mock(return_value=False)
            runtime.configured = Mock(return_value=(True, None))

            process = Mock()
            process.pid = 43210
            process.returncode = 7
            process.poll.return_value = 7

            try:
                with (
                    patch.object(
                        NativeVisionRuntime,
                        "executable",
                        new_callable=PropertyMock,
                        return_value=executable,
                    ),
                    patch.object(
                        NativeVisionRuntime,
                        "model_path",
                        new_callable=PropertyMock,
                        return_value=model,
                    ),
                    patch.object(
                        NativeVisionRuntime,
                        "mmproj_path",
                        new_callable=PropertyMock,
                        return_value=mmproj,
                    ),
                    patch(
                        "jarvis_core.core.local_vision.subprocess.Popen",
                        return_value=process,
                    ),
                ):
                    with self.assertRaisesRegex(
                        Exception,
                        "exited with code 7",
                    ):
                        runtime.ensure_started()

                self.assertIsNone(
                    runtime._log_handle,
                    "early process exit must clear the runtime log handle",
                )
                self.assertIsNone(runtime._process)
                self.assertFalse(runtime._owned)
            finally:
                # Test hygiene on the intentionally broken implementation:
                # release the leaked handle so TemporaryDirectory can clean up.
                if runtime._log_handle is not None:
                    runtime._log_handle.close()
                    runtime._log_handle = None
if __name__ == "__main__":
    unittest.main()
