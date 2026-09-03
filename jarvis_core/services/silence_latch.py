from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from threading import RLock
from typing import Any

from jarvis_core.core.events import EventBus


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


@dataclass(slots=True)
class SilenceState:
    active: bool = False
    since: str | None = None
    reason: str | None = None
    source: str | None = None
    generation: int = 0
    suppressed_responses: int = 0
    suppressed_proactive: int = 0


class SilenceLatchService:
    """Conversation-level silence latch controlled by the OWNER.

    This is deliberately separate from SpeechService.stop().  stop() only
    cancels current playback; the latch also prevents stale/in-flight output
    and unsolicited presence from speaking again until a fresh wake or an
    explicit OWNER release occurs.
    """

    def __init__(self, events: EventBus, enabled: bool = True) -> None:
        self.events = events
        self.enabled = bool(enabled)
        self._lock = RLock()
        self._state = SilenceState()

    def latch(self, reason: str = "owner_interrupt", source: str = "voice") -> dict[str, Any]:
        with self._lock:
            if not self.enabled:
                return self.status()
            self._state.active = True
            self._state.since = _now()
            self._state.reason = str(reason or "owner_interrupt")
            self._state.source = str(source or "voice")
            self._state.generation += 1
            result = self.status()
        self.events.emit(
            "SILENCE_LATCHED",
            reason=result.get("reason"),
            source=result.get("source"),
            generation=result.get("generation"),
        )
        return result

    def release(self, source: str = "wake") -> dict[str, Any]:
        with self._lock:
            was_active = self._state.active
            self._state.active = False
            self._state.since = None
            self._state.reason = None
            self._state.source = str(source or "wake")
            self._state.generation += 1
            result = self.status()
        if was_active:
            self.events.emit(
                "SILENCE_RELEASED",
                source=result.get("source"),
                generation=result.get("generation"),
            )
        return result

    def active(self) -> bool:
        with self._lock:
            return bool(self.enabled and self._state.active)

    def generation(self) -> int:
        with self._lock:
            return int(self._state.generation)

    def output_allowed(self, request_generation: int | None = None) -> bool:
        with self._lock:
            if self.enabled and self._state.active:
                return False
            if request_generation is not None and int(request_generation) != int(self._state.generation):
                return False
            return True

    def mark_suppressed_response(self, kind: str = "response") -> None:
        with self._lock:
            if kind == "proactive":
                self._state.suppressed_proactive += 1
            else:
                self._state.suppressed_responses += 1
        self.events.emit("SILENCE_OUTPUT_SUPPRESSED", kind=kind)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "enabled": self.enabled, **asdict(self._state)}
