from __future__ import annotations

from threading import Event, Thread, RLock
from time import monotonic
from typing import Any


class ListeningWatchdogService:
    """Keep the always-listening wake stream healthy without bypassing policy.

    The watchdog only repairs the local audio path. It never executes user
    commands and never changes security permissions. It deliberately backs off
    while TTS is speaking, the wake service is hard-paused, or audio is
    temporarily suppressed for barge-in/self-audio protection.
    """

    def __init__(
        self,
        events,
        wake,
        speech,
        *,
        enabled: bool = True,
        armed: bool = True,
        interval_seconds: float = 3.0,
        stream_grace_seconds: float = 8.0,
        recovery_cooldown_seconds: float = 15.0,
    ) -> None:
        self.events = events
        self.wake = wake
        self.speech = speech
        self.enabled = bool(enabled)
        self.armed = bool(armed)
        self.interval = max(1.0, float(interval_seconds))
        self.stream_grace = max(3.0, float(stream_grace_seconds))
        self.cooldown = max(5.0, float(recovery_cooldown_seconds))
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = RLock()
        self._unhealthy_since: float | None = None
        self._last_recovery_at = 0.0
        self._recoveries = 0
        self._last_recovery_reason: str | None = None
        self._last_recovery_result: dict[str, Any] | None = None
        self._device_waiting = False

    def _emit(self, name: str, **data: Any) -> None:
        try:
            self.events.emit(name, **data)
        except Exception:
            pass

    def status(self) -> dict[str, Any]:
        wake = self.wake.status()
        speech = self.speech.status()
        with self._lock:
            unhealthy_for = (
                max(0.0, monotonic() - self._unhealthy_since)
                if self._unhealthy_since is not None
                else 0.0
            )
            return {
                "ok": True,
                "enabled": self.enabled,
                "armed": self.armed,
                "running": bool(self._thread and self._thread.is_alive()),
                "interval_seconds": self.interval,
                "stream_grace_seconds": self.stream_grace,
                "recovery_cooldown_seconds": self.cooldown,
                "unhealthy_for_seconds": round(unhealthy_for, 2),
                "recoveries": self._recoveries,
                "last_recovery_reason": self._last_recovery_reason,
                "last_recovery_result": self._last_recovery_result,
                "device_waiting": self._device_waiting,
                "wake": wake,
                "speech": speech,
            }

    def set_armed(self, armed: bool) -> None:
        with self._lock:
            self.armed = bool(armed)
            if not self.armed:
                self._unhealthy_since = None
                self._device_waiting = False
        self._emit("LISTENING_WATCHDOG_ARMED", armed=self.armed)

    def _recovery_allowed(self) -> bool:
        return monotonic() - self._last_recovery_at >= self.cooldown

    def recover(self, reason: str = "manual") -> dict[str, Any]:
        if not self.enabled and reason != "manual":
            return {"ok": False, "error": "LISTENING_WATCHDOG_DISABLED"}

        speech = self.speech.status()
        wake_before = self.wake.status()
        if speech.get("speaking"):
            return {"ok": False, "error": "TTS_ACTIVE", "wake": wake_before}
        if wake_before.get("hard_paused"):
            return {"ok": False, "error": "WAKE_HARD_PAUSED", "wake": wake_before}
        if not wake_before.get("enabled"):
            return {"ok": False, "error": "WAKE_DISABLED", "wake": wake_before}
        if not wake_before.get("configured"):
            return {"ok": False, "error": "WAKE_NOT_CONFIGURED", "wake": wake_before}
        if not wake_before.get("enrolled"):
            return {"ok": False, "error": "WAKE_NOT_ENROLLED", "wake": wake_before}

        # A stale TTS suppression is safe to clear only when speech reports idle.
        if wake_before.get("audio_suppressed"):
            try:
                self.wake.suppress_audio(False, reason="tts", tail_seconds=0.0)
                self._emit("LISTENING_STALE_SUPPRESSION_CLEARED", reason=reason)
            except Exception as exc:
                return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

        try:
            self.wake.stop()
            start_result = self.wake.start()
        except Exception as exc:
            start_result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}

        with self._lock:
            self._last_recovery_at = monotonic()
            self._last_recovery_reason = str(reason)
            self._last_recovery_result = dict(start_result)
            if start_result.get("ok"):
                self._recoveries += 1
                self._unhealthy_since = None
                if reason == "owner_manual":
                    self.armed = True

        self._emit(
            "LISTENING_RECOVERY",
            reason=reason,
            ok=bool(start_result.get("ok")),
            result=start_result,
        )
        return {
            "ok": bool(start_result.get("ok")),
            "reason": reason,
            "wake_before": wake_before,
            "start": start_result,
            "wake_after": self.wake.status(),
        }

    def _check_once(self) -> None:
        if not self.enabled or not self.armed:
            return
        wake = self.wake.status()
        speech = self.speech.status()

        # Legitimate temporary states: never fight them.
        if speech.get("speaking") or wake.get("hard_paused"):
            with self._lock:
                self._unhealthy_since = None
            return

        # Voice V2 owns reconnects while its worker thread is alive. A USB
        # microphone being unplugged is an expected unavailable-device state,
        # not a dead worker. Restarting here would reset Voice V2's exponential
        # backoff and cause a noisy, tight recovery loop.
        if wake.get("running") and wake.get("device_unavailable"):
            with self._lock:
                first_wait = not self._device_waiting
                self._device_waiting = True
                self._unhealthy_since = None
            if first_wait:
                self._emit(
                    "LISTENING_DEVICE_WAITING",
                    failures=wake.get("device_failure_count"),
                    reconnect_in_seconds=wake.get("device_reconnect_in_seconds"),
                    last_error=wake.get("last_error"),
                )
            return

        # If the only problem is stale TTS suppression while TTS is idle, clear
        # it without reopening the stream.
        if wake.get("running") and wake.get("stream_active") and wake.get("audio_suppressed"):
            try:
                self.wake.suppress_audio(False, reason="tts", tail_seconds=0.0)
                self._emit("LISTENING_STALE_SUPPRESSION_CLEARED", reason="watchdog")
            except Exception:
                pass
            with self._lock:
                self._unhealthy_since = None
            return

        healthy = bool(wake.get("running") and wake.get("stream_active"))
        if healthy:
            with self._lock:
                was_waiting = self._device_waiting
                self._device_waiting = False
                self._unhealthy_since = None
            if was_waiting:
                self._emit("LISTENING_DEVICE_RECONNECTED")
            return

        # Do not spam recovery when wake cannot legitimately run.
        if not (wake.get("enabled") and wake.get("configured") and wake.get("enrolled")):
            with self._lock:
                self._unhealthy_since = None
            return

        now = monotonic()
        with self._lock:
            self._device_waiting = False
            if self._unhealthy_since is None:
                self._unhealthy_since = now
                self._emit(
                    "LISTENING_UNHEALTHY",
                    running=bool(wake.get("running")),
                    stream_active=bool(wake.get("stream_active")),
                    last_error=wake.get("last_error"),
                )
                return
            unhealthy_for = now - self._unhealthy_since

        if unhealthy_for >= self.stream_grace and self._recovery_allowed():
            reason = "thread_stopped" if not wake.get("running") else "stream_inactive"
            self.recover(reason=reason)

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="jarvis-listening-watchdog", daemon=True)
        self._thread.start()
        self._emit("LISTENING_WATCHDOG_STARTED", interval_seconds=self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._emit("LISTENING_WATCHDOG_STOPPED")

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self._check_once()
            except Exception as exc:
                self._emit("LISTENING_WATCHDOG_ERROR", error=f"{type(exc).__name__}: {exc}")
