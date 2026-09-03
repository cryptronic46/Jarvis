from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from threading import Event as ThreadEvent, Lock, Thread
from time import sleep
from typing import Any

import psutil

from jarvis_core.core.events import EventBus
from jarvis_core.tools.system_tools import read_gpu_status


@dataclass(slots=True)
class TelemetrySample:
    sampled_at: str
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_used_gib: float
    gpu: list[dict[str, Any]]


class TelemetryService:
    def __init__(
        self,
        events: EventBus,
        interval_seconds: float = 1.0,
        history_seconds: int = 120,
        gpu_interval_seconds: float = 3.0,
    ):
        self.events = events
        self.interval = max(0.5, float(interval_seconds))
        self.gpu_interval = max(
            self.interval,
            float(gpu_interval_seconds),
        )
        maxlen = max(30, int(history_seconds / self.interval))
        self._samples: deque[TelemetrySample] = deque(maxlen=maxlen)
        self._lock = Lock()
        self._stop = ThreadEvent()
        self._thread: Thread | None = None
        self._last_gpu: list[dict[str, Any]] = []
        self._last_gpu_monotonic: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="jarvis-telemetry", daemon=True)
        self._thread.start()
        self.events.emit(
            "TELEMETRY_STARTED",
            interval_seconds=self.interval,
            gpu_interval_seconds=self.gpu_interval,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.events.emit("TELEMETRY_STOPPED")

    def _loop(self) -> None:
        psutil.cpu_percent(interval=None)
        while not self._stop.is_set():
            started = datetime.now().timestamp()
            now_mono = __import__("time").monotonic()
            vm = psutil.virtual_memory()

            if (
                not self._last_gpu
                or now_mono - self._last_gpu_monotonic >= self.gpu_interval
            ):
                self._last_gpu = read_gpu_status()
                self._last_gpu_monotonic = now_mono

            sample = TelemetrySample(
                sampled_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
                timestamp=started,
                cpu_percent=psutil.cpu_percent(interval=None),
                memory_percent=vm.percent,
                memory_used_gib=round(vm.used / (1024 ** 3), 2),
                gpu=list(self._last_gpu),
            )
            with self._lock:
                self._samples.append(sample)
            elapsed = datetime.now().timestamp() - started
            if self._stop.wait(max(0.05, self.interval - elapsed)):
                return

    def latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._samples:
                return None
            return asdict(self._samples[-1])

    def latest_before(self, timestamp: float) -> dict[str, Any] | None:
        with self._lock:
            for sample in reversed(self._samples):
                if sample.timestamp <= timestamp:
                    return asdict(sample)
        return None

    def recent(self, seconds: int = 10) -> list[dict[str, Any]]:
        cutoff = datetime.now().timestamp() - max(1, int(seconds))
        with self._lock:
            return [asdict(s) for s in self._samples if s.timestamp >= cutoff]
