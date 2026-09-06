from __future__ import annotations

"""Local inference backends for JARVIS.

0.27.8 keeps the JARVIS Core owning the lifecycle of its text reasoning runtime.
The JARVIS Core owns text reasoning policy, memory, tools and prompt state.
Its preferred executor is a private llama.cpp server. On Windows machines where
Code Integrity rejects the verified llama.cpp binary, JARVIS may use an existing
local Ollama service strictly as a compatibility executor for the same local Qwen
model. That fallback is local-only, uses no Ollama Python SDK and never enables
cloud/external-AI routing.
"""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib import request, error
from threading import RLock
from time import monotonic, sleep
import json
import os
import socket
import subprocess
import shutil


class LocalLLMError(RuntimeError):
    pass


@dataclass(slots=True)
class NativeRuntimeStatus:
    running: bool
    pid: int | None
    url: str
    model_path: str
    owned: bool


class NativeLlamaRuntime:
    def __init__(self, settings, events=None):
        self.settings = settings
        self.events = events
        self._lock = RLock()
        self._startup_lock = RLock()
        self._lifecycle_generation = 0
        self._process: subprocess.Popen | None = None
        self._owned = False
        self._log_handle = None

    @property
    def host(self) -> str:
        return str(getattr(self.settings, "native_llama_host", "127.0.0.1"))

    @property
    def port(self) -> int:
        return int(getattr(self.settings, "native_llama_port", 11435))

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def executable(self) -> Path:
        return Path(str(getattr(self.settings, "native_llama_server_path", "runtime/llama.cpp/llama-server.exe")))

    @property
    def model_path(self) -> Path:
        return Path(str(getattr(self.settings, "native_llama_model_path", "models/llm/qwen3-8b.gguf")))

    @property
    def state_path(self) -> Path:
        return Path(str(getattr(self.settings, "native_llama_state_path", "memory/native_llama_runtime.json")))

    def _emit(self, name: str, **payload: Any) -> None:
        if self.events is not None:
            try:
                self.events.emit(name, **payload)
            except Exception:
                pass

    def _health(self, timeout: float = 0.8) -> bool:
        try:
            req = request.Request(self.base_url + "/health", method="GET")
            with request.urlopen(req, timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except Exception:
            try:
                req = request.Request(self.base_url + "/v1/models", method="GET")
                with request.urlopen(req, timeout=timeout) as response:
                    return 200 <= int(response.status) < 300
            except Exception:
                return False

    def _pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                text = (completed.stdout or b"").decode("utf-8", errors="replace")
                return f'"{pid}"' in text
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _read_state_pid(self) -> int | None:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
            pid = int(data.get("pid") or 0)
            return pid or None
        except Exception:
            return None

    def _write_state(self, pid: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({
            "pid": int(pid),
            "url": self.base_url,
            "model_path": str(self.model_path),
            "owned_by": "JARVIS",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _terminate_pid(self, pid: int) -> bool:
        if pid <= 0:
            return True
        try:
            if os.name == "nt":
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                return completed.returncode == 0 or not self._pid_alive(pid)
            os.kill(pid, 15)
            return True
        except Exception:
            return False

    def _cleanup_failed_startup(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass

        self._process = None
        self._owned = False

        try:
            self.state_path.unlink(missing_ok=True)
        except Exception:
            pass

        if self._log_handle is not None:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def ensure_started(self) -> NativeRuntimeStatus:
        with self._lock:
            generation = self._lifecycle_generation

        # Serialize startup attempts without holding the lifecycle state lock
        # across health waits. shutdown() must remain able to cancel startup.
        with self._startup_lock:
            with self._lock:
                if generation != self._lifecycle_generation:
                    raise LocalLLMError("LLM_STARTUP_CANCELLED")

            # Healthy fast path. PID resolution is intentionally outside the
            # lifecycle lock because it may touch the state file or OS.
            if self._health():
                with self._lock:
                    if generation != self._lifecycle_generation:
                        raise LocalLLMError("LLM_STARTUP_CANCELLED")
                    process = self._process
                    owned = bool(self._owned)

                pid = (
                    process.pid
                    if process is not None and process.poll() is None
                    else self._read_state_pid()
                )

                # Final fast-path barrier: shutdown may have completed while
                # PID resolution was in progress.
                with self._lock:
                    if generation != self._lifecycle_generation:
                        raise LocalLLMError("LLM_STARTUP_CANCELLED")

                    if process is not None:
                        current_process = self._process
                        if (
                            current_process is not process
                            or current_process.poll() is not None
                        ):
                            raise LocalLLMError("LLM_STARTUP_CANCELLED")
                        owned = bool(self._owned)

                    return NativeRuntimeStatus(
                        True,
                        pid,
                        self.base_url,
                        str(self.model_path),
                        owned,
                    )

            if not self.executable.is_file():
                raise LocalLLMError(
                    f"Native llama.cpp runtime not installed: {self.executable}. "
                    "Run .\\setup_native_brain.ps1."
                )

            if not self.model_path.is_file():
                raise LocalLLMError(
                    f"Native local model not found: {self.model_path}. "
                    "Run .\\setup_native_brain.ps1."
                )

            log_path = (
                Path(str(getattr(self.settings, "log_dir", "logs")))
                / "native_llama_server.log"
            )
            log_path.parent.mkdir(parents=True, exist_ok=True)

            args = [
                str(self.executable.resolve()),
                "-m",
                str(self.model_path.resolve()),
                "--host",
                self.host,
                "--port",
                str(self.port),
                "-c",
                str(int(getattr(self.settings, "llm_num_ctx", 8192))),
                "-ngl",
                str(
                    int(
                        getattr(
                            self.settings,
                            "native_llama_gpu_layers",
                            99,
                        )
                    )
                ),
                "--jinja",
            ]

            threads = int(
                getattr(
                    self.settings,
                    "native_llama_threads",
                    6,
                )
            )
            if threads > 0:
                args += ["-t", str(threads)]

            if bool(
                getattr(
                    self.settings,
                    "native_llama_flash_attention",
                    True,
                )
            ):
                args += ["--flash-attn", "on"]

            creationflags = 0
            if os.name == "nt":
                creationflags = int(
                    getattr(
                        subprocess,
                        "CREATE_NO_WINDOW",
                        0,
                    )
                )

            self._emit(
                "NATIVE_LLM_STARTING",
                executable=str(self.executable),
                model=str(self.model_path),
                port=self.port,
            )

            # Launch state is committed atomically under the lifecycle lock.
            with self._lock:
                if generation != self._lifecycle_generation:
                    raise LocalLLMError("LLM_STARTUP_CANCELLED")

                try:
                    self._log_handle = log_path.open(
                        "ab",
                        buffering=0,
                    )
                    self._process = subprocess.Popen(
                        args,
                        stdin=subprocess.DEVNULL,
                        stdout=self._log_handle,
                        stderr=subprocess.STDOUT,
                        creationflags=creationflags,
                    )
                    self._owned = True
                    self._write_state(self._process.pid)
                except Exception:
                    self._cleanup_failed_startup()
                    raise

            # shutdown may have raced immediately after process creation.
            with self._lock:
                if generation != self._lifecycle_generation:
                    self._cleanup_failed_startup()
                    raise LocalLLMError("LLM_STARTUP_CANCELLED")

            timeout = max(
                5.0,
                float(
                    getattr(
                        self.settings,
                        "native_llama_start_timeout_seconds",
                        45.0,
                    )
                ),
            )
            deadline = monotonic() + timeout

            while monotonic() < deadline:
                with self._lock:
                    if generation != self._lifecycle_generation:
                        self._cleanup_failed_startup()
                        raise LocalLLMError("LLM_STARTUP_CANCELLED")
                    process = self._process

                if process is None:
                    raise LocalLLMError("LLM_STARTUP_PROCESS_LOST")

                if process.poll() is not None:
                    code = int(process.returncode or 0)
                    code_hex = f"0x{(code & 0xFFFFFFFF):08X}"
                    tail = ""

                    try:
                        raw = log_path.read_bytes()[-4096:]
                        tail = raw.decode(
                            "utf-8",
                            errors="replace",
                        ).strip()
                    except Exception:
                        tail = ""

                    motw_count = 0
                    if os.name == "nt":
                        try:
                            for candidate in self.executable.parent.rglob("*"):
                                if not candidate.is_file():
                                    continue
                                try:
                                    if os.path.exists(
                                        str(candidate)
                                        + ":Zone.Identifier"
                                    ):
                                        motw_count += 1
                                except Exception:
                                    pass
                        except Exception:
                            pass

                    detail = (
                        tail[-1200:]
                        if tail
                        else "no log output"
                    )

                    with self._lock:
                        self._cleanup_failed_startup()

                    if code_hex == "0xC0E90002":
                        raise LocalLLMError(
                            "llama-server was rejected by Windows during "
                            "startup "
                            f"({code_hex}: Bad Image / Code Integrity). "
                            f"Runtime MOTW files detected: {motw_count}. "
                            "Run .\\setup_native_brain.ps1 -RepairRuntime to "
                            "reinstall the pinned llama.cpp runtime from "
                            "SHA-256-verified archives, then restart JARVIS. "
                            f"Log tail: {detail}"
                        )

                    raise LocalLLMError(
                        "llama-server exited during startup with code "
                        f"{code} ({code_hex}); runtime MOTW files: "
                        f"{motw_count}; log tail: {detail}"
                    )

                healthy = self._health(timeout=1.0)

                with self._lock:
                    if generation != self._lifecycle_generation:
                        self._cleanup_failed_startup()
                        raise LocalLLMError("LLM_STARTUP_CANCELLED")
                    process = self._process

                if healthy:
                    if process is None or process.poll() is not None:
                        continue

                    self._emit(
                        "NATIVE_LLM_STARTED",
                        pid=process.pid,
                        model=str(self.model_path),
                    )

                    # Final success barrier: the started event itself may take
                    # long enough for shutdown to complete concurrently.
                    with self._lock:
                        if generation != self._lifecycle_generation:
                            raise LocalLLMError("LLM_STARTUP_CANCELLED")

                        current_process = self._process
                        if (
                            current_process is None
                            or current_process is not process
                            or current_process.poll() is not None
                        ):
                            raise LocalLLMError("LLM_STARTUP_CANCELLED")

                        return NativeRuntimeStatus(
                            True,
                            current_process.pid,
                            self.base_url,
                            str(self.model_path),
                            True,
                        )

                sleep(0.25)

            self.shutdown(reason="startup_timeout")

            raise LocalLLMError(
                "Native llama.cpp runtime did not become healthy within "
                f"{timeout:.0f}s; see {log_path}."
            )
    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        with self._lock:
            self._lifecycle_generation += 1
            pid = None
            if self._process is not None and self._process.poll() is None:
                pid = self._process.pid
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception:
                    try:
                        self._process.kill()
                    except Exception:
                        pass
            else:
                pid = self._read_state_pid()
                if pid and self._pid_alive(pid):
                    self._terminate_pid(pid)
            self._process = None
            self._owned = False
            try:
                self.state_path.unlink(missing_ok=True)
            except Exception:
                pass
            if self._log_handle is not None:
                try:
                    self._log_handle.close()
                except Exception:
                    pass
                self._log_handle = None
            running = self._health(timeout=0.4)
            self._emit("NATIVE_LLM_STOPPED", reason=reason, pid=pid, running=running)
            return {"ok": not running, "released": not running, "pid": pid, "reason": reason}

    def status(self) -> NativeRuntimeStatus:
        running = self._health(timeout=0.4)
        pid = self._process.pid if self._process and self._process.poll() is None else self._read_state_pid()
        return NativeRuntimeStatus(running, pid, self.base_url, str(self.model_path), bool(self._owned))


class NativeLlamaClient:
    """Compatibility facade over the JARVIS-owned llama.cpp HTTP runtime."""

    def __init__(self, settings, events=None):
        self.settings = settings
        self.events = events
        self.runtime = NativeLlamaRuntime(settings, events)

    @staticmethod
    def _json(url: str, payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")[:1200]
            raise LocalLLMError(f"llama.cpp HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise LocalLLMError(f"llama.cpp request failed: {type(exc).__name__}: {exc}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise LocalLLMError("llama.cpp returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise LocalLLMError("llama.cpp returned an invalid response shape")
        return data

    @staticmethod
    def _messages(messages: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        pending_tool_ids: list[tuple[str, str]] = []
        for item in messages or []:
            if isinstance(item, dict):
                role = str(item.get("role") or "user")
                content = item.get("content", "")
                row: dict[str, Any] = {"role": role, "content": content}
                if role == "assistant" and item.get("tool_calls"):
                    calls = item.get("tool_calls") or []
                    row["tool_calls"] = calls
                    for call in calls:
                        try:
                            pending_tool_ids.append((str(call["function"]["name"]), str(call.get("id") or "")))
                        except Exception:
                            pass
                if role == "tool":
                    name = str(item.get("tool_name") or item.get("name") or "")
                    row["name"] = name
                    for idx, (tool_name, call_id) in enumerate(list(pending_tool_ids)):
                        if tool_name == name and call_id:
                            row["tool_call_id"] = call_id
                            pending_tool_ids.pop(idx)
                            break
                rows.append(row)
                continue

            role = str(getattr(item, "role", "assistant") or "assistant")
            content = getattr(item, "content", "") or ""
            row = {"role": role, "content": content}
            tool_calls = getattr(item, "tool_calls", None) or []
            if tool_calls:
                rendered = []
                for index, call in enumerate(tool_calls):
                    fn = getattr(call, "function", None)
                    name = str(getattr(fn, "name", "") or "")
                    arguments = getattr(fn, "arguments", {}) or {}
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments, ensure_ascii=False)
                    call_id = str(getattr(call, "id", "") or f"call_{len(rows)}_{index}")
                    rendered.append({
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    })
                    pending_tool_ids.append((name, call_id))
                row["tool_calls"] = rendered
            rows.append(row)
        return rows

    @staticmethod
    def _llama_safe_schema(value: Any) -> Any:
        """Reduce JSON Schema to the subset reliably accepted by llama.cpp grammar."""
        if isinstance(value, list):
            return [NativeLlamaClient._llama_safe_schema(x) for x in value]
        if not isinstance(value, dict):
            return value
        allowed = {"type", "properties", "required", "items", "enum", "description"}
        out = {}
        for key, item in value.items():
            if key not in allowed:
                continue
            if key == "properties" and isinstance(item, dict):
                out[key] = {str(k): NativeLlamaClient._llama_safe_schema(v) for k, v in item.items()}
            else:
                out[key] = NativeLlamaClient._llama_safe_schema(item)
        return out

    @classmethod
    def _llama_safe_tools(cls, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        safe = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            fn = dict(tool.get("function") or {})
            name = str(fn.get("name") or "").strip()
            if not name:
                continue
            safe.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(fn.get("description") or "")[:600],
                    "parameters": cls._llama_safe_schema(fn.get("parameters") or {"type": "object", "properties": {}}),
                },
            })
        return safe

    @staticmethod
    def _tool_calls(raw_calls: list[dict[str, Any]] | None) -> list[Any]:
        result = []
        for index, call in enumerate(raw_calls or []):
            fn = call.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    parsed = json.loads(args)
                    args = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    args = {}
            result.append(SimpleNamespace(
                id=str(call.get("id") or f"call_{index}"),
                function=SimpleNamespace(name=str(fn.get("name") or ""), arguments=args),
            ))
        return result

    def chat(self, *, model: str, messages: list[Any], think: bool = False, keep_alive: Any = None,
             options: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None,
             format: dict[str, Any] | None = None, stream: bool = False, **_: Any) -> Any:
        del model, stream
        release_after = str(keep_alive).strip().lower() in {"0", "0s", "0.0"} or (keep_alive == 0 and not isinstance(keep_alive, bool))
        self.runtime.ensure_started()
        options = dict(options or {})
        payload: dict[str, Any] = {
            "model": "jarvis-local",
            "messages": self._messages(messages),
            "temperature": float(options.get("temperature", 0.2)),
            "max_tokens": int(options.get("num_predict", 280)),
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": bool(think)},
        }
        if tools:
            safe_tools = self._llama_safe_tools(tools)
            if safe_tools:
                payload["tools"] = safe_tools
                payload["tool_choice"] = "auto"
        if isinstance(format, dict):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "jarvis_schema", "strict": True, "schema": format},
            }
        timeout = float(getattr(self.settings, "native_llama_request_timeout_seconds", 180.0))
        data = self._json(self.runtime.base_url + "/v1/chat/completions", payload, timeout=timeout)
        choices = list(data.get("choices") or [])
        if not choices:
            raise LocalLLMError("llama.cpp returned no completion choices")
        choice = choices[0] or {}
        raw_message = choice.get("message") or {}
        message = SimpleNamespace(
            role="assistant",
            content=str(raw_message.get("content") or ""),
            thinking=str(raw_message.get("reasoning_content") or raw_message.get("reasoning") or ""),
            tool_calls=self._tool_calls(raw_message.get("tool_calls") or []),
        )
        usage = data.get("usage") or {}
        result = SimpleNamespace(
            message=message,
            done_reason=str(choice.get("finish_reason") or ""),
            eval_count=int(usage.get("completion_tokens") or 0),
            model="jarvis-local",
        )
        if release_after:
            self.runtime.shutdown(reason="keep_alive_zero")
        return result

    def list(self) -> Any:
        model = self.runtime.model_path
        rows = [SimpleNamespace(model=str(getattr(self.settings, "model", "qwen3:8b")))] if model.is_file() else []
        return SimpleNamespace(models=rows)

    def show(self, model: str) -> Any:
        configured = str(getattr(self.settings, "model", "qwen3:8b"))
        if str(model or "") != configured:
            raise LocalLLMError(f"Model not configured in native text runtime: {model}")
        if not self.runtime.model_path.is_file():
            raise LocalLLMError("Native model not installed")
        return {"ok": True, "path": str(self.runtime.model_path)}

    def ps(self) -> Any:
        status = self.runtime.status()
        rows = []
        if status.running:
            rows.append(SimpleNamespace(
                model=str(getattr(self.settings, "model", "qwen3:8b")),
                size=None,
                size_vram=None,
                expires_at="managed-by-jarvis",
            ))
        return SimpleNamespace(models=rows)

    def generate(self, *, model: str, prompt: str = "", keep_alive: Any = None, **_: Any) -> Any:
        del model, prompt
        if str(keep_alive) in {"0", "0s", "0.0"} or (keep_alive == 0 and not isinstance(keep_alive, bool)):
            self.runtime.shutdown(reason="release_model")
        return {"ok": True}

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        return self.runtime.shutdown(reason=reason)



class OllamaLocalCompatClient:
    """Local-only compatibility executor using Ollama's loopback HTTP API.

    This class intentionally does not import the Ollama SDK. JARVIS still owns
    all orchestration, memory, tools, grounding and response policy; Ollama is
    only used to execute the configured local Qwen weights when Windows refuses
    to load the verified standalone llama.cpp runtime.
    """

    def __init__(self, settings, events=None):
        self.settings = settings
        self.events = events
        self.base_url = str(getattr(settings, "ollama_host", "http://127.0.0.1:11434") or "http://127.0.0.1:11434").rstrip("/")

    def _emit(self, name: str, **payload: Any) -> None:
        if self.events is not None:
            try:
                self.events.emit(name, **payload)
            except Exception:
                pass

    def _request(self, path: str, payload: dict[str, Any] | None = None, *, timeout: float = 180.0) -> dict[str, Any]:
        url = self.base_url + path
        data = None
        method = "GET"
        headers: dict[str, str] = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            method = "POST"
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")[:1200]
            raise LocalLLMError(f"Local Ollama executor HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise LocalLLMError(f"Local Ollama executor unavailable: {type(exc).__name__}: {exc}") from exc
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            raise LocalLLMError("Local Ollama executor returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise LocalLLMError("Local Ollama executor returned an invalid response shape")
        return parsed

    def health(self, *, require_model: bool = True) -> dict[str, Any]:
        try:
            data = self._request("/api/tags", timeout=2.0)
            names = {
                str(row.get("model") or row.get("name") or "")
                for row in (data.get("models") or [])
                if isinstance(row, dict)
            }
            configured = str(getattr(self.settings, "model", "qwen3:8b"))
            model_ok = configured in names
            return {"ok": bool(model_ok or not require_model), "online": True, "model_ok": model_ok, "model": configured}
        except Exception as exc:
            return {"ok": False, "online": False, "model_ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def chat(self, *, model: str, messages: list[Any], think: bool = False, keep_alive: Any = None,
             options: dict[str, Any] | None = None, tools: list[dict[str, Any]] | None = None,
             format: dict[str, Any] | None = None, stream: bool = False, **_: Any) -> Any:
        del stream
        payload: dict[str, Any] = {
            "model": str(model or getattr(self.settings, "model", "qwen3:8b")),
            "messages": NativeLlamaClient._messages(messages),
            "stream": False,
            "think": bool(think),
            "options": dict(options or {}),
        }
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        if tools:
            payload["tools"] = tools
        if isinstance(format, dict):
            payload["format"] = format
        timeout = float(getattr(self.settings, "native_llama_request_timeout_seconds", 180.0))
        data = self._request("/api/chat", payload, timeout=timeout)
        raw_message = data.get("message") or {}
        message = SimpleNamespace(
            role="assistant",
            content=str(raw_message.get("content") or ""),
            thinking=str(raw_message.get("thinking") or raw_message.get("reasoning_content") or ""),
            tool_calls=NativeLlamaClient._tool_calls(raw_message.get("tool_calls") or []),
        )
        return SimpleNamespace(
            message=message,
            done_reason=str(data.get("done_reason") or ("stop" if data.get("done") else "")),
            eval_count=int(data.get("eval_count") or 0),
            model=str(data.get("model") or model or getattr(self.settings, "model", "qwen3:8b")),
        )

    def list(self) -> Any:
        data = self._request("/api/tags", timeout=3.0)
        rows = []
        for row in data.get("models") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("model") or row.get("name") or "")
            if name:
                rows.append(SimpleNamespace(model=name, size=row.get("size")))
        return SimpleNamespace(models=rows)

    def show(self, model: str) -> Any:
        return self._request("/api/show", {"model": str(model)}, timeout=10.0)

    def ps(self) -> Any:
        try:
            data = self._request("/api/ps", timeout=3.0)
        except Exception:
            return SimpleNamespace(models=[])
        rows = []
        for row in data.get("models") or []:
            if not isinstance(row, dict):
                continue
            rows.append(SimpleNamespace(
                model=str(row.get("model") or row.get("name") or ""),
                size=row.get("size"),
                size_vram=row.get("size_vram"),
                expires_at=str(row.get("expires_at") or ""),
            ))
        return SimpleNamespace(models=rows)

    def generate(self, *, model: str, prompt: str = "", keep_alive: Any = None, **_: Any) -> Any:
        payload: dict[str, Any] = {"model": str(model), "prompt": str(prompt or ""), "stream": False}
        if keep_alive is not None:
            payload["keep_alive"] = keep_alive
        return self._request("/api/generate", payload, timeout=30.0)

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        model = str(getattr(self.settings, "model", "qwen3:8b"))
        try:
            self.generate(model=model, prompt="", keep_alive=0)
            self._emit("OLLAMA_COMPAT_MODEL_RELEASED", model=model, reason=reason)
            return {"ok": True, "released": True, "model": model, "reason": reason, "executor": "ollama_local_compat"}
        except Exception as exc:
            return {"ok": False, "released": False, "model": model, "reason": reason, "executor": "ollama_local_compat", "error": str(exc)}


def _native_windows_code_integrity_error(exc: BaseException) -> bool:
    text = str(exc or "").upper()
    return "0XC0E90002" in text or "CODE INTEGRITY" in text or "BAD IMAGE" in text


class JarvisLocalClient:
    """Executor abstraction owned by the JARVIS Core.

    Native llama.cpp is preferred. The Ollama compatibility path is activated
    only when the native runtime is rejected/unavailable and local fallback is
    explicitly enabled in settings. No external provider is ever contacted.
    """

    def __init__(self, settings, events=None, *, native_client=None, compat_client=None):
        self.settings = settings
        self.events = events
        self.native = native_client or NativeLlamaClient(settings, events)
        self.compat = compat_client or OllamaLocalCompatClient(settings, events)
        self._selected: str | None = None
        self._fallback_reason: str | None = None

    def _emit(self, name: str, **payload: Any) -> None:
        if self.events is not None:
            try:
                self.events.emit(name, **payload)
            except Exception:
                pass

    @property
    def allow_compat(self) -> bool:
        return bool(getattr(self.settings, "local_llm_allow_ollama_compat", True))

    @property
    def state_path(self) -> Path:
        return Path(str(getattr(self.settings, "local_llm_executor_state_path", "memory/local_llm_executor.json")))

    def _write_executor_state(self, selected: str, reason: str | None = None) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({
                "selected": str(selected),
                "model": str(getattr(self.settings, "model", "qwen3:8b")),
                "reason": str(reason or ""),
                "external_ai": False,
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _select_compat(self, reason: str) -> None:
        status = self.compat.health(require_model=True)
        if not status.get("ok"):
            raise LocalLLMError(
                "Native JARVIS executor is unavailable and the local Ollama compatibility executor "
                f"is not ready for {getattr(self.settings, 'model', 'qwen3:8b')}: {status.get('error') or status}"
            )
        self._selected = "ollama_local_compat"
        self._fallback_reason = str(reason or "native_unavailable")[:800]
        self._write_executor_state(self._selected, self._fallback_reason)
        self._emit("LOCAL_LLM_EXECUTOR_FALLBACK", executor=self._selected, reason=self._fallback_reason)

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._selected == "ollama_local_compat":
            return getattr(self.compat, method)(*args, **kwargs)
        try:
            result = getattr(self.native, method)(*args, **kwargs)
            if method == "chat":
                self._selected = "native_llama"
                self._write_executor_state(self._selected, "native_runtime_healthy")
            return result
        except LocalLLMError as exc:
            if not self.allow_compat:
                raise
            # Code Integrity is the primary supported fallback reason. Missing
            # or broken standalone runtime also falls back if the existing
            # loopback executor is healthy, so JARVIS remains usable.
            text = str(exc or "").lower()
            fallback_eligible = (
                _native_windows_code_integrity_error(exc)
                or "runtime not installed" in text
                or "did not become healthy" in text
                or "exited during startup" in text
            )
            if not fallback_eligible:
                raise
            self._select_compat(str(exc))
            return getattr(self.compat, method)(*args, **kwargs)

    def chat(self, **kwargs: Any) -> Any:
        return self._call("chat", **kwargs)

    def list(self) -> Any:
        # A local GGUF file proves model availability for native execution, but
        # if it is absent the compatibility executor may still own the same Qwen
        # model in its local cache.
        names: set[str] = set()
        rows: list[Any] = []
        try:
            native = self.native.list()
            for row in getattr(native, "models", []) or []:
                name = str(getattr(row, "model", "") or "")
                if name and name not in names:
                    names.add(name); rows.append(row)
        except Exception:
            pass
        if self.allow_compat:
            try:
                compat = self.compat.list()
                for row in getattr(compat, "models", []) or []:
                    name = str(getattr(row, "model", "") or "")
                    if name and name not in names:
                        names.add(name); rows.append(row)
            except Exception:
                pass
        return SimpleNamespace(models=rows)

    def show(self, model: str) -> Any:
        if self._selected == "ollama_local_compat":
            return self.compat.show(model)
        try:
            return self.native.show(model)
        except Exception:
            if self.allow_compat:
                return self.compat.show(model)
            raise

    def ps(self) -> Any:
        if self._selected == "ollama_local_compat":
            return self.compat.ps()
        try:
            native = self.native.ps()
            if getattr(native, "models", None):
                return native
        except Exception:
            pass
        if self.allow_compat:
            return self.compat.ps()
        return SimpleNamespace(models=[])

    def generate(self, **kwargs: Any) -> Any:
        if self._selected == "ollama_local_compat":
            return self.compat.generate(**kwargs)
        try:
            return self.native.generate(**kwargs)
        except Exception:
            if self.allow_compat:
                return self.compat.generate(**kwargs)
            raise

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        native_result = self.native.shutdown(reason=reason)
        compat_result = None
        if self.allow_compat and self._selected == "ollama_local_compat":
            compat_result = self.compat.shutdown(reason=reason)
        ok = bool(native_result.get("ok", True)) and (compat_result is None or bool(compat_result.get("ok", True)))
        return {
            "ok": ok,
            "released": ok,
            "executor": self._selected or "native_llama",
            "native": native_result,
            "compat": compat_result,
            "reason": reason,
        }

    def executor_status(self) -> dict[str, Any]:
        compat = self.compat.health(require_model=True) if self.allow_compat else {"ok": False, "disabled": True}
        native_status = self.native.runtime.status()
        return {
            "configured": "jarvis_local",
            "selected": self._selected,
            "native_running": native_status.running,
            "native_model_path": native_status.model_path,
            "ollama_compat_allowed": self.allow_compat,
            "ollama_compat_ready": bool(compat.get("ok")),
            "fallback_reason": self._fallback_reason,
            "external_ai": False,
        }

def build_local_client(settings, events=None):
    backend = str(getattr(settings, "local_llm_backend", "jarvis_local") or "jarvis_local").strip().lower()
    if backend in {"jarvis_local", "auto", "auto_local"}:
        return JarvisLocalClient(settings, events)
    if backend == "native_llama":
        return NativeLlamaClient(settings, events)
    if backend in {"ollama_local_compat", "ollama_compat"}:
        return OllamaLocalCompatClient(settings, events)
    raise LocalLLMError(f"Unsupported local_llm_backend: {backend}")
