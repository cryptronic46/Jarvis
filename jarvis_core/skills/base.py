from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis_core.security.policy import RiskLevel


@dataclass(slots=True)
class SkillTool:
    name: str
    description: str
    func: Callable[..., Any]
    parameters: dict[str, Any]
    risk: RiskLevel = RiskLevel.READ_ONLY
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(slots=True)
class SkillContext:
    settings: Any
    events: Any
    registry: Any
    brain: Any = None
    desktop: Any = None
    apps: Any = None
    memory: Any = None
    cyber_range: Any = None
    kali_bridge: Any = None
    services: dict[str, Any] = field(default_factory=dict)


class Skill:
    """Base contract for built-in and OWNER-trusted external skills."""

    skill_id = "skill"
    name = "Skill"
    version = "1.0.0"
    description = ""

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.started = False
        self.last_error: str | None = None

    def tools(self) -> list[SkillTool]:
        return []

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def status(self) -> dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "started": self.started,
            "last_error": self.last_error,
        }
