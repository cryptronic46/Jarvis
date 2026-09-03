from __future__ import annotations

"""JARVIS-owned native multimodal inference runtime.

This module is deliberately separate from the text reasoning runtime.  It starts
another instance of the already trusted llama.cpp ``llama-server`` binary on a
loopback-only port, loads a local vision GGUF + mmproj pair, and submits images
through the OpenAI-compatible multimodal endpoint.  No external AI provider is
contacted during inference.
"""

from dataclasses import dataclass
from pathlib import Path
from threading import RLock, Timer
from time import monotonic, sleep
from typing import Any
from urllib import error, request
import base64
import json
import mimetypes
import os
import subprocess


class LocalVisionError(RuntimeError):
    pass


@dataclass(slots=True)
class NativeVisionStatus:
    running: bool
    pid: int | None
    url: str
    model_path: str
    mmproj_path: str
    owned: bool


class NativeVisionRuntime:
    def __init__(self, settings, events=None) -> None:
        self.settings = settings
        self.events = events
        self._lock = RLock()
        self._process: subprocess.Popen | None = None
        self._owned = False
        self._log_handle = None

    @property
    def host(self) -> str:
        # The visual runtime is intentionally loopback-only.
        return "127.0.0.1"

    @property
    def port(self) -> int:
        return int(getattr(self.settings, "vision_native_port", 11436))

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def executable(self) -> Path:
        return Path(str(getattr(
            self.settings,
            "native_llama_server_path",
            "runtime/llama.cpp/llama-server.exe",
        )))

    @property
    def model_path(self) -> Path:
        return Path(str(getattr(
            self.settings,
            "vision_native_model_path",
            "models/vision/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf",
        )))

    @property
    def mmproj_path(self) -> Path:
        return Path(str(getattr(
            self.settings,
            "vision_native_mmproj_path",
            "models/vision/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf",
        )))

    @property
    def state_path(self) -> Path:
        return Path(str(getattr(
            self.settings,
            "vision_native_state_path",
            "memory/native_vision_runtime.json",
        )))

    def _emit(self, name: str, **payload: Any) -> None:
        if self.events is None:
            return
        try:
            self.events.emit(name, **payload)
        except Exception:
            pass

    def _health(self, timeout: float = 0.8) -> bool:
        for endpoint in ("/health", "/v1/models"):
            try:
                req = request.Request(self.base_url + endpoint, method="GET")
                with request.urlopen(req, timeout=timeout) as response:
                    if 200 <= int(response.status) < 300:
                        return True
            except Exception:
                continue
        return False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
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
        self.state_path.write_text(
            json.dumps({
                "pid": int(pid),
                "url": self.base_url,
                "model_path": str(self.model_path),
                "mmproj_path": str(self.mmproj_path),
                "owned_by": "JARVIS",
                "external_ai": False,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _terminate_pid(pid: int) -> bool:
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
                return completed.returncode == 0 or not NativeVisionRuntime._pid_alive(pid)
            os.kill(pid, 15)
            return True
        except Exception:
            return False

    def configured(self) -> tuple[bool, str | None]:
        # Report the actionable vision assets first. setup_vision.ps1 installs
        # these explicitly, while the llama.cpp binary belongs to the native
        # brain runtime and has its own setup path.
        if not self.model_path.is_file():
            return False, "VISION_MODEL_NOT_INSTALLED"
        if not self.mmproj_path.is_file():
            return False, "VISION_MMPROJ_NOT_INSTALLED"
        if not self.executable.is_file():
            return False, "VISION_LLAMA_RUNTIME_NOT_INSTALLED"
        return True, None

    def ensure_started(self) -> NativeVisionStatus:
        with self._lock:
            if self._health():
                pid = self._process.pid if self._process and self._process.poll() is None else self._read_state_pid()
                return NativeVisionStatus(
                    True, pid, self.base_url, str(self.model_path), str(self.mmproj_path), bool(self._owned)
                )

            configured, error_code = self.configured()
            if not configured:
                raise LocalVisionError(error_code or "VISION_NOT_CONFIGURED")

            log_path = Path(str(getattr(self.settings, "log_dir", "logs"))) / "native_vision_server.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_handle = log_path.open("ab", buffering=0)

            args = [
                str(self.executable.resolve()),
                "-m", str(self.model_path.resolve()),
                "--mmproj", str(self.mmproj_path.resolve()),
                "--host", self.host,
                "--port", str(self.port),
                # Qwen2.5-VL needs enough room for image tokens plus the answer.
                "-c", str(max(8192, int(getattr(self.settings, "vision_native_ctx", 8192)))),
                "-ngl", str(int(getattr(self.settings, "vision_native_gpu_layers", 99))),
                "--alias", "jarvis-vision",
                "--jinja",
            ]
            threads = int(getattr(self.settings, "vision_native_threads", 6))
            if threads > 0:
                args += ["-t", str(threads)]

            creationflags = 0
            if os.name == "nt":
                creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))

            self._emit(
                "NATIVE_VISION_STARTING",
                executable=str(self.executable),
                model=str(self.model_path),
                mmproj=str(self.mmproj_path),
                port=self.port,
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

            timeout = max(10.0, float(getattr(self.settings, "vision_native_start_timeout_seconds", 90.0)))
            deadline = monotonic() + timeout
            while monotonic() < deadline:
                if self._process.poll() is not None:
                    code = int(self._process.returncode or 0)
                    tail = ""
                    try:
                        tail = log_path.read_bytes()[-5000:].decode("utf-8", errors="replace").strip()
                    except Exception:
                        pass
                    raise LocalVisionError(
                        f"native vision llama-server exited with code {code}; log tail: {tail[-1600:] or 'no log output'}"
                    )
                if self._health(timeout=1.0):
                    self._emit("NATIVE_VISION_STARTED", pid=self._process.pid, model=str(self.model_path))
                    return NativeVisionStatus(
                        True,
                        self._process.pid,
                        self.base_url,
                        str(self.model_path),
                        str(self.mmproj_path),
                        True,
                    )
                sleep(0.25)

            self.shutdown(reason="startup_timeout")
            raise LocalVisionError(
                f"Native visual runtime did not become healthy within {timeout:.0f}s; see {log_path}."
            )

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        with self._lock:
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
            self._emit("NATIVE_VISION_STOPPED", reason=reason, pid=pid, running=running)
            return {"ok": not running, "released": not running, "pid": pid, "reason": reason}

    def status(self) -> NativeVisionStatus:
        running = self._health(timeout=0.4)
        pid = self._process.pid if self._process and self._process.poll() is None else self._read_state_pid()
        return NativeVisionStatus(
            running,
            pid,
            self.base_url,
            str(self.model_path),
            str(self.mmproj_path),
            bool(self._owned),
        )


class NativeVisionClient:
    def __init__(self, settings, events=None) -> None:
        self.settings = settings
        self.events = events
        self.runtime = NativeVisionRuntime(settings, events)
        self._idle_lock = RLock()
        self._idle_timer: Timer | None = None

    @staticmethod
    def _duration_seconds(value: Any, default: float = 120.0) -> float:
        text = str(value if value is not None else "").strip().lower()
        if not text:
            return max(0.0, float(default))
        multiplier = 1.0
        if text.endswith("ms"):
            multiplier = 0.001
            text = text[:-2]
        elif text.endswith("s"):
            text = text[:-1]
        elif text.endswith("m"):
            multiplier = 60.0
            text = text[:-1]
        elif text.endswith("h"):
            multiplier = 3600.0
            text = text[:-1]
        try:
            return max(0.0, float(text.strip()) * multiplier)
        except (TypeError, ValueError):
            return max(0.0, float(default))

    def _cancel_idle_shutdown(self) -> None:
        with self._idle_lock:
            timer = self._idle_timer
            self._idle_timer = None
            if timer is not None:
                try:
                    timer.cancel()
                except Exception:
                    pass

    def _expire_idle_runtime(self) -> None:
        with self._idle_lock:
            self._idle_timer = None
        self.runtime.shutdown(reason="vision_keep_alive_expired")

    def _schedule_idle_shutdown(self) -> None:
        keep_alive = getattr(self.settings, "vision_keep_alive", "2m")
        seconds = self._duration_seconds(keep_alive, default=120.0)
        self._cancel_idle_shutdown()
        if seconds <= 0.0:
            self.runtime.shutdown(reason="vision_keep_alive_expired")
            return
        timer = Timer(seconds, self._expire_idle_runtime)
        timer.daemon = True
        with self._idle_lock:
            self._idle_timer = timer
        timer.start()

    @staticmethod
    def _json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace")[:1600]
            raise LocalVisionError(f"llama.cpp vision HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise LocalVisionError(f"llama.cpp vision request failed: {type(exc).__name__}: {exc}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise LocalVisionError("llama.cpp vision returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise LocalVisionError("llama.cpp vision returned an invalid response shape")
        return data

    @staticmethod
    def _image_data_url(path: Path) -> str:
        try:
            raw = path.read_bytes()
        except Exception as exc:
            raise LocalVisionError(f"Unable to read image: {type(exc).__name__}: {exc}") from exc
        encoded = base64.b64encode(raw).decode("ascii")
        # llama.cpp multimodal examples use an unknown image MIME for data URLs;
        # the backend detects the actual image format from the bytes.
        return f"data:image/unknown;base64,{encoded}"

    def configured(self) -> tuple[bool, str | None]:
        return self.runtime.configured()

    def analyze(self, image_path: str | Path, *, prompt: str, system: str) -> str:
        path = Path(image_path)
        if not path.is_file():
            raise LocalVisionError(f"IMAGE_NOT_FOUND: {path}")
        self.runtime.ensure_started()
        payload = {
            "model": "jarvis-vision",
            "messages": [
                {"role": "system", "content": str(system or "")},
                {
                    "role": "user",
                    "content": [
                        # Put the image first so the multimodal template binds the
                        # visual tokens before the textual instruction.
                        {"type": "image_url", "image_url": {"url": self._image_data_url(path)}},
                        {"type": "text", "text": str(prompt or "")},
                    ],
                },
            ],
            "temperature": 0.0,
            "max_tokens": int(getattr(self.settings, "vision_native_max_tokens", 700)),
            "stream": False,
        }
        timeout = max(10.0, float(getattr(self.settings, "vision_native_request_timeout_seconds", 180.0)))
        # llama.cpp's native OpenAI-compatible multimodal route is
        # /chat/completions. Keep /v1 only as an endpoint-compatibility fallback.
        try:
            data = self._json(self.runtime.base_url + "/chat/completions", payload, timeout)
        except LocalVisionError as first_exc:
            try:
                data = self._json(self.runtime.base_url + "/v1/chat/completions", payload, timeout)
            except LocalVisionError:
                raise first_exc
        choices = list(data.get("choices") or [])
        if not choices:
            raise LocalVisionError("llama.cpp vision returned no completion choices")
        message = (choices[0] or {}).get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text") or ""))
            content = "\n".join(parts)
        text = str(content or "").strip()
        if not text:
            raise LocalVisionError("llama.cpp vision returned an empty analysis")
        self._schedule_idle_shutdown()
        return text

    def shutdown(self, reason: str = "shutdown") -> dict[str, Any]:
        self._cancel_idle_shutdown()
        return self.runtime.shutdown(reason=reason)
