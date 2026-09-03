from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Event as ThreadEvent, RLock, Thread
from typing import Any
import json

from jarvis_core.core.events import Event, EventBus


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class ActivityTraceService:
    """Safe observability view of JARVIS activity.

    It intentionally exposes *states, decisions and actions*, never hidden
    chain-of-thought.  The trace is designed for OWNER diagnostics and the HUD.
    """

    SAFE_EVENTS = {
        "VOICE_HEARD",
        "WAKE_CANDIDATE",
        "WAKE_CANDIDATE_CONFIRMED",
        "WAKE_CANDIDATE_REJECTED",
        "INPUT_RECEIVED",
        "REQUEST_INTENT_CLASSIFIED",
        "HYBRID_ROUTE",
        "FAST_PATH_HIT",
        "THINKING_STARTED",
        "TOOL_SCHEMA_SELECTION",
        "TOOL_EXECUTING",
        "TOOL_FINISHED",
        "TOOL_REPEAT_SUPPRESSED",
        "CONFIRMATION_REQUIRED",
        "TASK_PLAN_CREATED",
        "TASK_PLAN_PROGRESS",
        "TASK_PLAN_WAITING_CONFIRMATION",
        "TASK_PLAN_ADAPTED",
        "TASK_PLAN_FAILED",
        "PROACTIVE_MESSAGE",
        "COMPANION_MESSAGE",
        "RESPONSE_READY",
        "SILENCE_LATCHED",
        "SILENCE_RELEASED",
        "SILENCE_OUTPUT_SUPPRESSED",
    }

    def __init__(self, events: EventBus, path: str = "memory/activity_trace.json", enabled: bool = True, live: bool = False, keep_last: int = 80) -> None:
        self.events = events
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.enabled = bool(enabled)
        self._live = bool(live)
        self._recent: deque[dict[str, Any]] = deque(maxlen=max(20, int(keep_last)))
        self._lock = RLock()
        self._queue: Queue[dict[str, Any]] = Queue(maxsize=256)
        self._stop = ThreadEvent()
        self._thread = Thread(target=self._worker, name="jarvis-activity-trace", daemon=True)
        self._current = {"stage": "IDLE", "detail": "Núcleo disponível", "updated_at": _now()}

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self.events.subscribe(self._on_event)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait({"_stop": True})
        except Exception:
            pass
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._flush()

    def set_live(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self._live = bool(enabled)
        return self.status()

    def _safe_entry(self, event: Event) -> dict[str, Any] | None:
        if event.name not in self.SAFE_EVENTS:
            return None
        d = event.data
        stage = event.name
        detail = ""
        if event.name == "VOICE_HEARD":
            stage = "OUVI"
            text = str(d.get("text") or "")[:220]
            raw = str(d.get("raw_text") or text)[:220]
            detail = text if raw == text else f"processado='{text}' | bruto='{raw}'"
        elif event.name == "WAKE_CANDIDATE":
            stage = "WAKE?"
            detail = f"candidato acústico score={d.get('score')}"
        elif event.name == "WAKE_CANDIDATE_CONFIRMED":
            stage = "WAKE"
            detail = f"confirmado: {str(d.get('transcript') or '')[:120]}"
        elif event.name == "WAKE_CANDIDATE_REJECTED":
            stage = "IGNORADO"
            detail = f"não era Jarvis: {str(d.get('transcript') or '')[:120]}"
        elif event.name == "REQUEST_INTENT_CLASSIFIED":
            stage = "INTENÇÃO"
            detail = str(d.get("contract") or "")[:220]
        elif event.name == "HYBRID_ROUTE":
            stage = "ROTA"
            detail = f"{d.get('route')} — {d.get('reason')}"
        elif event.name == "FAST_PATH_HIT":
            stage = "ROTA"
            detail = f"FAST/{d.get('route')} — {d.get('tool') or 'determinístico'}"
        elif event.name == "THINKING_STARTED":
            stage = "PROCESSO"
            detail = f"Qwen local / perfil {d.get('profile')}"
        elif event.name == "TOOL_SCHEMA_SELECTION":
            stage = "CAPACIDADES"
            tools = d.get("tools") or []
            detail = ", ".join(str(x) for x in tools[:8]) or "sem ferramenta"
        elif event.name == "TOOL_EXECUTING":
            stage = "AÇÃO"
            detail = str(d.get("tool") or "")
        elif event.name == "TOOL_FINISHED":
            stage = "RESULTADO"
            detail = f"{d.get('tool')} — {'OK' if d.get('ok') else 'ERRO'}"
        elif event.name == "TOOL_REPEAT_SUPPRESSED":
            stage = "OTIMIZAÇÃO"
            detail = f"repetição evitada: {d.get('tool')}"
        elif event.name == "CONFIRMATION_REQUIRED":
            stage = "AGUARDA"
            detail = f"confirmação OWNER para {d.get('tool')}"
        elif event.name.startswith("TASK_PLAN_"):
            stage = "PLANO"
            detail = f"{event.name.replace('TASK_PLAN_', '').lower()} plan={d.get('plan_id')} step={d.get('step')}"
            if d.get("goal"):
                detail += f" goal={str(d.get('goal'))[:140]}"
        elif event.name == "PROACTIVE_MESSAGE":
            stage = "INICIATIVA"
            detail = f"proatividade: {d.get('reason')}"
        elif event.name == "COMPANION_MESSAGE":
            stage = "INICIATIVA"
            detail = f"companion/{d.get('tone')}: {d.get('reason')}"
        elif event.name == "RESPONSE_READY":
            stage = "RESPOSTA"
            detail = f"pronta em {d.get('elapsed_ms')} ms"
        elif event.name == "SILENCE_LATCHED":
            stage = "SILÊNCIO"
            detail = "latch ativo; saída conversacional suspensa"
        elif event.name == "SILENCE_RELEASED":
            stage = "ATIVO"
            detail = f"silêncio libertado por {d.get('source')}"
        elif event.name == "SILENCE_OUTPUT_SUPPRESSED":
            stage = "SUPRIMIDO"
            detail = f"saída {d.get('kind')} descartada pelo silence latch"
        else:
            return None
        return {"time": event.timestamp, "stage": stage, "detail": detail, "event": event.name}

    def _on_event(self, event: Event) -> None:
        if not self.enabled:
            return
        entry = self._safe_entry(event)
        if entry is None:
            return
        try:
            self._queue.put_nowait(entry)
        except Exception:
            pass

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                entry = self._queue.get(timeout=0.5)
            except Empty:
                continue
            if entry.get("_stop"):
                break
            with self._lock:
                self._recent.append(entry)
                self._current = {"stage": entry["stage"], "detail": entry["detail"], "updated_at": entry["time"]}
                live = self._live
            if live:
                print(f"\n[JARVIS/{entry['stage']}] {entry['detail']}")
            self._flush()

    def _flush(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            payload = {
                "updated_at": _now(),
                "live": self._live,
                "current": dict(self._current),
                "recent": list(self._recent)[-30:],
            }
        try:
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "ok": True,
                "enabled": self.enabled,
                "live": self._live,
                "path": str(self.path),
                "current": dict(self._current),
                "recent": list(self._recent)[-12:],
                "note": "Mostra estados/decisões/ações observáveis; não expõe chain-of-thought interno.",
            }

    def last(self, count: int = 12) -> dict[str, Any]:
        with self._lock:
            return {"ok": True, "entries": list(self._recent)[-max(1, min(int(count), 40)):]}
