from __future__ import annotations

from pathlib import Path
import json
import os
import platform
import re
import shutil
import subprocess
import time
from typing import Any

import psutil

_PERCENT_ENV = re.compile(r"%([^%]+)%")


def _expand_windows_env(value: str) -> str:
    def replace(match):
        return os.environ.get(match.group(1), match.group(0))
    return os.path.expandvars(os.path.expanduser(_PERCENT_ENV.sub(replace, value)))


class AppRegistry:
    def __init__(self, path: str | Path = "apps.json"):
        self.path = Path(path)
        self.apps = self._load()

    def _load(self):
        if not self.path.exists():
            apps = {}
        else:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            apps = {str(k).lower(): dict(v) for k, v in data.get("apps", data).items()}

        # Core-safe built-in discovery entries. OWNER custom apps.json remains
        # authoritative: setdefault never overwrites an existing definition.
        # Notepad++ is deliberately distinct from Windows Notepad so punctuation
        # normalization can never turn a request for one into the other.
        apps.setdefault("notepad_plus_plus", {
            "name": "Notepad++",
            "aliases": ["notepad++", "notepad plus plus"],
            "launch": {"type": "path", "target": r"%ProgramFiles%\Notepad++\notepad++.exe"},
            "path_candidates": [
                r"%ProgramFiles%\Notepad++\notepad++.exe",
                r"%ProgramFiles(x86)%\Notepad++\notepad++.exe",
                r"%LOCALAPPDATA%\Programs\Notepad++\notepad++.exe",
            ],
            "executable_candidates": ["notepad++.exe"],
            "process_names": ["notepad++.exe"],
        })
        return apps

    def list_apps(self):
        return [{
            "id": key,
            "name": item.get("name", key),
            "aliases": item.get("aliases", []),
            "process_names": item.get("process_names", []),
            "executable_candidates": item.get("executable_candidates", []),
        } for key, item in sorted(self.apps.items())]

    def resolve(self, query: str):
        q = query.strip().lower()
        if q in self.apps:
            return q, self.apps[q]
        for key, item in self.apps.items():
            aliases = [str(x).lower() for x in item.get("aliases", [])]
            if q == str(item.get("name", "")).lower() or q in aliases:
                return key, item
        return None

    def _expand(self, value: str) -> str:
        return _expand_windows_env(value)

    def _running_executable(self, names: list[str]):
        wanted = {x.lower() for x in names}
        for proc in psutil.process_iter(attrs=["name"]):
            try:
                if (proc.info.get("name") or "").lower() not in wanted:
                    continue
                exe = proc.exe()
                if exe and Path(exe).is_file():
                    return exe
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return None

    def _registry_app_path(self, exe_name: str):
        if platform.system() != "Windows":
            return None
        try:
            import winreg
        except ImportError:
            return None

        subkeys = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
            rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
        ]
        hives = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
        modes = [winreg.KEY_READ]
        if hasattr(winreg, "KEY_WOW64_64KEY"):
            modes += [
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                winreg.KEY_READ | winreg.KEY_WOW64_32KEY,
            ]

        for hive in hives:
            for subkey in subkeys:
                for mode in modes:
                    try:
                        with winreg.OpenKey(hive, subkey, 0, mode) as key:
                            value, _ = winreg.QueryValueEx(key, None)
                            path = str(value).strip().strip('"')
                            if Path(path).is_file():
                                return path
                    except OSError:
                        pass
        return None

    def _discover_executable(self, item):
        attempts = []
        exe_names = list(item.get("executable_candidates", [])) or list(item.get("process_names", []))

        running = self._running_executable(exe_names)
        attempts.append({"method": "running_process", "candidate": running, "found": bool(running)})
        if running:
            return running, "running_process", attempts

        candidates = list(item.get("path_candidates", []))
        launch = item.get("launch") or {}
        if launch.get("type") == "path" and launch.get("target"):
            candidates.append(str(launch["target"]))

        seen = set()
        for raw in candidates:
            expanded = self._expand(str(raw))
            if expanded in seen:
                continue
            seen.add(expanded)
            exists = Path(expanded).is_file()
            attempts.append({"method": "path_candidate", "candidate": expanded, "found": exists})
            if exists:
                return expanded, "path_candidate", attempts

        for exe_name in exe_names:
            found = self._registry_app_path(exe_name)
            attempts.append({"method": "registry_app_paths", "candidate": exe_name, "resolved": found, "found": bool(found)})
            if found:
                return found, "registry_app_paths", attempts

        for exe_name in exe_names:
            found = shutil.which(exe_name)
            attempts.append({"method": "PATH", "candidate": exe_name, "resolved": found, "found": bool(found)})
            if found:
                return found, "PATH", attempts

        return None, None, attempts

    def running(self, app_name: str):
        resolved = self.resolve(app_name)
        if not resolved:
            return []
        _, item = resolved
        wanted = {x.lower() for x in item.get("process_names", [])}
        out = []
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in wanted:
                    row = {"pid": proc.info["pid"], "name": proc.info["name"]}
                    try:
                        row["exe"] = proc.exe()
                    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                        pass
                    out.append(row)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return out

    def diagnose(self, app_name: str):
        resolved = self.resolve(app_name)
        if not resolved:
            return {"ok": False, "error": "APP_NOT_ALLOWED", "message": f"'{app_name}' não está no App Registry."}

        app_id, item = resolved
        launch = item.get("launch") or {}
        base = {
            "ok": True,
            "app": app_id,
            "name": item.get("name", app_id),
            "configured_launch": launch,
            "running_processes": self.running(app_name),
        }

        if launch.get("type") == "uri":
            base.update({"launchable": True, "selected_target": launch.get("target"), "selected_method": "uri", "attempts": []})
            return base

        target, method, attempts = self._discover_executable(item)
        base.update({
            "launchable": bool(target) or launch.get("type") == "command",
            "selected_target": target,
            "selected_method": method,
            "fallback_command_available": launch.get("type") == "command",
            "attempts": attempts,
        })
        return base

    def open(self, app_name: str):
        resolved = self.resolve(app_name)
        if not resolved:
            return {"ok": False, "error": "APP_NOT_ALLOWED", "message": f"'{app_name}' não está no App Registry."}

        app_id, item = resolved
        launch = item.get("launch") or {}
        kind = launch.get("type", "path")

        existing = self.running(app_name)
        if existing:
            return {"ok": True, "app": app_id, "name": item.get("name", app_id), "already_running": True, "effect_verified": True, "running_processes": existing}

        try:
            if kind == "uri":
                target = str(launch.get("target", ""))
                os.startfile(target)
                time.sleep(0.15)
                running = self.running(app_name)
                return {"ok": True, "app": app_id, "name": item.get("name", app_id), "launch_method": "uri", "target": target, "effect_verified": bool(running), "running_processes": running}

            target, method, attempts = self._discover_executable(item)
            if target:
                os.startfile(target)
                time.sleep(0.15)
                running = self.running(app_name)
                return {"ok": True, "app": app_id, "name": item.get("name", app_id), "launch_method": method, "target": target, "effect_verified": bool(running), "running_processes": running}

            if kind == "command":
                command = str(launch.get("command", ""))
                args = [self._expand(str(x)) for x in launch.get("args", [])]
                subprocess.Popen([command, *args], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                time.sleep(0.15)
                running = self.running(app_name)
                return {"ok": True, "app": app_id, "name": item.get("name", app_id), "launch_method": "fixed_command", "effect_verified": bool(running), "running_processes": running}

            return {
                "ok": False,
                "error": "APP_EXECUTABLE_NOT_FOUND",
                "message": f"Não encontrei o executável de {item.get('name', app_id)} nos processos, caminhos conhecidos, App Paths do Windows ou PATH.",
                "app": app_id,
                "attempts": attempts,
            }
        except OSError as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc), "app": app_id}

    def open_document(self, app_name: str, path: str):
        resolved = self.resolve(app_name)
        if not resolved:
            return {"ok": False, "error": "APP_NOT_ALLOWED", "message": f"'{app_name}' não está no App Registry."}
        app_id, item = resolved
        document = Path(path).resolve()
        if not document.is_file():
            return {"ok": False, "error": "FILE_NOT_FOUND", "path": str(document)}
        if document.suffix.casefold() != ".pdf":
            return {"ok": False, "error": "DOCUMENT_TYPE_NOT_ALLOWED", "message": "A abertura visual está limitada a ficheiros PDF."}

        target, method, attempts = self._discover_executable(item)
        if not target:
            return {
                "ok": False,
                "error": "APP_EXECUTABLE_NOT_FOUND",
                "message": f"Não encontrei o executável de {item.get('name', app_id)}.",
                "attempts": attempts,
            }
        try:
            subprocess.Popen(
                [target, str(document)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            time.sleep(0.15)
            return {
                "ok": True,
                "app": app_id,
                "name": item.get("name", app_id),
                "path": str(document),
                "launch_method": method,
                "launch_requested": True,
                "effect_verified": bool(self.running(app_name)),
            }
        except OSError as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc), "app": app_id}

    def close(self, app_name: str):
        resolved = self.resolve(app_name)
        if not resolved:
            return {"ok": False, "error": "APP_NOT_ALLOWED", "message": f"'{app_name}' não está no App Registry."}

        app_id, item = resolved
        wanted = {x.lower() for x in item.get("process_names", [])}
        closed, failed = [], []
        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                if (proc.info.get("name") or "").lower() not in wanted:
                    continue
                proc.terminate()
                closed.append({"pid": proc.pid, "name": proc.info.get("name")})
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as exc:
                failed.append({"pid": getattr(proc, "pid", None), "error": str(exc)})

        if not closed and not failed:
            return {"ok": False, "error": "APP_NOT_RUNNING", "app": app_id, "message": f"{item.get('name', app_id)} não está em execução."}
        return {"ok": bool(closed) and not failed, "app": app_id, "terminated": closed, "failed": failed}


def _get_audio_endpoint():
    from pycaw.pycaw import AudioUtilities
    device = AudioUtilities.GetSpeakers()
    return device, device.EndpointVolume


def _safe_device_name(device) -> str:
    try:
        return str(device.FriendlyName)
    except Exception:
        return "Default Windows audio output"


def get_master_volume():
    if platform.system() != "Windows":
        return {"ok": False, "error": "WINDOWS_ONLY"}
    try:
        device, endpoint = _get_audio_endpoint()
        scalar = float(endpoint.GetMasterVolumeLevelScalar())
        return {"ok": True, "device": _safe_device_name(device), "volume_percent": round(scalar * 100, 1), "muted": bool(endpoint.GetMute()), "backend": "IAudioEndpointVolume"}
    except ModuleNotFoundError as exc:
        return {"ok": False, "error": "AUDIO_DEPENDENCY_MISSING", "message": str(exc), "fix": "Run .\\setup.ps1 -SkipModel to reinstall pycaw/comtypes."}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc), "backend": "IAudioEndpointVolume"}


def set_master_volume(percent: int | float):
    if platform.system() != "Windows":
        return {"ok": False, "error": "WINDOWS_ONLY"}
    value = max(0.0, min(float(percent), 100.0))
    try:
        device, endpoint = _get_audio_endpoint()
        endpoint.SetMasterVolumeLevelScalar(value / 100, None)
        actual = float(endpoint.GetMasterVolumeLevelScalar()) * 100
        return {"ok": True, "device": _safe_device_name(device), "requested_percent": round(value, 1), "volume_percent": round(actual, 1), "muted": bool(endpoint.GetMute()), "backend": "IAudioEndpointVolume"}
    except ModuleNotFoundError as exc:
        return {"ok": False, "error": "AUDIO_DEPENDENCY_MISSING", "message": str(exc), "fix": "Run .\\setup.ps1 -SkipModel to reinstall pycaw/comtypes."}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc), "backend": "IAudioEndpointVolume"}


def set_mute(muted: bool):
    if platform.system() != "Windows":
        return {"ok": False, "error": "WINDOWS_ONLY"}
    try:
        device, endpoint = _get_audio_endpoint()
        endpoint.SetMute(1 if muted else 0, None)
        return {"ok": True, "device": _safe_device_name(device), "muted": bool(endpoint.GetMute()), "backend": "IAudioEndpointVolume"}
    except ModuleNotFoundError as exc:
        return {"ok": False, "error": "AUDIO_DEPENDENCY_MISSING", "message": str(exc), "fix": "Run .\\setup.ps1 -SkipModel to reinstall pycaw/comtypes."}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc), "backend": "IAudioEndpointVolume"}
