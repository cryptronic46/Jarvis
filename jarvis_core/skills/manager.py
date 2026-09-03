from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from importlib import util as importlib_util
from pathlib import Path
from types import ModuleType
from typing import Any
import json
import re

from jarvis_core.skills.base import Skill, SkillContext


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")


class SkillManager:
    """Load built-ins and OWNER-trusted external skill packages.

    External skills live under the runtime ``skills`` folder, which is not
    mirrored by Core updates. They are inert until the OWNER trusts the exact
    directory digest through the CLI. The LLM has no trust/install tool.
    """

    BUILTIN_MODULES = (
        "jarvis_core.skills.builtin.desktop_agent",
        "jarvis_core.skills.builtin.purple_team",
        "jarvis_core.skills.builtin.system_guardian",
        "jarvis_core.skills.builtin.task_planner",
        "jarvis_core.skills.builtin.memory_graph",
        "jarvis_core.skills.builtin.wallpaper_live",
        "jarvis_core.skills.builtin.vision",
        "jarvis_core.skills.builtin.self_repair",
        "jarvis_core.skills.builtin.meta",
    )

    def __init__(
        self,
        context: SkillContext,
        *,
        external_root: str | Path = "skills",
        trust_path: str | Path = "memory/skills_trust.json",
        external_enabled: bool = True,
    ) -> None:
        self.context = context
        self.external_root = Path(external_root)
        self.trust_path = Path(trust_path)
        self.external_enabled = bool(external_enabled)
        self.skills: dict[str, Skill] = {}
        self.load_errors: list[dict[str, str]] = []
        self._tool_names: set[str] = set()
        self.context.services["skill_manager"] = self

    def _event(self, name: str, **data: Any) -> None:
        try:
            self.context.events.emit(name, **data)
        except Exception:
            pass

    def _load_trust(self) -> dict[str, Any]:
        try:
            data = json.loads(self.trust_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"skills": {}}
        except Exception:
            return {"skills": {}}

    def _save_trust(self, data: dict[str, Any]) -> None:
        self.trust_path.parent.mkdir(parents=True, exist_ok=True)
        self.trust_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def directory_digest(path: str | Path) -> str:
        root = Path(path).resolve()
        digest = sha256()
        for file in sorted(p for p in root.rglob("*") if p.is_file()):
            rel = file.relative_to(root).as_posix()
            if "__pycache__" in file.parts or file.suffix.lower() == ".pyc":
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _manifest(path: Path) -> dict[str, Any]:
        manifest_path = path / "skill.json"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("skill.json must contain an object")
        skill_id = str(data.get("id") or "").strip().lower()
        if not _ID_RE.fullmatch(skill_id):
            raise ValueError("invalid skill id")
        entrypoint = str(data.get("entrypoint") or "skill.py").strip()
        if not entrypoint.endswith(".py") or "/" in entrypoint or "\\" in entrypoint:
            raise ValueError("entrypoint must be one local .py filename")
        if not (path / entrypoint).is_file():
            raise ValueError("skill entrypoint missing")
        data["id"] = skill_id
        data["entrypoint"] = entrypoint
        return data

    def discover_external(self) -> dict[str, Any]:
        rows = []
        if not self.external_root.is_dir():
            return {"ok": True, "root": str(self.external_root), "candidates": []}
        trust = self._load_trust().get("skills") or {}
        for path in sorted(p for p in self.external_root.iterdir() if p.is_dir()):
            try:
                manifest = self._manifest(path)
                digest = self.directory_digest(path)
                grant = trust.get(manifest["id"]) if isinstance(trust, dict) else None
                rows.append({
                    "id": manifest["id"],
                    "name": manifest.get("name") or manifest["id"],
                    "version": manifest.get("version"),
                    "path": str(path.resolve()),
                    "sha256": digest,
                    "trusted": bool(grant and str(grant.get("sha256")) == digest),
                    "loaded": manifest["id"] in self.skills,
                })
            except Exception as exc:
                rows.append({"path": str(path.resolve()), "error": f"{type(exc).__name__}: {exc}"})
        return {"ok": True, "root": str(self.external_root), "candidates": rows}

    def trust_external(self, path: str | Path) -> dict[str, Any]:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            return {"ok": False, "error": "SKILL_DIRECTORY_NOT_FOUND", "path": str(root)}
        try:
            manifest = self._manifest(root)
            digest = self.directory_digest(root)
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
        state = self._load_trust()
        trusted = state.setdefault("skills", {})
        trusted[manifest["id"]] = {
            "path": str(root),
            "sha256": digest,
            "version": str(manifest.get("version") or "unknown"),
        }
        self._save_trust(state)
        return {
            "ok": True,
            "id": manifest["id"],
            "path": str(root),
            "sha256": digest,
            "instruction": "Reinicia o JARVIS para carregar a skill confiada.",
        }

    def untrust_external(self, skill_id: str) -> dict[str, Any]:
        key = str(skill_id or "").strip().lower()
        state = self._load_trust()
        trusted = state.setdefault("skills", {})
        existed = key in trusted
        trusted.pop(key, None)
        self._save_trust(state)
        return {"ok": True, "id": key, "removed": existed, "restart_recommended": key in self.skills}

    def _register_skill(self, skill: Skill, source: str) -> None:
        if skill.skill_id in self.skills:
            raise ValueError(f"duplicate skill id: {skill.skill_id}")
        for tool in skill.tools():
            if tool.name in self._tool_names or tool.name in self.context.registry.names:
                raise ValueError(f"duplicate tool: {tool.name}")
            self.context.registry.register_skill_tool(
                name=tool.name,
                description=tool.description,
                func=tool.func,
                schema=tool.schema(),
                risk=tool.risk,
                keywords=tool.keywords,
                skill_id=skill.skill_id,
            )
            self._tool_names.add(tool.name)
        self.skills[skill.skill_id] = skill
        self._event(
            "SKILL_LOADED",
            skill=skill.skill_id,
            version=skill.version,
            source=source,
            tools=len(skill.tools()),
        )

    def load_builtins(self) -> None:
        from importlib import import_module
        for module_name in self.BUILTIN_MODULES:
            try:
                module = import_module(module_name)
                factory = getattr(module, "create_skill")
                skill = factory(self.context)
                if not isinstance(skill, Skill):
                    raise TypeError("create_skill() must return Skill")
                self._register_skill(skill, "builtin")
            except Exception as exc:
                self.load_errors.append({"source": module_name, "error": f"{type(exc).__name__}: {exc}"})
                self._event("SKILL_LOAD_FAILED", source=module_name, error=f"{type(exc).__name__}: {exc}")

    def _load_external_module(self, root: Path, manifest: dict[str, Any]) -> ModuleType:
        entry = root / manifest["entrypoint"]
        name = f"jarvis_external_skill_{manifest['id'].replace('-', '_').replace('.', '_')}"
        spec = importlib_util.spec_from_file_location(name, entry)
        if spec is None or spec.loader is None:
            raise ImportError("unable to create module spec")
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def load_external(self) -> None:
        if not self.external_enabled:
            return
        state = self._load_trust()
        trusted = state.get("skills") or {}
        if not isinstance(trusted, dict):
            return
        for skill_id, grant in trusted.items():
            try:
                root = Path(str(grant.get("path") or "")).expanduser().resolve()
                manifest = self._manifest(root)
                if manifest["id"] != skill_id:
                    raise ValueError("trusted id no longer matches manifest")
                digest = self.directory_digest(root)
                if digest != str(grant.get("sha256") or ""):
                    raise PermissionError("skill files changed after OWNER trust; re-trust required")
                module = self._load_external_module(root, manifest)
                factory = getattr(module, "create_skill")
                skill = factory(self.context)
                if not isinstance(skill, Skill):
                    raise TypeError("external create_skill() must return Skill")
                self._register_skill(skill, "owner_trusted_external")
            except Exception as exc:
                self.load_errors.append({"source": str(skill_id), "error": f"{type(exc).__name__}: {exc}"})
                self._event("SKILL_LOAD_FAILED", source=str(skill_id), error=f"{type(exc).__name__}: {exc}")

    def load_all(self) -> dict[str, Any]:
        self.load_builtins()
        self.load_external()
        return self.status()

    def start_all(self) -> None:
        for skill in self.skills.values():
            try:
                skill.start()
            except Exception as exc:
                skill.last_error = f"{type(exc).__name__}: {exc}"
                self._event("SKILL_START_FAILED", skill=skill.skill_id, error=skill.last_error)

    def stop_all(self) -> None:
        for skill in reversed(list(self.skills.values())):
            try:
                skill.stop()
            except Exception as exc:
                skill.last_error = f"{type(exc).__name__}: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "ok": not bool(self.load_errors),
            "loaded": len(self.skills),
            "tool_count": len(self._tool_names),
            "external_enabled": self.external_enabled,
            "external_root": str(self.external_root),
            "trust_path": str(self.trust_path),
            "skills": [skill.status() for skill in self.skills.values()],
            "load_errors": list(self.load_errors),
        }

    def get(self, skill_id: str) -> Skill | None:
        return self.skills.get(str(skill_id or "").strip().lower())
