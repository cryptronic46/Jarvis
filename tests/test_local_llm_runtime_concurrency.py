import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from jarvis_core.core.local_llm import NativeLlamaRuntime


class LocalLlmRuntimeConcurrencyTests(unittest.TestCase):
    def test_shutdown_is_not_blocked_by_startup_wait_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

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
                native_llama_start_timeout_seconds=10,
            )

            runtime = NativeLlamaRuntime(settings)
            runtime._write_state = Mock()
            runtime._emit = Mock()

            process = Mock()
            process.pid = 43210
            process.returncode = None
            process.poll.return_value = None
            process.wait.return_value = 0

            startup_waiting = threading.Event()
            release_startup = threading.Event()
            shutdown_done = threading.Event()

            startup_errors = []
            shutdown_errors = []
            startup_health_calls = 0
            startup_health_lock = threading.Lock()

            def controlled_health(*args, **kwargs):
                nonlocal startup_health_calls

                if threading.current_thread().name == "llm-startup-test":
                    with startup_health_lock:
                        startup_health_calls += 1
                        call_number = startup_health_calls

                    if call_number == 1:
                        return False

                    startup_waiting.set()
                    release_startup.wait(timeout=5.0)
                    return True

                return False

            runtime._health = controlled_health

            def run_startup():
                try:
                    runtime.ensure_started()
                except Exception as exc:
                    startup_errors.append(exc)

            def run_shutdown():
                try:
                    runtime.shutdown(reason="concurrency_test")
                except Exception as exc:
                    shutdown_errors.append(exc)
                finally:
                    shutdown_done.set()

            with patch(
                "jarvis_core.core.local_llm.subprocess.Popen",
                return_value=process,
            ):
                startup_thread = threading.Thread(
                    target=run_startup,
                    name="llm-startup-test",
                    daemon=True,
                )
                startup_thread.start()

                self.assertTrue(
                    startup_waiting.wait(timeout=2.0),
                    "startup did not reach its health wait loop",
                )

                shutdown_thread = threading.Thread(
                    target=run_shutdown,
                    name="llm-shutdown-test",
                    daemon=True,
                )
                shutdown_thread.start()

                shutdown_completed_while_startup_waited = shutdown_done.wait(
                    timeout=0.75
                )

                # Always release/join before asserting so a RED test leaves no
                # background thread behind.
                release_startup.set()
                startup_thread.join(timeout=3.0)
                shutdown_thread.join(timeout=3.0)

            self.assertFalse(startup_thread.is_alive())
            self.assertFalse(shutdown_thread.is_alive())
            self.assertEqual(shutdown_errors, [])
            self.assertTrue(
                shutdown_completed_while_startup_waited,
                "shutdown was blocked behind the startup lifecycle lock",
            )



    def test_shutdown_during_started_event_prevents_stale_startup_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

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
                native_llama_start_timeout_seconds=10,
            )

            runtime = NativeLlamaRuntime(settings)
            runtime._write_state = Mock()

            process = Mock()
            process.pid = 54321
            process.returncode = None
            process.poll.return_value = None
            process.wait.return_value = 0

            started_event_entered = threading.Event()
            release_started_event = threading.Event()
            shutdown_done = threading.Event()

            startup_results = []
            startup_errors = []
            shutdown_errors = []

            startup_health_calls = 0
            startup_health_lock = threading.Lock()

            def controlled_health(*args, **kwargs):
                nonlocal startup_health_calls

                if threading.current_thread().name == "llm-startup-stale-test":
                    with startup_health_lock:
                        startup_health_calls += 1
                        call_number = startup_health_calls

                    if call_number == 1:
                        return False
                    return True

                return False

            def controlled_emit(name, **payload):
                if name == "NATIVE_LLM_STARTED":
                    started_event_entered.set()
                    release_started_event.wait(timeout=5.0)

            runtime._health = controlled_health
            runtime._emit = controlled_emit

            def run_startup():
                try:
                    startup_results.append(runtime.ensure_started())
                except Exception as exc:
                    startup_errors.append(exc)

            def run_shutdown():
                try:
                    runtime.shutdown(reason="stale_success_test")
                except Exception as exc:
                    shutdown_errors.append(exc)
                finally:
                    shutdown_done.set()

            with patch(
                "jarvis_core.core.local_llm.subprocess.Popen",
                return_value=process,
            ):
                startup_thread = threading.Thread(
                    target=run_startup,
                    name="llm-startup-stale-test",
                    daemon=True,
                )
                startup_thread.start()

                self.assertTrue(
                    started_event_entered.wait(timeout=2.0),
                    "startup did not reach NATIVE_LLM_STARTED",
                )

                shutdown_thread = threading.Thread(
                    target=run_shutdown,
                    name="llm-shutdown-stale-test",
                    daemon=True,
                )
                shutdown_thread.start()

                shutdown_completed_during_started_event = shutdown_done.wait(
                    timeout=0.75
                )

                # Always release before assertions so a RED run cannot leave
                # either test thread blocked.
                release_started_event.set()

                startup_thread.join(timeout=3.0)
                shutdown_thread.join(timeout=3.0)

            self.assertFalse(startup_thread.is_alive())
            self.assertFalse(shutdown_thread.is_alive())
            self.assertEqual(shutdown_errors, [])

            self.assertTrue(
                shutdown_completed_during_started_event,
                "shutdown was blocked during the startup success window",
            )

            self.assertEqual(
                startup_results,
                [],
                "startup returned stale success after shutdown completed",
            )

            self.assertEqual(len(startup_errors), 1)
            self.assertIn(
                "LLM_STARTUP_CANCELLED",
                str(startup_errors[0]),
            )

    def test_shutdown_prevents_stale_success_from_healthy_fast_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            settings = SimpleNamespace(
                native_llama_state_path=str(root / "llm-state.json"),
            )

            runtime = NativeLlamaRuntime(settings)

            fast_path_pid_read = threading.Event()
            release_fast_path = threading.Event()
            shutdown_done = threading.Event()

            startup_results = []
            startup_errors = []
            shutdown_errors = []

            def controlled_health(*args, **kwargs):
                if threading.current_thread().name == "llm-fastpath-test":
                    return True
                return False

            def controlled_read_state_pid():
                if threading.current_thread().name == "llm-fastpath-test":
                    fast_path_pid_read.set()
                    release_fast_path.wait(timeout=5.0)
                    return 54321
                return None

            runtime._health = controlled_health
            runtime._read_state_pid = controlled_read_state_pid
            runtime._process = None
            runtime._owned = False
            runtime._emit = Mock()

            def run_fast_path():
                try:
                    startup_results.append(runtime.ensure_started())
                except Exception as exc:
                    startup_errors.append(exc)

            def run_shutdown():
                try:
                    runtime.shutdown(reason="healthy_fastpath_test")
                except Exception as exc:
                    shutdown_errors.append(exc)
                finally:
                    shutdown_done.set()

            startup_thread = threading.Thread(
                target=run_fast_path,
                name="llm-fastpath-test",
                daemon=True,
            )
            startup_thread.start()

            self.assertTrue(
                fast_path_pid_read.wait(timeout=2.0),
                "healthy fast path did not reach PID resolution",
            )

            shutdown_thread = threading.Thread(
                target=run_shutdown,
                name="llm-fastpath-shutdown-test",
                daemon=True,
            )
            shutdown_thread.start()

            shutdown_completed_during_fast_path = shutdown_done.wait(
                timeout=0.75
            )

            release_fast_path.set()

            startup_thread.join(timeout=3.0)
            shutdown_thread.join(timeout=3.0)

            self.assertFalse(startup_thread.is_alive())
            self.assertFalse(shutdown_thread.is_alive())
            self.assertEqual(shutdown_errors, [])

            self.assertTrue(
                shutdown_completed_during_fast_path,
                "shutdown was blocked during healthy fast-path PID resolution",
            )

            self.assertEqual(
                startup_results,
                [],
                "healthy fast path returned stale success after shutdown",
            )

            self.assertEqual(len(startup_errors), 1)
            self.assertIn(
                "LLM_STARTUP_CANCELLED",
                str(startup_errors[0]),
            )
if __name__ == "__main__":
    unittest.main()
