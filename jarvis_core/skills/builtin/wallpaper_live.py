from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event as ThreadEvent, Thread, RLock
from typing import Any
import json

from jarvis_core.core.events import Event
from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class LiveWallpaperStateService:
    """Publish a compact, read-only HUD state file for the Wallpaper bridge."""

    ACTIVITY_EVENTS = {
        "THINKING_STARTED": ("THINKING", "A processar"),
        "MODEL_REQUEST": ("THINKING", "Núcleo neural em inferência"),
        "TOOL_EXECUTING": ("WORKING", "A executar ferramenta"),
        "SPEECH_STARTED": ("SPEAKING", "A responder"),
        "LISTENING_STARTED": ("LISTENING", "A escutar"),
        "WAKE_WORD_DETECTED": ("LISTENING", "Wake word confirmada"),
        "VOICE_HEARD": ("LISTENING", "Voz transcrita"),
        "WAKE_CANDIDATE": ("LISTENING", "A confirmar wake word"),
        "WAKE_CANDIDATE_REJECTED": ("IDLE", "Falso wake ignorado"),
        "SILENCE_LATCHED": ("SILENT", "Silêncio conversacional ativo"),
        "SILENCE_RELEASED": ("LISTENING", "Silêncio libertado"),
        "RESPONSE_READY": ("IDLE", "Núcleo neural ativo"),
        "SPEECH_FINISHED": ("IDLE", "Núcleo neural ativo"),
        "PURPLE_TEAM_STARTED": ("CYBER", "Purple Team em execução"),
        "PURPLE_TEAM_FINISHED": ("IDLE", "Purple Team concluído"),
        "SYSTEM_GUARDIAN_ALERT": ("WATCH", "System Guardian detetou alterações"),
        "TASK_PLAN_CREATED": ("PLANNING", "Plano autónomo criado"),
        "TASK_PLAN_WAITING_CONFIRMATION": ("WAITING", "Plano aguarda confirmação"),
        "TASK_PLAN_PROGRESS": ("WORKING", "Plano autónomo em progresso"),
        "VISION_CAPTURED": ("VISION", "Visão: ecrã capturado"),
        "VISION_ANALYZED": ("VISION", "Visão local concluída"),
        "SELF_REPAIR_STARTED": ("REPAIR", "Auto-diagnóstico/reparação"),
        "SELF_REPAIR_FINISHED": ("IDLE", "Auto-reparação concluída"),
    }

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.path = Path(getattr(context.settings, "wallpaper_live_state_path", "memory/live_hud.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.interval = max(1.0, float(getattr(context.settings, "wallpaper_live_interval_seconds", 2.0)))
        self._lock = RLock()
        self._stop = ThreadEvent()
        self._dirty = ThreadEvent()
        self._thread: Thread | None = None
        self._active = False
        self._state: dict[str, Any] = {
            "updated_at": _now(),
            "mode": "IDLE",
            "message": "Núcleo neural ativo",
            "active_tool": None,
            "active_skill": None,
            "guardian_alert_count": 0,
            "guardian": {"total": 0, "critical": 0, "high": 0, "attention": 0, "other": 0},
            "task_plan": None,
            "purple_team": None,
            "vision": None,
            "activity": {"stage": "IDLE", "detail": "Núcleo disponível", "timestamp": _now()},
            "last_event": None,
        }
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            self._state["updated_at"] = _now()
            self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _on_event(self, event: Event) -> None:
        if not self._active:
            return
        with self._lock:
            self._state["last_event"] = {"name": event.name, "timestamp": event.timestamp}
            mapping = self.ACTIVITY_EVENTS.get(event.name)
            if mapping:
                self._state["mode"], self._state["message"] = mapping
            if event.name == "VOICE_HEARD":
                text = str(event.data.get("text") or "")[:220]
                raw = str(event.data.get("raw_text") or text)[:220]
                detail = text if raw == text else f"processado={text} | bruto={raw}"
                self._state["activity"] = {"stage": "OUVI", "detail": detail, "timestamp": event.timestamp}
            elif event.name == "HYBRID_ROUTE":
                self._state["activity"] = {"stage": "ROTA", "detail": f"{event.data.get('route')} — {event.data.get('reason')}", "timestamp": event.timestamp}
            elif event.name == "THINKING_STARTED":
                self._state["activity"] = {"stage": "PROCESSO", "detail": f"Qwen local / {event.data.get('profile')}", "timestamp": event.timestamp}
            elif event.name == "TOOL_EXECUTING":
                self._state["activity"] = {"stage": "AÇÃO", "detail": str(event.data.get("tool") or ""), "timestamp": event.timestamp}
            elif event.name in {"PROACTIVE_MESSAGE", "COMPANION_MESSAGE"}:
                self._state["activity"] = {"stage": "INICIATIVA", "detail": str(event.data.get("reason") or "iniciativa local"), "timestamp": event.timestamp}
            elif event.name == "SILENCE_LATCHED":
                self._state["activity"] = {"stage": "SILÊNCIO", "detail": "saída conversacional suspensa", "timestamp": event.timestamp}
            elif event.name == "WAKE_CANDIDATE_REJECTED":
                self._state["activity"] = {"stage": "IGNORADO", "detail": f"falso wake: {str(event.data.get('transcript') or '')[:140]}", "timestamp": event.timestamp}

            if event.name == "TOOL_EXECUTING":
                tool = event.data.get("tool")
                self._state["active_tool"] = tool
                try:
                    described = {row["name"]: row for row in self.context.registry.describe()}
                    self._state["active_skill"] = (described.get(tool) or {}).get("skill_id")
                except Exception:
                    self._state["active_skill"] = None
            elif event.name == "TOOL_FINISHED":
                self._state["active_tool"] = None
            elif event.name == "SYSTEM_GUARDIAN_ALERT":
                total = int(event.data.get("count") or 0)
                counts = dict(event.data.get("severity_counts") or {})
                if not counts:
                    counts = {"critical": 0, "high": 0, "attention": 0, "other": total}
                    for alert in event.data.get("alerts") or []:
                        sev = str(alert.get("severity") or "other").lower()
                        if sev not in counts:
                            sev = "other"
                        counts[sev] = int(counts.get(sev) or 0) + 1
                counts["total"] = total
                guardian = {
                    "total": total,
                    "critical": int(counts.get("critical") or 0),
                    "high": int(counts.get("high") or 0),
                    "attention": int(counts.get("attention") or 0),
                    "other": int(counts.get("other") or 0),
                }
                self._state["guardian_alert_count"] = total
                self._state["guardian"] = guardian
                if guardian["critical"] or guardian["high"]:
                    self._state["mode"] = "ALERT"
                elif total:
                    self._state["mode"] = "WATCH"
                self._state["message"] = (
                    f"Guardian: {guardian['critical']} critical · "
                    f"{guardian['high']} high · {guardian['attention']} attention"
                )
            elif event.name == "SYSTEM_GUARDIAN_OK":
                self._state["guardian_alert_count"] = 0
                self._state["guardian"] = {"total": 0, "critical": 0, "high": 0, "attention": 0, "other": 0}
            elif event.name.startswith("TASK_PLAN_"):
                self._state["task_plan"] = {
                    "id": event.data.get("plan_id"),
                    "status": event.name.replace("TASK_PLAN_", "").lower(),
                    "step": event.data.get("step"),
                }
            elif event.name.startswith("PURPLE_TEAM_"):
                self._state["purple_team"] = {
                    "target": event.data.get("target"),
                    "status": event.name.replace("PURPLE_TEAM_", "").lower(),
                }
            elif event.name.startswith("VISION_"):
                self._state["vision"] = {
                    "status": event.name.replace("VISION_", "").lower(),
                    "path": event.data.get("path"),
                }
        # Never perform disk I/O inside EventBus callbacks. Wake/audio events
        # may originate from latency-sensitive threads, so we only mark the
        # state dirty here and let the dedicated HUD worker coalesce writes.
        self._dirty.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._dirty.wait(timeout=self.interval)
            self._dirty.clear()
            if self._stop.is_set():
                break
            try:
                self._flush()
            except Exception:
                pass

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self.context.events.subscribe(self._on_event)
        self._stop.clear()
        self._dirty.clear()
        self._thread = Thread(target=self._loop, name="jarvis-live-wallpaper-state", daemon=True)
        self._thread.start()
        self.context.events.emit("LIVE_WALLPAPER_STATE_STARTED", path=str(self.path))

    def stop(self) -> None:
        self._active = False
        self._stop.set()
        self._dirty.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, **json.loads(json.dumps(self._state))}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "running": bool(self._active),
            "path": str(self.path),
            "interval_seconds": self.interval,
            "bridge_contract": "memory/live_hud.json",
        }


class WallpaperLiveSkill(Skill):
    skill_id = "wallpaper_live"
    name = "Live Wallpaper State"
    version = "1.0.0"
    description = "Publish Core/skill/task/cyber/guardian state for the Wallpaper Engine HUD."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = LiveWallpaperStateService(context)
        context.services["wallpaper_live"] = self.service

    def tools(self) -> list[SkillTool]:
        markers = ("wallpaper", "hud", "interface", "ecrã jarvis", "ecra jarvis", "estado visual")
        return [
            SkillTool("get_live_wallpaper_state", "Read the compact live state currently published to the Wallpaper bridge.", self.service.state, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
        ]

    def start(self) -> None:
        self.service.start(); self.started = True

    def stop(self) -> None:
        self.service.stop(); self.started = False

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return WallpaperLiveSkill(context)
