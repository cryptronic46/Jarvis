from __future__ import annotations

from typing import Any

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


class SkillsMetaSkill(Skill):
    skill_id = "skills_system"
    name = "Skills System"
    version = "1.0.0"
    description = "Discover built-in and OWNER-trusted modular JARVIS capabilities."

    def _manager(self):
        return self.context.services.get("skill_manager")

    def get_status(self) -> dict[str, Any]:
        manager = self._manager()
        return manager.status() if manager else {"ok": False, "error": "SKILL_MANAGER_UNAVAILABLE"}

    def discover(self) -> dict[str, Any]:
        manager = self._manager()
        return manager.discover_external() if manager else {"ok": False, "error": "SKILL_MANAGER_UNAVAILABLE"}

    def tools(self) -> list[SkillTool]:
        markers = ("skills", "skill", "módulos", "modulos", "capacidades instaladas", "extensões", "extensoes")
        return [
            SkillTool("get_skills_status", "Read loaded JARVIS skills, versions, startup state and registered tool count.", self.get_status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("discover_external_skills", "List skill packages present in the persistent external skills folder and whether their exact digest is OWNER-trusted. Does not load or trust them.", self.discover, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
        ]


def create_skill(context: SkillContext) -> Skill:
    return SkillsMetaSkill(context)
