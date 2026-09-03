from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json
import uuid

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


PLAN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "maxItems": 20,
            "items": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                    "purpose": {"type": "string"},
                },
                "required": ["tool", "arguments", "purpose"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["steps"],
    "additionalProperties": False,
}


class AutonomousTaskPlanner:
    """Bounded local planner that can execute only registered JARVIS tools.

    It never bypasses SecurityPolicy. CONFIRM tools pause execution and the
    existing /confirm TOKEN path remains the only way to approve them.
    """

    _BLOCKED = {
        "create_task_plan", "execute_task_plan", "run_autonomous_task",
        "get_task_plan", "list_task_plans", "adapt_task_plan",
    }

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.path = Path(getattr(context.settings, "task_planner_state_path", "memory/task_plans.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_steps = max(2, min(int(getattr(context.settings, "task_planner_max_steps", 10)), 20))
        self.max_adaptations = max(0, min(int(getattr(context.settings, "task_planner_max_adaptations", 1)), 3))
        self._lock = RLock()
        if not self.path.exists():
            self._save({"plans": {}})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"plans": {}}
        except Exception:
            return {"plans": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _candidate_tools(self, goal: str) -> list[dict[str, Any]]:
        # First use the same selective routing as the conversational brain.
        schemas = self.context.registry.schemas_for_query(goal, max_tools=28)
        names: list[str] = []
        for schema in schemas:
            name = str((schema.get("function") or {}).get("name") or "")
            if name and name not in names:
                names.append(name)

        described = {row["name"]: row for row in self.context.registry.describe()}
        out: list[dict[str, Any]] = []
        for name in names:
            if name in self._BLOCKED or name not in described:
                continue
            row = described[name]
            if row.get("risk") == "CRITICAL":
                continue
            schema = next((x for x in schemas if str((x.get("function") or {}).get("name") or "") == name), {})
            out.append({
                "name": name,
                "risk": row.get("risk"),
                "description": row.get("description"),
                "parameters": dict((schema.get("function") or {}).get("parameters") or {}),
            })

        # A vague follow-up such as "resolve isto" may not carry enough lexical
        # detail to route domain tools. In that case expose only READ_ONLY tools
        # as a conservative observation fallback. The planner cannot silently
        # widen a vague request into mutations.
        domain = [row for row in out if row["name"] not in self._BLOCKED]
        if not domain:
            for row in described.values():
                if row.get("name") in self._BLOCKED or row.get("risk") != "READ_ONLY":
                    continue
                out.append({
                    "name": row.get("name"),
                    "risk": row.get("risk"),
                    "description": row.get("description"),
                })
                if len(out) >= 28:
                    break
        # De-duplicate while keeping deterministic ordering.
        dedup: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in out:
            name = str(row.get("name") or "")
            if name and name not in seen:
                seen.add(name); dedup.append(row)
        return dedup[:28]

    def _model_plan(
        self,
        goal: str,
        tools: list[dict[str, Any]],
        *,
        execution_context: dict[str, Any] | None = None,
        max_steps: int | None = None,
    ) -> list[dict[str, Any]]:
        if self.context.brain is None:
            return []
        system = (
            "És o planeador local de tarefas do JARVIS. Não tens ferramentas nesta chamada. "
            "Transforma o objetivo do OWNER num plano curto usando SOMENTE ferramentas fornecidas no catálogo. "
            "Não inventes nomes de ferramentas. Prefere observar e verificar antes de alterar. Não adiciones ações "
            "que o OWNER não pediu. Ações CONFIRM podem aparecer, mas serão suspensas pelo SecurityPolicy até "
            "confirmação humana. Se receberes contexto de uma falha anterior, adapta o plano usando a evidência real; "
            "não repitas cegamente a mesma etapa e não alargues o âmbito. Se o catálogo não permitir cumprir tudo, "
            "cria apenas passos úteis possíveis. Responde SOMENTE JSON válido: "
            "{\"steps\":[{\"tool\":\"nome\",\"arguments\":{},\"purpose\":\"motivo\"}]} ."
        )
        payload = {
            "goal": goal[:4000],
            "max_steps": max(1, min(int(max_steps or self.max_steps), self.max_steps)),
            "tools": tools,
        }
        if execution_context:
            payload["execution_context"] = execution_context
        try:
            response = self.context.brain.client.chat(
                model=self.context.settings.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                think=False,
                format=PLAN_RESPONSE_SCHEMA,
                keep_alive=self.context.settings.ollama_keep_alive,
                options={"num_ctx": 4096, "num_predict": 700, "temperature": 0.1},
            )
            raw = (getattr(response.message, "content", "") or "").strip()
        except Exception as exc:
            self.context.events.emit("TASK_PLANNER_MODEL_ERROR", error=f"{type(exc).__name__}: {exc}")
            return []
        try:
            data = json.loads(raw)
        except Exception:
            self.context.events.emit("TASK_PLANNER_INVALID_STRUCTURED_JSON", chars=len(raw))
            return []
        rows = data.get("steps") if isinstance(data, dict) else []
        return rows if isinstance(rows, list) else []

    def _validated_steps(
        self,
        requested: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        start_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        allowed = {row["name"]: row for row in tools}
        steps: list[dict[str, Any]] = []
        for row in requested[:limit]:
            if not isinstance(row, dict):
                continue
            tool = str(row.get("tool") or "").strip()
            if tool not in allowed:
                continue
            args = row.get("arguments") if isinstance(row.get("arguments"), dict) else {}
            validate_arguments = getattr(self.context.registry, "validate_arguments", None)
            if callable(validate_arguments):
                valid, _detail = validate_arguments(tool, args)
                if not valid:
                    continue
            steps.append({
                "id": start_id + len(steps),
                "tool": tool,
                "arguments": args,
                "purpose": str(row.get("purpose") or allowed[tool].get("description") or "")[:600],
                "risk": allowed[tool].get("risk"),
                "status": "pending",
                "result": None,
                "confirmation_token": None,
            })
        return steps

    def create_plan(self, goal: str) -> dict[str, Any]:
        goal = str(goal or "").strip()
        if not goal:
            return {"ok": False, "error": "EMPTY_GOAL"}
        tools = self._candidate_tools(goal)
        if not tools:
            return {"ok": False, "error": "NO_RELEVANT_TOOLS", "goal": goal}
        requested = self._model_plan(goal, tools)
        steps = self._validated_steps(requested, tools, start_id=1, limit=self.max_steps)
        if not steps:
            return {"ok": False, "error": "MODEL_PRODUCED_NO_VALID_STEPS", "goal": goal, "available_tools": tools}
        plan_id = uuid.uuid4().hex[:10]
        plan = {
            "id": plan_id,
            "goal": goal[:4000],
            "created_at": _now(),
            "updated_at": _now(),
            "status": "planned",
            "adaptations": 0,
            "steps": steps,
        }
        with self._lock:
            data = self._load(); data.setdefault("plans", {})[plan_id] = plan; self._save(data)
        self.context.events.emit("TASK_PLAN_CREATED", plan_id=plan_id, steps=len(steps), goal=goal[:200])
        return {"ok": True, "plan": plan}

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        data = self._load()
        plan = (data.get("plans") or {}).get(str(plan_id or "").strip())
        if not plan:
            return {"ok": False, "error": "PLAN_NOT_FOUND", "plan_id": plan_id}
        return {"ok": True, "plan": plan}

    def list_plans(self, limit: int = 10) -> dict[str, Any]:
        plans = list((self._load().get("plans") or {}).values())
        plans.sort(key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""), reverse=True)
        cap = max(1, min(int(limit), 50))
        return {"ok": True, "plans": plans[:cap]}

    def _persist_plan(self, plan: dict[str, Any]) -> None:
        plan["updated_at"] = _now()
        with self._lock:
            data = self._load(); data.setdefault("plans", {})[plan["id"]] = plan; self._save(data)

    def execute_plan(self, plan_id: str, max_steps: int = 10) -> dict[str, Any]:
        loaded = self.get_plan(plan_id)
        if not loaded.get("ok"):
            return loaded
        plan = loaded["plan"]
        cap = max(1, min(int(max_steps), self.max_steps))
        executed = 0
        plan["status"] = "running"
        for step in plan.get("steps") or []:
            if executed >= cap:
                break
            if step.get("status") in {"completed", "failed", "superseded"}:
                continue
            if step.get("status") == "waiting_confirmation":
                plan["status"] = "waiting_confirmation"
                self._persist_plan(plan)
                return {"ok": True, "plan": plan, "waiting_confirmation": True, "token": step.get("confirmation_token")}
            tool = str(step.get("tool") or "")
            if tool not in self.context.registry.names:
                step["status"] = "failed"; step["result"] = {"ok": False, "error": "TOOL_NO_LONGER_AVAILABLE"}
                plan["status"] = "failed"; self._persist_plan(plan)
                return {"ok": False, "error": "TOOL_NO_LONGER_AVAILABLE", "plan": plan}
            raw = self.context.registry.execute(tool, step.get("arguments") or {})
            try:
                result = json.loads(raw)
            except Exception:
                result = {"ok": False, "error": "INVALID_TOOL_RESULT", "raw": raw}
            executed += 1
            step["result"] = result
            if isinstance(result, dict) and result.get("confirmation_required"):
                step["status"] = "waiting_confirmation"
                step["confirmation_token"] = result.get("token")
                plan["status"] = "waiting_confirmation"
                self._persist_plan(plan)
                self.context.events.emit("TASK_PLAN_WAITING_CONFIRMATION", plan_id=plan["id"], step=step["id"], token=result.get("token"))
                return {"ok": True, "plan": plan, "waiting_confirmation": True, "token": result.get("token")}
            failed = isinstance(result, dict) and (result.get("ok") is False or bool(result.get("error")))
            step["status"] = "failed" if failed else "completed"
            if failed:
                plan["status"] = "failed"
                self._persist_plan(plan)
                self.context.events.emit("TASK_PLAN_FAILED", plan_id=plan["id"], step=step["id"], tool=tool)
                return {"ok": False, "error": "STEP_FAILED", "plan": plan, "failed_step": step}
            self._persist_plan(plan)
        remaining = [s for s in plan.get("steps") or [] if s.get("status") not in {"completed", "failed", "superseded"}]
        plan["status"] = "completed" if not remaining else "paused"
        self._persist_plan(plan)
        self.context.events.emit("TASK_PLAN_PROGRESS", plan_id=plan["id"], status=plan["status"], executed=executed)
        return {"ok": True, "plan": plan, "executed": executed}

    def adapt_plan(self, plan_id: str) -> dict[str, Any]:
        """Replan once (configurable) from real execution evidence after failure."""
        loaded = self.get_plan(plan_id)
        if not loaded.get("ok"):
            return loaded
        plan = loaded["plan"]
        adaptations = int(plan.get("adaptations") or 0)
        if adaptations >= self.max_adaptations:
            return {"ok": False, "error": "ADAPTATION_LIMIT_REACHED", "plan": plan}
        failed = next((s for s in reversed(plan.get("steps") or []) if s.get("status") == "failed"), None)
        if failed is None:
            return {"ok": False, "error": "NO_FAILED_STEP_TO_ADAPT", "plan": plan}
        tools = self._candidate_tools(str(plan.get("goal") or ""))
        if not tools:
            return {"ok": False, "error": "NO_RELEVANT_TOOLS", "plan": plan}
        evidence = []
        for step in (plan.get("steps") or [])[-8:]:
            if step.get("status") not in {"completed", "failed"}:
                continue
            evidence.append({
                "tool": step.get("tool"),
                "arguments": step.get("arguments"),
                "status": step.get("status"),
                "result": step.get("result"),
            })
        remaining_slots = max(1, self.max_steps - sum(1 for s in plan.get("steps") or [] if s.get("status") == "completed"))
        requested = self._model_plan(
            str(plan.get("goal") or ""),
            tools,
            execution_context={"reason": "previous_step_failed", "evidence": evidence},
            max_steps=remaining_slots,
        )
        next_id = max([int(s.get("id") or 0) for s in plan.get("steps") or []] + [0]) + 1
        new_steps = self._validated_steps(requested, tools, start_id=next_id, limit=remaining_slots)
        if not new_steps:
            return {"ok": False, "error": "MODEL_PRODUCED_NO_VALID_ADAPTATION", "plan": plan}
        # Pending steps from the obsolete branch are kept for audit but not run.
        for step in plan.get("steps") or []:
            if step.get("status") == "pending":
                step["status"] = "superseded"
        plan.setdefault("steps", []).extend(new_steps)
        plan["adaptations"] = adaptations + 1
        plan["status"] = "planned"
        self._persist_plan(plan)
        self.context.events.emit("TASK_PLAN_ADAPTED", plan_id=plan["id"], adaptation=plan["adaptations"], steps=len(new_steps))
        return {"ok": True, "plan": plan, "new_steps": new_steps}

    def run_goal(self, goal: str) -> dict[str, Any]:
        created = self.create_plan(goal)
        if not created.get("ok"):
            return created
        plan_id = created["plan"]["id"]
        execution = self.execute_plan(plan_id, max_steps=self.max_steps)
        adaptation = None
        if not execution.get("ok") and execution.get("error") == "STEP_FAILED" and self.max_adaptations > 0:
            adaptation = self.adapt_plan(plan_id)
            if adaptation.get("ok"):
                execution = self.execute_plan(plan_id, max_steps=self.max_steps)
        return {
            "ok": bool(execution.get("ok")),
            "created": created,
            "adaptation": adaptation,
            "execution": execution,
        }

    def record_confirmation(self, token: str, confirmation_result: dict[str, Any]) -> dict[str, Any]:
        wanted = str(token or "").strip().upper()
        data = self._load()
        for plan in (data.get("plans") or {}).values():
            for step in plan.get("steps") or []:
                if str(step.get("confirmation_token") or "").upper() != wanted:
                    continue
                step["result"] = confirmation_result
                step["status"] = "completed" if confirmation_result.get("ok") else "failed"
                step["confirmation_token"] = None
                plan["status"] = "paused" if confirmation_result.get("ok") else "failed"
                plan["updated_at"] = _now()
                self._save(data)
                self.context.events.emit("TASK_PLAN_CONFIRMATION_RECORDED", plan_id=plan["id"], step=step["id"], ok=confirmation_result.get("ok"))
                return {"ok": True, "plan_id": plan["id"], "step": step["id"], "status": step["status"]}
        return {"ok": False, "error": "CONFIRMATION_NOT_LINKED_TO_PLAN", "token": wanted}

    def status(self) -> dict[str, Any]:
        plans = list((self._load().get("plans") or {}).values())
        return {
            "ok": True,
            "path": str(self.path),
            "plan_count": len(plans),
            "active": sum(1 for p in plans if p.get("status") in {"planned", "running", "paused", "waiting_confirmation"}),
            "max_steps": self.max_steps,
            "max_adaptations": self.max_adaptations,
            "confirmation_bypass": False,
        }


class TaskPlannerSkill(Skill):
    skill_id = "task_planner"
    name = "Autonomous Task Planner"
    version = "1.1.0"
    description = "Plan multi-step goals with the local model, validate tools, execute safe steps, adapt once from failures, and pause on confirmations."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = AutonomousTaskPlanner(context)
        context.services["task_planner"] = self.service

    def tools(self) -> list[SkillTool]:
        markers = ("resolve isto", "resolve", "trata disto", "trata disso", "faz isto", "planeia", "plano", "passos", "autónomo", "autonomo", "tarefa complexa")
        return [
            SkillTool("get_task_planner_status", "Read autonomous Task Planner status.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("create_task_plan", "Create and persist a validated multi-step plan using only currently registered tools; does not execute it.", self.service.create_plan, {"type":"object","properties":{"goal":{"type":"string"}},"required":["goal"]}, RiskLevel.LOW, markers),
            SkillTool("execute_task_plan", "Execute pending steps in a validated plan; underlying tool risk gates remain active and confirmation steps pause the plan.", self.service.execute_plan, {"type":"object","properties":{"plan_id":{"type":"string"},"max_steps":{"type":"integer","minimum":1,"maximum":20}},"required":["plan_id"]}, RiskLevel.LOW, markers),
            SkillTool("adapt_task_plan", "Adapt a failed task plan from actual step evidence, within the configured bounded adaptation limit.", self.service.adapt_plan, {"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"]}, RiskLevel.LOW, markers),
            SkillTool("run_autonomous_task", "Create and immediately execute a bounded multi-step task plan. It may adapt from one failure but can never bypass confirmation-required steps.", self.service.run_goal, {"type":"object","properties":{"goal":{"type":"string"}},"required":["goal"]}, RiskLevel.LOW, markers),
            SkillTool("get_task_plan", "Read one persisted task plan and step results.", self.service.get_plan, {"type":"object","properties":{"plan_id":{"type":"string"}},"required":["plan_id"]}, RiskLevel.READ_ONLY, markers),
            SkillTool("list_task_plans", "List recent local task plans.", self.service.list_plans, {"type":"object","properties":{"limit":{"type":"integer","minimum":1,"maximum":50}}}, RiskLevel.READ_ONLY, markers),
        ]

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return TaskPlannerSkill(context)
