from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
import json

from jarvis_core.services.personal_cognition import personal_cognition


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if dt.tzinfo is not None else dt.astimezone()
    except Exception:
        return None


class CompanionPresenceService:
    """Context-driven social initiative for the local JARVIS persona.

    Timing/rate limits are deterministic product guards. The decision to speak
    and the wording are delegated to the local model planner; there are no
    prewritten flirt lines or random phrase tables in this service.
    """

    def __init__(
        self,
        planner: Callable[[dict[str, Any]], dict[str, Any]],
        output_callback: Callable[[str, dict[str, Any]], None],
        *,
        state_path: str | Path = "memory/companion_presence.json",
        enabled: bool = True,
        flirt_enabled: bool = True,
        flirt_intensity: float = 0.60,
        check_interval_seconds: float = 60.0,
        startup_delay_seconds: float = 180.0,
        decision_cooldown_seconds: float = 180.0,
        min_interval_minutes: float = 25.0,
        idle_seconds: float = 150.0,
        quiet_start_hour: int = 23,
        quiet_end_hour: int = 8,
        max_per_hour: int = 1,
        max_chars: int = 260,
    ) -> None:
        self.planner = planner
        self.output_callback = output_callback
        self.state_path = Path(state_path)
        self.enabled = bool(enabled)
        self.flirt_enabled = bool(flirt_enabled)
        self.flirt_intensity = max(0.0, min(float(flirt_intensity), 1.0))
        self.check_interval_seconds = max(15.0, float(check_interval_seconds))
        self.startup_delay_seconds = max(0.0, float(startup_delay_seconds))
        self.decision_cooldown_seconds = max(30.0, float(decision_cooldown_seconds))
        self.min_interval_minutes = max(2.0, float(min_interval_minutes))
        self.idle_seconds = max(30.0, float(idle_seconds))
        self.quiet_start_hour = int(quiet_start_hour) % 24
        self.quiet_end_hour = int(quiet_end_hour) % 24
        self.max_per_hour = max(1, int(max_per_hour))
        self.max_chars = max(80, min(int(max_chars), 600))
        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._state = self._load_state()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "version": 1,
            "last_decision_at": None,
            "last_spoken_at": None,
            "history": [],
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()
        if not isinstance(raw, dict):
            return self._default_state()
        state = self._default_state()
        state.update(raw)
        if not isinstance(state.get("history"), list):
            state["history"] = []
        return state

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            name="jarvis-companion-presence",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        self.enabled = bool(enabled)
        return self.status()

    def set_flirt_enabled(self, enabled: bool) -> dict[str, Any]:
        self.flirt_enabled = bool(enabled)
        return self.status()

    def set_intensity(self, value: float) -> dict[str, Any]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return {"ok": False, "error": "INVALID_COMPANION_INTENSITY"}
        if not 0.0 <= number <= 1.0:
            return {"ok": False, "error": "COMPANION_INTENSITY_RANGE_0_TO_1"}
        self.flirt_intensity = number
        return self.status()

    def idle_status(self) -> dict[str, Any]:
        """Read-only gate state for OWNER idle observability."""
        eligible, reason = self._eligible()
        return {
            "ok": True,
            "eligible": bool(eligible),
            "gate_reason": reason,
            "enabled": self.enabled,
            "flirt_enabled": self.flirt_enabled,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        return {
            "ok": True,
            "enabled": self.enabled,
            "flirt_enabled": self.flirt_enabled,
            "flirt_intensity": round(self.flirt_intensity, 2),
            "initiative_model_driven": True,
            "prewritten_flirt_lines": False,
            "subjective_volition_claimed": False,
            "last_decision_at": state.get("last_decision_at"),
            "last_spoken_at": state.get("last_spoken_at"),
            "recent_history": list(state.get("history") or [])[-5:],
        }

    def _in_quiet_hours(self, now: datetime) -> bool:
        hour = now.hour
        if self.quiet_start_hour > self.quiet_end_hour:
            return hour >= self.quiet_start_hour or hour < self.quiet_end_hour
        return self.quiet_start_hour <= hour < self.quiet_end_hour

    def _eligible(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "disabled"
        now = _now()
        if self._in_quiet_hours(now):
            return False, "quiet_hours"

        cognition_state = personal_cognition().state()
        last_interaction = _parse_dt(cognition_state.get("last_interaction_at"))
        if last_interaction is None:
            return False, "no_interaction"
        idle = (now - last_interaction).total_seconds()
        if idle < self.idle_seconds:
            return False, "not_idle_enough"
        # Avoid speaking out of nowhere after an old abandoned session.
        if idle > 45 * 60:
            return False, "session_too_old"

        with self._lock:
            last_decision = _parse_dt(self._state.get("last_decision_at"))
            last_spoken = _parse_dt(self._state.get("last_spoken_at"))
            history = list(self._state.get("history") or [])

        if last_decision and (now - last_decision).total_seconds() < self.decision_cooldown_seconds:
            return False, "decision_cooldown"
        if last_spoken and now - last_spoken < timedelta(minutes=self.min_interval_minutes):
            return False, "speech_cooldown"

        spoken_last_hour = 0
        for row in history:
            when = _parse_dt(row.get("timestamp")) if isinstance(row, dict) else None
            if when and now - when <= timedelta(hours=1) and row.get("spoken"):
                spoken_last_hour += 1
        if spoken_last_hour >= self.max_per_hour:
            return False, "hourly_cap"
        return True, "eligible"

    def evaluate_once(self) -> dict[str, Any]:
        eligible, gate_reason = self._eligible()
        if not eligible:
            return {"ok": True, "eligible": False, "reason": gate_reason}

        context = {
            "flirt_enabled": self.flirt_enabled,
            "flirt_intensity": self.flirt_intensity,
            "max_chars": self.max_chars,
            "local_time": _iso(),
        }
        with self._lock:
            self._state["last_decision_at"] = _iso()
            self._save_state()

        try:
            decision = self.planner(context)
        except Exception as exc:
            return {
                "ok": False,
                "error": "COMPANION_PLANNER_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
            }
        if not isinstance(decision, dict):
            return {"ok": False, "error": "INVALID_COMPANION_PLANNER_RESULT"}

        speak = bool(decision.get("speak"))
        text = str(decision.get("text") or "").strip()
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rstrip()
        if speak and not text:
            speak = False

        history_row = {
            "timestamp": _iso(),
            "spoken": speak,
            "tone": str(decision.get("tone") or "")[:40],
            "reason": str(decision.get("reason") or "")[:180],
            "text": text if speak else "",
        }
        with self._lock:
            history = list(self._state.get("history") or [])
            history.append(history_row)
            self._state["history"] = history[-50:]
            if speak:
                self._state["last_spoken_at"] = history_row["timestamp"]
            self._save_state()

        if speak:
            self.output_callback(text, decision)
        return {
            "ok": True,
            "eligible": True,
            "spoken": speak,
            "tone": history_row["tone"],
            "reason": history_row["reason"],
        }

    def _loop(self) -> None:
        if self._stop.wait(self.startup_delay_seconds):
            return
        while not self._stop.is_set():
            try:
                self.evaluate_once()
            except Exception:
                pass
            if self._stop.wait(self.check_interval_seconds):
                break
