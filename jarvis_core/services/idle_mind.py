from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from jarvis_core.services.synthetic_self import synthetic_self


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo is not None else dt.astimezone()
    except Exception:
        return None


def _statements(rows: Any, limit: int = 3) -> list[str]:
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows[-limit:]:
        if isinstance(row, dict):
            text = str(row.get("statement") or row.get("text") or "").strip()
        else:
            text = str(row or "").strip()
        if text:
            out.append(text[:240])
    return out


class IdleMindService:
    """Safe OWNER-facing snapshot of what JARVIS is attending to while idle.

    This is functional observability, not hidden chain-of-thought.  It reports
    persisted attention, gates and possible initiatives that the runtime can
    actually inspect.  It deliberately does not ask the LLM to invent an
    internal monologue merely because the OWNER requested a status view.
    """

    def __init__(
        self,
        *,
        settings,
        cognition,
        activity_trace,
        companion_service,
        silence_latch,
        wake,
        planner_provider: Callable[[], Any] | None = None,
        reflection_provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings
        self.cognition = cognition
        self.activity_trace = activity_trace
        self.companion_service = companion_service
        self.silence_latch = silence_latch
        self.wake = wake
        self.planner_provider = planner_provider
        self.reflection_provider = reflection_provider

    @staticmethod
    def _deterministic_next_action(
        *,
        candidate: dict[str, Any] | None,
        companion: dict[str, Any],
        planner: dict[str, Any] | None,
        profile: dict[str, Any],
        pending_insights: int,
    ) -> dict[str, Any] | None:
        if candidate:
            return {
                "kind": "proactive_message",
                "summary": str(candidate.get("text") or "")[:280],
                "reason": candidate.get("reason"),
                "permission_required": False,
            }
        if planner and int(planner.get("active") or 0) > 0:
            return {
                "kind": "resume_active_plan",
                "summary": "Existe um plano autónomo ainda ativo.",
                "reason": "planner_active",
                "permission_required": False,
            }
        if pending_insights > 0:
            return {
                "kind": "review_pending_insight",
                "summary": f"Há {pending_insights} insight(s) pendente(s) na cognição local.",
                "reason": "pending_insights",
                "permission_required": False,
            }
        projects = _statements(profile.get("projects"), 1)
        if projects:
            return {
                "kind": "continue_project",
                "summary": projects[-1],
                "reason": "active_project",
                "permission_required": True,
            }
        goals = _statements(profile.get("goals"), 1)
        if goals:
            return {
                "kind": "continue_goal",
                "summary": goals[-1],
                "reason": "explicit_goal",
                "permission_required": True,
            }
        if companion.get("eligible"):
            return {
                "kind": "companion_decision",
                "summary": "O Companion está elegível para decidir se vale a pena falar.",
                "reason": "companion_eligible",
                "permission_required": False,
            }
        return None

    def snapshot(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        cognitive = self.cognition.status()
        profile = self.cognition.profile().get("model") or {}
        last_dt = _parse_dt(cognitive.get("last_interaction_at"))
        idle_seconds = None
        if last_dt is not None:
            idle_seconds = max(0, int((now - last_dt).total_seconds()))

        candidate = self.cognition.proactive_candidate(
            min_interval_minutes=float(self.settings.proactive_min_interval_minutes),
            idle_seconds=float(self.settings.proactive_idle_seconds),
            quiet_start_hour=int(self.settings.proactive_quiet_start_hour),
            quiet_end_hour=int(self.settings.proactive_quiet_end_hour),
            max_per_hour=int(self.settings.proactive_max_per_hour),
        )
        companion = self.companion_service.idle_status()
        activity = self.activity_trace.status().get("current") or {}
        planner = None
        if self.planner_provider is not None:
            try:
                service = self.planner_provider()
                planner = service.status() if service is not None else None
            except Exception:
                planner = None
        wake_status = self.wake.status()
        try:
            self_state = synthetic_self().snapshot()
        except Exception:
            self_state = {}

        consideration = None
        if candidate:
            consideration = {
                "source": "proactive_presence",
                "reason": candidate.get("reason"),
                "priority": candidate.get("priority"),
                "possible_message": str(candidate.get("text") or "")[:320],
            }
        elif companion.get("eligible"):
            consideration = {
                "source": "companion_presence",
                "reason": "eligible_for_model_decision",
                "possible_message": None,
            }

        pending_insights = int(cognitive.get("pending_insights") or 0)
        possible_next_action = self._deterministic_next_action(
            candidate=candidate,
            companion=companion,
            planner=planner,
            profile=profile,
            pending_insights=pending_insights,
        )

        return {
            "ok": True,
            "mode": "SILENT_IDLE" if self.silence_latch.active() else "IDLE",
            "model_actively_reasoning": False,
            "idle_seconds_since_last_interaction": idle_seconds,
            "attention": {
                "recent_topics": list(cognitive.get("recent_topics") or [])[:5],
                "goals": _statements(profile.get("goals"), 3),
                "projects": _statements(profile.get("projects"), 3),
                "pending_insights": pending_insights,
            },
            "synthetic_self_state": self_state,
            "considering": consideration,
            "possible_next_action": possible_next_action,
            "proactive_gate": {
                "candidate_ready": bool(candidate),
                "speech_enabled": bool(cognitive.get("proactive_speech_enabled", True)),
            },
            "companion_gate": companion,
            "planner": planner,
            "listening": {
                "wake_running": bool(wake_status.get("running")),
                "device": wake_status.get("device"),
                "last_command": wake_status.get("last_command"),
            },
            "last_observable_activity": activity,
            "note": (
                "Este estado mostra atenção, memória, gates e iniciativas observáveis. "
                "Em idle o modelo não mantém um monólogo interno contínuo e este comando "
                "não expõe chain-of-thought privado."
            ),
        }
    def reflect(self) -> dict[str, Any]:
        """On-demand high-level idle deliberation summary from the local model.

        The normal snapshot remains instant and deterministic. This optional
        call is explicit, tool-free and asks only for a concise summary of what
        could be useful next; it never requests or exposes chain-of-thought.
        """
        snapshot = self.snapshot()
        if self.reflection_provider is None:
            return {
                "ok": False,
                "error": "REFLECTION_PROVIDER_UNAVAILABLE",
                "snapshot": snapshot,
            }
        compact = {
            "mode": snapshot.get("mode"),
            "idle_seconds": snapshot.get("idle_seconds_since_last_interaction"),
            "attention": snapshot.get("attention"),
            "possible_next_action": snapshot.get("possible_next_action"),
            "planner": snapshot.get("planner"),
            "silence_active": bool(self.silence_latch.active()),
            "wake_running": (snapshot.get("listening") or {}).get("wake_running"),
        }
        reflection = self.reflection_provider(compact)
        return {
            "ok": bool(reflection.get("ok")),
            "mode": snapshot.get("mode"),
            "snapshot": snapshot,
            "reflection": reflection,
            "note": "Reflexão de alto nível observável; não contém chain-of-thought privado.",
        }

