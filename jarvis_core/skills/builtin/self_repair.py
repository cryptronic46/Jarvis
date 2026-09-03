from __future__ import annotations

from pathlib import Path
from typing import Any
import importlib.util

from jarvis_core.core.config import Settings
from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


class SelfRepairService:
    """Safe, idempotent diagnostics and bounded repair actions."""

    RUNTIME_DIRS = (
        "memory", "knowledge", "logs", ".cache", "voice_profiles", "models", "skills",
    )

    def __init__(self, context: SkillContext) -> None:
        self.context = context

    def diagnose(self) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool, **detail: Any) -> None:
            checks.append({"name": name, "ok": bool(ok), **detail})

        add("settings_file", Path("settings.json").is_file(), path="settings.json")
        add("apps_file", Path("apps.json").is_file(), path="apps.json")
        add("release_manifest", Path("release_manifest.json").is_file(), path="release_manifest.json")
        for directory in self.RUNTIME_DIRS:
            add(f"runtime_dir:{directory}", Path(directory).is_dir(), path=directory)

        if self.context.brain is not None:
            try:
                self.context.brain.client.show(self.context.settings.model)
                add("ollama_model", True, model=self.context.settings.model)
            except Exception as exc:
                add("ollama_model", False, model=self.context.settings.model, error=f"{type(exc).__name__}: {exc}")
        else:
            add("ollama_model", False, error="LOCAL_BRAIN_UNAVAILABLE")

        add("edge_tts_module", importlib.util.find_spec("edge_tts") is not None)
        add("psutil_module", importlib.util.find_spec("psutil") is not None)

        if self.context.desktop is not None:
            try:
                desktop = self.context.desktop.status()
                add("desktop_bridge", bool(desktop.get("bridge_online")), detail=desktop)
                add("wallpaper_engine", bool(desktop.get("wallpaper_engine_running")), detail=desktop)
            except Exception as exc:
                add("desktop_integration", False, error=f"{type(exc).__name__}: {exc}")

        guardian = self.context.services.get("system_guardian")
        if guardian is not None:
            try:
                integrity = guardian._release_integrity()  # bounded internal diagnostic
                add("core_integrity", bool(integrity.get("ok")), detail=integrity)
            except Exception as exc:
                add("core_integrity", False, error=f"{type(exc).__name__}: {exc}")

        failed = [row for row in checks if not row.get("ok")]
        result = {
            "ok": not bool(failed),
            "checks": checks,
            "failed_count": len(failed),
            "repairable_automatically": [
                row["name"] for row in failed
                if row["name"].startswith("runtime_dir:") or row["name"] in {"desktop_bridge", "wallpaper_engine", "settings_file"}
            ],
            "manual_attention": [
                row["name"] for row in failed
                if row["name"] in {"ollama_model", "core_integrity", "edge_tts_module", "release_manifest", "apps_file"}
            ],
        }
        self.context.events.emit("SELF_DIAGNOSTICS_FINISHED", ok=result["ok"], failed=len(failed))
        return result

    def repair_safe(self) -> dict[str, Any]:
        self.context.events.emit("SELF_REPAIR_STARTED")
        actions: list[dict[str, Any]] = []
        for directory in self.RUNTIME_DIRS:
            path = Path(directory)
            if not path.is_dir():
                try:
                    path.mkdir(parents=True, exist_ok=True)
                    actions.append({"action": "create_runtime_dir", "path": directory, "ok": True})
                except Exception as exc:
                    actions.append({"action": "create_runtime_dir", "path": directory, "ok": False, "error": str(exc)})
        try:
            schema = Settings.ensure_file_schema("settings.json")
            actions.append({"action": "ensure_settings_schema", "ok": bool(schema.get("ok")), "detail": schema})
        except Exception as exc:
            actions.append({"action": "ensure_settings_schema", "ok": False, "error": str(exc)})
        if self.context.desktop is not None:
            try:
                state = self.context.desktop.start()
                actions.append({"action": "ensure_desktop_integration", "ok": bool(state.get("bridge_online") or state.get("wallpaper_engine_running")), "detail": state})
            except Exception as exc:
                actions.append({"action": "ensure_desktop_integration", "ok": False, "error": str(exc)})
        after = self.diagnose()
        result = {
            "ok": all(row.get("ok") for row in actions) and after.get("failed_count", 0) == 0,
            "actions": actions,
            "after": after,
            "boundaries": [
                "does not replace release files",
                "does not install packages/models automatically",
                "does not change Windows security settings",
                "does not execute arbitrary shell commands",
            ],
        }
        self.context.events.emit("SELF_REPAIR_FINISHED", ok=result["ok"], actions=len(actions))
        return result

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "safe_repairs": ["runtime directories", "settings schema", "desktop/wallpaper ensure"],
            "manual_only": ["Core integrity mismatch", "missing Python packages", "missing native local model"],
        }


class SelfRepairSkill(Skill):
    skill_id = "self_repair"
    name = "Self Diagnostics & Safe Repair"
    version = "1.0.0"
    description = "Diagnose JARVIS subsystems and apply only bounded idempotent repairs."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = SelfRepairService(context)
        context.services["self_repair"] = self.service

    def tools(self) -> list[SkillTool]:
        markers = ("diagnostica-te", "diagnóstico jarvis", "diagnostico jarvis", "repara-te", "self repair", "auto reparação", "auto reparacao", "jarvis avariado", "jarvis não funciona", "jarvis nao funciona")
        return [
            SkillTool("get_self_repair_status", "Read self-diagnostics and safe-repair boundaries.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("run_self_diagnostics", "Diagnose local JARVIS Core, native model/runtime directories, integrity and desktop integration without changing them.", self.service.diagnose, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("run_safe_self_repair", "Apply bounded idempotent JARVIS repairs: runtime dirs, settings schema, and desktop/wallpaper ensure. It cannot replace Core files or install software.", self.service.repair_safe, {"type":"object","properties":{}}, RiskLevel.LOW, markers),
        ]

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return SelfRepairSkill(context)
