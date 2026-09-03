from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import os
import platform
import subprocess
import sys
import time
import urllib.request

import psutil

from jarvis_core.core.events import EventBus


WALLPAPER_PROCESS_NAMES = {
    "wallpaper32.exe",
    "wallpaper64.exe",
    "wallpaper_engine.exe",
}


@dataclass(slots=True)
class DesktopIntegrationState:
    enabled: bool
    platform: str
    wallpaper_root: str
    bridge_port: int
    bridge_online: bool = False
    bridge_started: bool = False
    bridge_pid: int | None = None
    wallpaper_engine_running: bool = False
    wallpaper_engine_started: bool = False
    wallpaper_engine_pid: int | None = None
    wallpaper_engine_path: str | None = None
    last_error: str | None = None


class DesktopIntegrationService:
    """
    Safe one-shot desktop bootstrap for the local JARVIS HUD.

    It never accepts paths or commands from the LLM. Paths come only from the
    OWNER settings/environment. The bridge is loopback-only and the Wallpaper
    Engine executable is launched directly without invoking a shell.
    """

    def __init__(
        self,
        events: EventBus,
        *,
        enabled: bool = True,
        core_root: str | Path = ".",
        wallpaper_root: str | Path = "",
        bridge_port: int = 8765,
        bridge_auto_start: bool = True,
        wallpaper_engine_auto_start: bool = True,
        wallpaper_engine_path: str = "",
    ) -> None:
        self.events = events
        self.enabled = bool(enabled)
        self.core_root = Path(core_root).resolve()
        configured_wallpaper_root = str(wallpaper_root or "").strip()
        self.wallpaper_root = (
            Path(configured_wallpaper_root).expanduser()
            if configured_wallpaper_root
            else self.core_root.parent / "JARVIS-Wallpaper"
        )
        self.bridge_port = int(bridge_port)
        self.bridge_auto_start = bool(bridge_auto_start)
        self.wallpaper_engine_auto_start = bool(wallpaper_engine_auto_start)
        self.wallpaper_engine_path = str(wallpaper_engine_path or "").strip()
        self._state = DesktopIntegrationState(
            enabled=self.enabled,
            platform=platform.system(),
            wallpaper_root=str(self.wallpaper_root),
            bridge_port=self.bridge_port,
        )

    def status(self) -> dict[str, Any]:
        self._state.bridge_online = self._bridge_online()
        proc = self._wallpaper_process()
        self._state.wallpaper_engine_running = proc is not None
        if proc is not None:
            self._state.wallpaper_engine_pid = proc.pid
        return asdict(self._state)

    def start(self) -> dict[str, Any]:
        if not self.enabled:
            self.events.emit("DESKTOP_INTEGRATION_DISABLED")
            return self.status()
        if not 1024 <= self.bridge_port <= 65535:
            self._state.last_error = "INVALID_BRIDGE_PORT"
            self.events.emit(
                "DESKTOP_INTEGRATION_ERROR",
                error=self._state.last_error,
                bridge_port=self.bridge_port,
            )
            return self.status()

        # The bridge is useful even if Wallpaper Engine itself is not installed:
        # the OWNER can still preview the HUD in a browser.
        if self.bridge_auto_start:
            self._ensure_bridge()

        if self.wallpaper_engine_auto_start and platform.system().lower() == "windows":
            self._ensure_wallpaper_engine()

        current = self.status()
        self.events.emit(
            "DESKTOP_INTEGRATION_READY",
            bridge_online=current["bridge_online"],
            wallpaper_engine_running=current["wallpaper_engine_running"],
            wallpaper_root=current["wallpaper_root"],
            bridge_port=current["bridge_port"],
        )
        return current

    def _bridge_health_url(self) -> str:
        return f"http://127.0.0.1:{self.bridge_port}/api/health"

    def _bridge_online(self) -> bool:
        try:
            request = urllib.request.Request(
                self._bridge_health_url(),
                headers={"User-Agent": "JARVIS-Core-DesktopIntegration/0.22"},
            )
            with urllib.request.urlopen(request, timeout=0.45) as response:
                return 200 <= int(response.status) < 300
        except Exception:
            return False

    def _bridge_python(self) -> Path:
        candidates = []
        if platform.system().lower() == "windows":
            candidates.extend(
                [
                    self.core_root / ".venv" / "Scripts" / "pythonw.exe",
                    self.core_root / ".venv" / "Scripts" / "python.exe",
                ]
            )
        else:
            candidates.append(self.core_root / ".venv" / "bin" / "python")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return Path(sys.executable)

    def _ensure_bridge(self) -> None:
        if self._bridge_online():
            self._state.bridge_online = True
            return

        bridge = self.wallpaper_root / "bridge" / "jarvis_bridge.py"
        if not bridge.is_file():
            self._state.last_error = "WALLPAPER_BRIDGE_NOT_INSTALLED"
            self.events.emit(
                "DESKTOP_BRIDGE_UNAVAILABLE",
                bridge_path=str(bridge),
            )
            return

        command = [
            str(self._bridge_python()),
            str(bridge),
            "--core",
            str(self.core_root),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.bridge_port),
        ]
        flags = 0
        startupinfo = None
        if platform.system().lower() == "windows":
            flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                getattr(subprocess, "DETACHED_PROCESS", 0)
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

        try:
            proc = subprocess.Popen(
                command,
                cwd=str(self.wallpaper_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=flags,
                startupinfo=startupinfo,
            )
            self._state.bridge_started = True
            self._state.bridge_pid = proc.pid
            self.events.emit(
                "DESKTOP_BRIDGE_STARTED",
                pid=proc.pid,
                port=self.bridge_port,
            )
            for _ in range(6):
                if self._bridge_online():
                    self._state.bridge_online = True
                    break
                time.sleep(0.20)
        except Exception as exc:
            self._state.last_error = f"BRIDGE_START_FAILED:{type(exc).__name__}"
            self.events.emit(
                "DESKTOP_INTEGRATION_ERROR",
                error=self._state.last_error,
            )

    def _wallpaper_process(self):
        try:
            for proc in psutil.process_iter(attrs=["name"]):
                try:
                    name = str(proc.info.get("name") or "").lower()
                    if name in WALLPAPER_PROCESS_NAMES:
                        return proc
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return None

    def _steam_roots(self) -> list[Path]:
        roots: list[Path] = []
        for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env_name)
            if base:
                roots.append(Path(base) / "Steam")
        if platform.system().lower() == "windows":
            try:
                import winreg

                for hive, key_name, value_name in (
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
                ):
                    try:
                        with winreg.OpenKey(hive, key_name) as key:
                            value = winreg.QueryValueEx(key, value_name)[0]
                            if value:
                                roots.append(Path(str(value)))
                    except OSError:
                        continue
            except Exception:
                pass
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root).lower()
            if key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def _detect_wallpaper_engine(self) -> Path | None:
        if self.wallpaper_engine_path:
            configured = Path(self.wallpaper_engine_path).expanduser()
            if configured.is_file():
                return configured
        # Prefer an installation on the same dedicated drive as the Core.
        # This supports G:\JARVIS + G:\WallpaperEngine as well as Steam
        # libraries on G: without hard-coding a machine-specific drive letter.
        drive_root = Path(self.core_root.anchor) if self.core_root.anchor else None
        same_drive_bases: list[Path] = []
        if drive_root is not None:
            same_drive_bases.extend([
                drive_root / "WallpaperEngine",
                drive_root / "Wallpaper Engine",
                drive_root / "SteamLibrary" / "steamapps" / "common" / "wallpaper_engine",
                drive_root / "Steam" / "steamapps" / "common" / "wallpaper_engine",
                drive_root / "steamapps" / "common" / "wallpaper_engine",
            ])
        for base in same_drive_bases:
            for exe in ("wallpaper64.exe", "wallpaper32.exe", "wallpaper_engine.exe"):
                candidate = base / exe
                if candidate.is_file():
                    return candidate

        for steam_root in self._steam_roots():
            base = steam_root / "steamapps" / "common" / "wallpaper_engine"
            for exe in ("wallpaper64.exe", "wallpaper32.exe", "wallpaper_engine.exe"):
                candidate = base / exe
                if candidate.is_file():
                    return candidate
        return None

    def _ensure_wallpaper_engine(self) -> None:
        existing = self._wallpaper_process()
        if existing is not None:
            self._state.wallpaper_engine_running = True
            self._state.wallpaper_engine_pid = existing.pid
            return

        executable = self._detect_wallpaper_engine()
        if executable is None:
            self._state.last_error = "WALLPAPER_ENGINE_NOT_FOUND"
            self.events.emit("WALLPAPER_ENGINE_UNAVAILABLE")
            return

        self._state.wallpaper_engine_path = str(executable)
        flags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        try:
            proc = subprocess.Popen(
                [str(executable)],
                cwd=str(executable.parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=flags,
            )
            self._state.wallpaper_engine_started = True
            self._state.wallpaper_engine_running = True
            self._state.wallpaper_engine_pid = proc.pid
            self.events.emit(
                "WALLPAPER_ENGINE_STARTED",
                pid=proc.pid,
                path=str(executable),
            )
        except Exception as exc:
            self._state.last_error = f"WALLPAPER_ENGINE_START_FAILED:{type(exc).__name__}"
            self.events.emit(
                "DESKTOP_INTEGRATION_ERROR",
                error=self._state.last_error,
            )
