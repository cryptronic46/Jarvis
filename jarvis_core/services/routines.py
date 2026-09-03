from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import shutil

from jarvis_core.services.profiles import manager as profile_manager
from jarvis_core.tools.windows_actions import AppRegistry, set_master_volume, set_mute


class RoutineManager:
    ALLOWED_ACTIONS = {"open_app", "volume", "mute"}

    def __init__(
        self,
        path: str | Path = "memory/routines.json",
        default_path: str | Path = "defaults/routines.json",
        apps_path: str | Path = "apps.json",
    ):
        self.path = Path(path)
        self.default_path = Path(default_path)
        self.apps = AppRegistry(apps_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            if self.default_path.exists():
                shutil.copyfile(self.default_path, self.path)
            else:
                self.path.write_text('{"routines":{}}', encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"routines": {}}
        except Exception:
            return {"routines": {}}

    def list(self) -> dict[str, Any]:
        return {
            "ok": True,
            "routines": [
                {
                    "id": key,
                    "label": value.get("label", key),
                    "actions": value.get("actions", []),
                }
                for key, value in (self._load().get("routines") or {}).items()
            ],
        }

    def run(self, name: str) -> dict[str, Any]:
        key = str(name).strip().lower()
        if not profile_manager().routine_allowed(key):
            return {
                "ok": False,
                "error": "PROFILE_ROUTINE_DENIED",
                "profile": profile_manager().active_id(),
                "routine": key,
            }
        routine = (self._load().get("routines") or {}).get(key)
        if not routine:
            return {"ok": False, "error": "UNKNOWN_ROUTINE", "routine": key}

        results = []
        for action in routine.get("actions", []):
            action_type = str(action.get("type") or "")
            if action_type not in self.ALLOWED_ACTIONS:
                results.append({"ok": False, "error": "ROUTINE_ACTION_NOT_ALLOWED", "action": action})
                continue
            if action_type == "open_app":
                result = self.apps.open(str(action.get("app") or ""))
            elif action_type == "volume":
                result = set_master_volume(float(action.get("percent", 25)))
            else:
                result = set_mute(bool(action.get("muted")))
            results.append({"action": action, "result": result})

        ok = all((row.get("result") or {}).get("ok") is not False for row in results if row.get("result") is not None)
        return {
            "ok": ok,
            "routine": key,
            "label": routine.get("label", key),
            "results": results,
            "safe_action_types": sorted(self.ALLOWED_ACTIONS),
        }


_MANAGER: RoutineManager | None = None


def routine_manager() -> RoutineManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = RoutineManager()
    return _MANAGER


def list_routines() -> dict[str, Any]:
    return routine_manager().list()


def run_routine(name: str) -> dict[str, Any]:
    return routine_manager().run(name)
