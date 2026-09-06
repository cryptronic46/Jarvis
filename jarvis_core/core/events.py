from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from collections import deque
from pathlib import Path
from typing import Callable, Any
from threading import RLock
import json


@dataclass(slots=True)
class Event:
    name: str
    timestamp: str
    data: dict[str, Any]


class EventBus:
    def __init__(
        self,
        log_dir: str = "logs",
        keep_last: int = 300,
        max_bytes: int = 8 * 1024 * 1024,
        backup_count: int = 6,
    ):
        self._subscribers: list[Callable[[Event], None]] = []
        self._recent: deque[Event] = deque(maxlen=keep_last)
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.event_log = self.log_dir / "events.jsonl"
        self.max_bytes = max(256 * 1024, int(max_bytes))
        self.backup_count = max(1, min(int(backup_count), 30))
        self._lock = RLock()

    def _rotate_if_needed(self, incoming_bytes: int = 0) -> None:
        """Rotate JSONL logs without discarding the most recent evidence.

        Backups stay beside events.jsonl as events.jsonl.1 .. .N. Rotation is
        performed under the EventBus lock before the new event is appended.
        """
        try:
            current = self.event_log.stat().st_size if self.event_log.exists() else 0
        except OSError:
            current = 0
        if current + max(0, int(incoming_bytes)) <= self.max_bytes:
            return
        oldest = self.event_log.with_name(f"{self.event_log.name}.{self.backup_count}")
        try:
            oldest.unlink(missing_ok=True)
        except OSError:
            pass
        for index in range(self.backup_count - 1, 0, -1):
            src = self.event_log.with_name(f"{self.event_log.name}.{index}")
            dst = self.event_log.with_name(f"{self.event_log.name}.{index + 1}")
            if src.exists():
                try:
                    src.replace(dst)
                except OSError:
                    pass
        if self.event_log.exists():
            try:
                self.event_log.replace(self.event_log.with_name(f"{self.event_log.name}.1"))
            except OSError:
                pass

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def emit(self, name: str, **data: Any) -> Event:
        event = Event(
            name=name,
            timestamp=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            data=data,
        )

        line = json.dumps(asdict(event), ensure_ascii=False, default=str) + "\n"
        with self._lock:
            self._recent.append(event)
            self._rotate_if_needed(len(line.encode("utf-8")))
            with self.event_log.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line)
            subscribers = list(self._subscribers)

        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # Subscribers are observers. One failing observer must never
                # break event production or prevent later observers running.
                pass
        return event

    def recent(self, count: int = 20) -> list[Event]:
        with self._lock:
            return list(self._recent)[-count:]
