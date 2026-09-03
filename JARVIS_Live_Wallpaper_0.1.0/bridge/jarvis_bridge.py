from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import RLock
from typing import Any
import argparse
import json
import mimetypes
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.parse

try:
    import psutil
except ImportError as exc:
    raise SystemExit(
        "psutil não está instalado. Inicia o bridge com o Python da .venv do JARVIS."
    ) from exc


BRIDGE_VERSION = "0.1.0"
DEFAULT_CORE = Path(os.environ.get("JARVIS_CORE_ROOT", r"G:\JARVIS"))
CORE_LOCK = RLock()
NET_LOCK = RLock()
NETWORK_SAMPLE = {
    "at": None,
    "sent": None,
    "recv": None,
    "upload_mbps": 0.0,
    "download_mbps": 0.0,
}
CORE_IMPORTS: dict[str, Any] = {}


def read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_log(message: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"[{stamp}] {message}", flush=True)


def cpu_name() -> str:
    if platform.system().lower() == "windows":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except Exception:
            pass
    return platform.processor() or "CPU"


def cpu_temperature() -> float | None:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        preferred = []
        for name, entries in temps.items():
            for entry in entries:
                value = getattr(entry, "current", None)
                if value is None:
                    continue
                label = str(getattr(entry, "label", "") or "").lower()
                score = 0
                if "package" in label: score += 4
                if "cpu" in label: score += 3
                if name.lower() in {"coretemp","k10temp","zenpower"}: score += 5
                preferred.append((score, float(value)))
        if preferred:
            preferred.sort(reverse=True)
            return preferred[0][1]
    except Exception:
        pass
    return None


def nvidia_gpu() -> dict[str, Any] | None:
    commands = [
        "nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ]
    exe = next((x for x in commands if Path(x).exists()), "nvidia-smi")
    try:
        out = subprocess.check_output(
            [
                exe,
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total,clocks.current.graphics",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=2.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).strip().splitlines()
        if not out:
            return None
        parts = [x.strip() for x in out[0].split(",")]
        return {
            "name": parts[0],
            "temperature_c": float(parts[1]),
            "utilization_percent": float(parts[2]),
            "memory_used_mb": float(parts[3]),
            "memory_total_mb": float(parts[4]),
            "clock_mhz": float(parts[5]),
        }
    except Exception:
        return None


def local_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except Exception:
        return None
    finally:
        sock.close()


def likely_interface(ip: str | None) -> str:
    if not ip:
        return "LAN"
    try:
        for name, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if getattr(addr, "address", None) == ip:
                    lname = name.lower()
                    if "wi-fi" in lname or "wifi" in lname or "wlan" in lname:
                        return "Wi-Fi"
                    return name
    except Exception:
        pass
    return "LAN"


def network_rate() -> dict[str, float]:
    counters = psutil.net_io_counters()
    now = time.monotonic()
    with NET_LOCK:
        previous_at = NETWORK_SAMPLE["at"]
        previous_sent = NETWORK_SAMPLE["sent"]
        previous_recv = NETWORK_SAMPLE["recv"]

        if previous_at is not None:
            dt = max(.001, now - float(previous_at))
            NETWORK_SAMPLE["upload_mbps"] = max(
                0.0,
                (counters.bytes_sent - int(previous_sent)) * 8 / dt / 1_000_000,
            )
            NETWORK_SAMPLE["download_mbps"] = max(
                0.0,
                (counters.bytes_recv - int(previous_recv)) * 8 / dt / 1_000_000,
            )

        NETWORK_SAMPLE["at"] = now
        NETWORK_SAMPLE["sent"] = counters.bytes_sent
        NETWORK_SAMPLE["recv"] = counters.bytes_recv

        return {
            "upload_mbps": round(float(NETWORK_SAMPLE["upload_mbps"]), 2),
            "download_mbps": round(float(NETWORK_SAMPLE["download_mbps"]), 2),
        }


def collect_telemetry() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    freq = psutil.cpu_freq()
    ip = local_ip()
    rate = network_rate()

    return {
        "cpu": {
            "name": cpu_name(),
            "usage_percent": psutil.cpu_percent(interval=None),
            "frequency_mhz": (
                round(float(freq.current), 0)
                if freq and freq.current
                else None
            ),
            "temperature_c": cpu_temperature(),
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
        },
        "memory": {
            "percent": round(float(memory.percent), 1),
            "used_gb": round(float(memory.used) / 1024**3, 1),
            "available_gb": round(float(memory.available) / 1024**3, 1),
            "total_gb": round(float(memory.total) / 1024**3, 1),
        },
        "gpu": nvidia_gpu(),
        "network": {
            **rate,
            "local_ip": ip,
            "interface": likely_interface(ip),
        },
    }


@contextmanager
def core_cwd(core: Path):
    with CORE_LOCK:
        previous = Path.cwd()
        try:
            os.chdir(core)
            yield
        finally:
            os.chdir(previous)


def ensure_core_import(core: Path, key: str, module: str, attr: str):
    cache_key = f"{core}|{key}"
    if cache_key in CORE_IMPORTS:
        return CORE_IMPORTS[cache_key]

    core_text = str(core)
    if core_text not in sys.path:
        sys.path.insert(0, core_text)

    with core_cwd(core):
        mod = __import__(module, fromlist=[attr])
        value = getattr(mod, attr)
    CORE_IMPORTS[cache_key] = value
    return value


def get_environment(core: Path) -> dict[str, Any]:
    cache = core / ".cache" / "environment_furadouro.json"
    data = read_json(cache, None)
    if isinstance(data, dict):
        cached = data.get("_cached_at_epoch")
        try:
            age = time.time() - float(cached)
        except Exception:
            age = 10_000
        if age < 900:
            return data

    try:
        func = ensure_core_import(
            core,
            "environment",
            "jarvis_core.tools.environment_tools",
            "get_home_environment",
        )
        with core_cwd(core):
            data = func()
        if isinstance(data, dict):
            return data
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "location": {"label": "Furadouro, Ovar"},
        }

    return {"ok": False, "location": {"label": "Furadouro, Ovar"}}


def get_profile(core: Path) -> dict[str, Any]:
    data = read_json(core / "memory" / "profiles.json", None)
    if not isinstance(data, dict):
        data = read_json(core / "defaults" / "profiles.json", {}) or {}
    active_id = str(data.get("active_profile") or "owner")
    profile = dict((data.get("profiles") or {}).get(active_id) or {})
    profile["id"] = active_id
    return profile


def get_security(core: Path) -> dict[str, Any]:
    baseline = read_json(core / "memory" / "security_baseline.json", {}) or {}
    state = read_json(core / "memory" / "security_watch.json", {}) or {}
    fp = baseline.get("fingerprint") or {}
    return {
        "baseline_exists": bool(baseline),
        "baseline_created_at": baseline.get("created_at"),
        "last_check": state.get("checked_at"),
        "alerts": state.get("alerts") or [],
        "firewall_all_enabled": fp.get("firewall_all_enabled"),
        "defender_realtime_enabled": fp.get("defender_realtime_enabled"),
        "rdp_enabled": fp.get("rdp_enabled"),
        "remote_assistance_enabled": fp.get("remote_assistance_enabled"),
    }


def get_network_inventory(core: Path) -> dict[str, Any]:
    data = read_json(core / "memory" / "network_devices.json", {}) or {}
    rows = list((data.get("devices") or {}).values())
    active = [row for row in rows if row.get("active")]
    active.sort(key=lambda x: str(x.get("label") or x.get("ip") or ""))
    return {
        "updated_at": data.get("updated_at"),
        "active_devices": active,
        "known_count": len(rows),
    }


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except Exception:
        return None


def get_agenda(core: Path) -> dict[str, Any]:
    data = read_json(core / "memory" / "agenda.json", {}) or {}
    now = datetime.now().astimezone()
    today = now.date()

    pending = []
    today_rows = []
    for item in data.get("items") or []:
        if item.get("done"):
            continue
        row = dict(item)
        dt = parse_when(row.get("when"))
        if dt and dt < now - timedelta(minutes=2):
            continue
        pending.append(row)
        if dt and dt.astimezone().date() == today:
            today_rows.append(row)

    pending.sort(
        key=lambda x: (
            x.get("when") is None,
            x.get("when") or "9999",
            x.get("created_at") or "",
        )
    )

    return {
        "today_count": len(today_rows),
        "pending_count": len(pending),
        "upcoming": pending[:8],
    }


def get_integrations(core: Path) -> dict[str, Any]:
    data = read_json(core / "memory" / "integrations.json", None)
    if not isinstance(data, dict):
        data = read_json(core / "defaults" / "integrations.json", {}) or {}
    return {
        "local_agenda": {"configured": True, "status": "READY"},
        **data,
    }


def tail_events(path: Path, max_bytes: int = 350_000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            raw = f.read().decode("utf-8", errors="replace")
        lines = raw.splitlines()
        if size > max_bytes and lines:
            lines = lines[1:]
        events = []
        for line in lines[-500:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
        return events
    except Exception:
        return []


def core_process_running(core: Path) -> bool:
    core_lower = str(core).lower()
    try:
        for proc in psutil.process_iter(attrs=["name", "cmdline"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or []).lower()
                name = str(proc.info.get("name") or "").lower()
                if (
                    ("python" in name or "python" in cmd)
                    and "jarvis.py" in cmd
                    and (
                        core_lower in cmd
                        or core.name.lower() in cmd
                        or core_lower == str(DEFAULT_CORE).lower()
                    )
                ):
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def derive_state(core: Path) -> dict[str, Any]:
    running = core_process_running(core)
    events = tail_events(core / "logs" / "events.jsonl")

    if not running:
        return {
            "name": "OFFLINE",
            "message": "Core JARVIS não está em execução",
            "source": "process",
        }

    state = "IDLE"
    message = "Núcleo neural ativo"
    last_relevant_ts = None

    for event in events:
        name = str(event.get("name") or "")
        ts = event.get("timestamp")

        if name in {
            "WAKE_WORD_DETECTED",
            "SPEECH_DETECTED",
            "WAKE_COMMAND_TRANSCRIBED",
        }:
            state = "LISTENING"
            message = "Estou a ouvir, Senhor"
            last_relevant_ts = ts
        elif name in {
            "INPUT_RECEIVED",
            "THINKING_STARTED",
            "MODEL_REQUEST",
            "TOOL_CALLS_REQUESTED",
            "TOOL_EXECUTING",
            "CLOUD_REQUEST",
            "CLOUD_TOOL_CALLS_REQUESTED",
        }:
            state = "THINKING"
            message = "A processar"
            last_relevant_ts = ts
        elif name == "FAST_PATH_HIT":
            state = "THINKING"
            message = "A preparar resposta"
            last_relevant_ts = ts
        elif name == "SPEECH_STARTED":
            state = "SPEAKING"
            message = "A responder"
            last_relevant_ts = ts
        elif name in {
            "SPEECH_FINISHED",
            "SPEECH_INTERRUPTED",
            "VOICE_INTERRUPT_APPLIED",
            "WAKE_COMMAND_TIMEOUT",
            "MODEL_ERROR",
        }:
            state = "IDLE"
            message = "Núcleo neural ativo"
            last_relevant_ts = ts

    if state != "SPEAKING" and last_relevant_ts:
        try:
            dt = datetime.fromisoformat(last_relevant_ts)
            if datetime.now().astimezone() - dt > timedelta(seconds=25):
                state = "IDLE"
                message = "Núcleo neural ativo"
        except Exception:
            pass

    return {
        "name": state,
        "message": message,
        "source": "events.jsonl",
        "last_event": events[-1].get("name") if events else None,
    }


def get_core_version(core: Path) -> str:
    init_file = core / "jarvis_core" / "__init__.py"
    if init_file.exists():
        try:
            text = init_file.read_text(encoding="utf-8")
            import re
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
            if match:
                return match.group(1)
        except Exception:
            pass
    return "0.12.0"


class Cache:
    def __init__(self):
        self.values: dict[str, tuple[float, Any]] = {}
        self.lock = RLock()

    def get(self, key: str, ttl: float, factory):
        now = time.monotonic()
        with self.lock:
            row = self.values.get(key)
            if row and now - row[0] < ttl:
                return row[1]
        value = factory()
        with self.lock:
            self.values[key] = (now, value)
        return value


CACHE = Cache()


def snapshot(core: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "bridge": {
            "version": BRIDGE_VERSION,
            "core_version": get_core_version(core),
            "core_path": str(core),
            "timestamp": datetime.now().astimezone().isoformat(
                timespec="milliseconds"
            ),
            "read_only": True,
            "bind": "127.0.0.1",
        },
        "profile": CACHE.get("profile", 10, lambda: get_profile(core)),
        "telemetry": collect_telemetry(),
        "environment": CACHE.get(
            "environment",
            60,
            lambda: get_environment(core),
        ),
        "security": CACHE.get(
            "security",
            5,
            lambda: get_security(core),
        ),
        "network": CACHE.get(
            "network",
            5,
            lambda: get_network_inventory(core),
        ),
        "agenda": CACHE.get(
            "agenda",
            5,
            lambda: get_agenda(core),
        ),
        "integrations": CACHE.get(
            "integrations",
            15,
            lambda: get_integrations(core),
        ),
        "state": derive_state(core),
    }


class JarvisHandler(SimpleHTTPRequestHandler):
    server_version = "JarvisWallpaperBridge/0.1"

    def log_message(self, format, *args):
        # Quiet by default; avoid console spam.
        pass

    @property
    def core(self) -> Path:
        return self.server.core_path  # type: ignore[attr-defined]

    @property
    def wallpaper_dir(self) -> Path:
        return self.server.wallpaper_dir  # type: ignore[attr-defined]

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def json_response(self, payload: Any, status: int = 200):
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/health":
                return self.json_response({
                    "ok": True,
                    "bridge_version": BRIDGE_VERSION,
                    "core_path": str(self.core),
                    "core_exists": self.core.exists(),
                    "core_running": core_process_running(self.core),
                    "bind": "127.0.0.1",
                    "read_only": True,
                })
            if path == "/api/state":
                return self.json_response(derive_state(self.core))
            if path == "/api/snapshot":
                return self.json_response(snapshot(self.core))
        except Exception as exc:
            return self.json_response({
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }, status=500)

        # Preview server: serve the wallpaper itself too.
        if path == "/":
            path = "/index.html"

        requested = (self.wallpaper_dir / path.lstrip("/")).resolve()
        try:
            requested.relative_to(self.wallpaper_dir.resolve())
        except ValueError:
            self.send_error(403)
            return

        if not requested.exists() or not requested.is_file():
            self.send_error(404)
            return

        ctype, _ = mimetypes.guess_type(str(requested))
        raw = requested.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="JARVIS Live Wallpaper local read-only bridge."
    )
    parser.add_argument(
        "--core",
        default=os.environ.get("JARVIS_CORE_PATH", str(DEFAULT_CORE)),
        help=r"JARVIS Core path (default: G:\JARVIS)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(
            "Por segurança, o bridge só pode escutar em loopback/localhost."
        )

    core = Path(args.core).expanduser()
    wallpaper_dir = Path(__file__).resolve().parents[1] / "wallpaper"

    server = ThreadingHTTPServer((args.host, args.port), JarvisHandler)
    server.core_path = core  # type: ignore[attr-defined]
    server.wallpaper_dir = wallpaper_dir  # type: ignore[attr-defined]

    write_log(
        f"JARVIS Live Wallpaper Bridge {BRIDGE_VERSION} | "
        f"http://{args.host}:{args.port} | Core={core}"
    )
    write_log("READ_ONLY | Loopback only | Ctrl+C para terminar.")

    try:
        server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
