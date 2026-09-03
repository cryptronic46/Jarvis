from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, RLock, Thread
from time import monotonic
from typing import Any, Callable
import json
import re
import unicodedata


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class PerformancePlan:
    profile: str
    reason: str
    pressure: str
    think: bool
    num_ctx: int
    num_predict: int
    max_tool_rounds: int
    history_messages: int
    max_tools: int
    keep_alive: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PerformanceGovernor:
    """
    Lightweight local resource governor.

    It never launches its own expensive probes. CPU/RAM/GPU pressure comes
    from TelemetryService's cached sample so performance management does not
    become another source of load.
    """

    MODES = {"auto", "fast", "balanced", "deep", "eco"}

    DEEP_MARKERS = (
        "analise profunda",
        "análise profunda",
        "investiga a fundo",
        "muito detalhado",
        "arquitetura complexa",
        "arquitectura complexa",
        "debug complexo",
        "problema complexo",
        "raciocina profundamente",
        "usa o melhor modelo",
        "usa o sol",
    )

    BALANCED_MARKERS = (
        "analisa",
        "análise",
        "compara",
        "comparar",
        "investiga",
        "diagnostica",
        "diagnóstico",
        "estratégia",
        "estrategia",
        "planeia",
        "plano",
        "explica",
        "recomenda",
        "avalia",
        "otimiza",
        "optimiza",
        "debug",
        "código",
        "codigo",
    )

    LOCAL_SENSITIVE_MARKERS = (
        "ciber",
        "cyber",
        "firewall",
        "defender",
        "malware",
        "ransomware",
        "cve-",
        "mitre",
        "owasp",
        "rdp",
        "smb",
        "memoria local",
        "memória local",
        "ficheiro local",
        "arquivo local",
        "meu pc",
        "meu computador",
    )

    def __init__(
        self,
        settings,
        events,
        telemetry,
        state_path: str | Path = "memory/performance_state.json",
    ):
        self.settings = settings
        self.events = events
        self.telemetry = telemetry
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = RLock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._on_sustained_pressure: Callable[[dict[str, Any]], None] | None = None
        self._request_active = 0
        self._high_samples = 0
        self._pressure_callback_fired = False
        self._latencies_ms: deque[int] = deque(maxlen=40)
        self._routes: deque[str] = deque(maxlen=40)
        self._last_plan: PerformancePlan | None = None

        state = self._load_state()
        mode = str(state.get("mode") or getattr(settings, "performance_mode", "auto")).lower()
        self._mode = mode if mode in self.MODES else "auto"

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        self.state_path.write_text(
            json.dumps(
                {"mode": self._mode},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> dict[str, Any]:
        wanted = str(mode or "").strip().lower()
        if wanted not in self.MODES:
            return {
                "ok": False,
                "error": "INVALID_PERFORMANCE_MODE",
                "allowed": sorted(self.MODES),
            }

        with self._lock:
            self._mode = wanted
            self._save_state()

        self.events.emit(
            "PERFORMANCE_MODE_CHANGED",
            mode=wanted,
        )
        return {
            "ok": True,
            "mode": wanted,
        }

    def begin_request(self) -> None:
        with self._lock:
            self._request_active += 1

    def end_request(self) -> None:
        with self._lock:
            self._request_active = max(
                0,
                self._request_active - 1,
            )

    def request_active(self) -> bool:
        with self._lock:
            return self._request_active > 0

    def pressure(self) -> dict[str, Any]:
        sample = self.telemetry.latest() or {}

        cpu = _number(sample.get("cpu_percent"))
        memory = _number(sample.get("memory_percent"))

        gpu_util = None
        gpu_vram = None
        gpu_rows = sample.get("gpu") or []
        for gpu in gpu_rows:
            util = _number(gpu.get("utilization_percent"))
            used = _number(gpu.get("memory_used_mib"))
            total = _number(gpu.get("memory_total_mib"))

            if util is not None:
                gpu_util = max(gpu_util or 0.0, util)

            if used is not None and total and total > 0:
                pct = used / total * 100.0
                gpu_vram = max(gpu_vram or 0.0, pct)

        high = (
            (cpu is not None and cpu >= float(self.settings.performance_high_cpu_percent))
            or (
                memory is not None
                and memory >= float(self.settings.performance_high_memory_percent)
            )
            or (
                gpu_util is not None
                and gpu_util >= float(self.settings.performance_high_gpu_percent)
            )
            or (
                gpu_vram is not None
                and gpu_vram >= float(self.settings.performance_high_vram_percent)
            )
        )

        elevated = (
            (cpu is not None and cpu >= float(self.settings.performance_elevated_cpu_percent))
            or (
                memory is not None
                and memory >= float(self.settings.performance_elevated_memory_percent)
            )
            or (
                gpu_util is not None
                and gpu_util >= float(self.settings.performance_elevated_gpu_percent)
            )
            or (
                gpu_vram is not None
                and gpu_vram >= float(self.settings.performance_elevated_vram_percent)
            )
        )

        critical = (
            (memory is not None and memory >= 95.0)
            or (cpu is not None and cpu >= 96.0)
            or (gpu_util is not None and gpu_util >= 98.0)
            or (gpu_vram is not None and gpu_vram >= 95.0)
        )

        level = (
            "critical"
            if critical
            else "high"
            if high
            else "elevated"
            if elevated
            else "normal"
        )

        return {
            "level": level,
            "cpu_percent": cpu,
            "memory_percent": memory,
            "gpu_utilization_percent": gpu_util,
            "gpu_vram_percent": (
                round(gpu_vram, 1)
                if gpu_vram is not None
                else None
            ),
            "sampled_at": sample.get("sampled_at"),
        }

    def _intent_profile(self, user_text: str) -> str:
        text = _norm(user_text)

        if any(_norm(marker) in text for marker in self.DEEP_MARKERS):
            return "deep"

        score = 0
        if len(text) >= 320:
            score += 2
        elif len(text) >= 160:
            score += 1

        for marker in self.BALANCED_MARKERS:
            if _norm(marker) in text:
                score += 1
                if score >= 2:
                    break

        if score >= 2:
            return "deep"
        if score == 1:
            return "balanced"
        return "fast"

    def _profile_values(
        self,
        profile: str,
        pressure: str,
        user_text: str,
    ) -> PerformancePlan:
        base_ctx = int(self.settings.llm_num_ctx)
        base_predict = int(self.settings.llm_num_predict)

        if profile == "eco":
            return PerformancePlan(
                profile="eco",
                reason="resource_pressure",
                pressure=pressure,
                think=False,
                num_ctx=min(
                    base_ctx,
                    int(self.settings.performance_eco_ctx),
                ),
                num_predict=min(
                    base_predict,
                    int(self.settings.performance_eco_predict),
                ),
                max_tool_rounds=min(
                    int(self.settings.max_tool_rounds),
                    2,
                ),
                history_messages=int(
                    self.settings.performance_history_eco
                ),
                max_tools=int(
                    self.settings.performance_tool_budget_eco
                ),
                keep_alive=str(
                    self.settings.performance_eco_keep_alive
                ),
            )

        if profile == "fast":
            return PerformancePlan(
                profile="fast",
                reason="simple_request",
                pressure=pressure,
                think=False,
                num_ctx=min(
                    base_ctx,
                    int(self.settings.performance_fast_ctx),
                ),
                num_predict=min(
                    base_predict,
                    int(self.settings.performance_fast_predict),
                ),
                max_tool_rounds=min(
                    int(self.settings.max_tool_rounds),
                    2,
                ),
                history_messages=int(
                    self.settings.performance_history_fast
                ),
                max_tools=int(
                    self.settings.performance_tool_budget_fast
                ),
                keep_alive=str(self.settings.ollama_keep_alive),
            )

        if profile == "deep":
            return PerformancePlan(
                profile="deep",
                reason="complex_request",
                pressure=pressure,
                think=True,
                num_ctx=min(
                    base_ctx,
                    int(self.settings.performance_deep_ctx),
                ),
                num_predict=max(
                    base_predict,
                    int(self.settings.performance_deep_predict),
                ),
                max_tool_rounds=int(
                    self.settings.max_tool_rounds
                ),
                history_messages=int(
                    self.settings.performance_history_deep
                ),
                max_tools=int(
                    self.settings.performance_tool_budget_deep
                ),
                keep_alive=str(self.settings.ollama_keep_alive),
            )

        # balanced
        should_think = self._intent_profile(user_text) == "deep"
        return PerformancePlan(
            profile="balanced",
            reason="normal_reasoning",
            pressure=pressure,
            think=should_think,
            num_ctx=min(
                base_ctx,
                int(self.settings.performance_balanced_ctx),
            ),
            num_predict=min(
                max(base_predict, 220),
                int(self.settings.performance_balanced_predict),
            ),
            max_tool_rounds=min(
                int(self.settings.max_tool_rounds),
                4,
            ),
            history_messages=int(
                self.settings.performance_history_balanced
            ),
            max_tools=int(
                self.settings.performance_tool_budget_balanced
            ),
            keep_alive=str(self.settings.ollama_keep_alive),
        )

    def plan(self, user_text: str) -> PerformancePlan:
        pressure = self.pressure().get("level", "normal")
        mode = self.mode

        if not bool(getattr(self.settings, "performance_enabled", True)):
            mode = "balanced"

        if mode != "auto":
            profile = mode
        else:
            profile = self._intent_profile(user_text)

            if pressure == "elevated":
                if profile == "deep":
                    profile = "balanced"
            elif pressure in {"high", "critical"}:
                if profile == "deep":
                    profile = "balanced"
                else:
                    profile = "eco"

        plan = self._profile_values(
            profile,
            pressure,
            user_text,
        )

        if mode != "auto":
            plan.reason = f"manual_{mode}"

        with self._lock:
            self._last_plan = plan

        self.events.emit(
            "PERFORMANCE_PLAN",
            **plan.to_dict(),
        )
        return plan

    def should_offload_to_cloud(self, user_text: str) -> bool:
        if self.mode != "auto":
            return False
        if not bool(
            getattr(
                self.settings,
                "performance_cloud_offload_under_pressure",
                True,
            )
        ):
            return False

        pressure = self.pressure().get("level")
        if pressure not in {"high", "critical"}:
            return False

        text = _norm(user_text)
        if any(
            _norm(marker) in text
            for marker in self.LOCAL_SENSITIVE_MARKERS
        ):
            return False

        return True

    def should_defer_background(self, workload: str = "") -> bool:
        if not bool(
            getattr(
                self.settings,
                "performance_background_defer_under_pressure",
                True,
            )
        ):
            return False

        if self.request_active():
            return True

        return self.pressure().get("level") in {
            "high",
            "critical",
        }

    def should_warm_llm(self) -> bool:
        if self.request_active():
            return False
        return self.pressure().get("level") not in {
            "high",
            "critical",
        }

    def record_request(
        self,
        *,
        elapsed_ms: int,
        route: str,
    ) -> None:
        with self._lock:
            self._latencies_ms.append(
                max(0, int(elapsed_ms))
            )
            self._routes.append(str(route or ""))

    def status(self) -> dict[str, Any]:
        with self._lock:
            latencies = list(self._latencies_ms)
            routes = list(self._routes)
            last_plan = (
                self._last_plan.to_dict()
                if self._last_plan
                else None
            )

        return {
            "ok": True,
            "mode": self.mode,
            "pressure": self.pressure(),
            "request_active": self.request_active(),
            "last_plan": last_plan,
            "recent_requests": len(latencies),
            "average_latency_ms": (
                round(sum(latencies) / len(latencies))
                if latencies
                else None
            ),
            "recent_routes": routes[-8:],
            "gpu_sampling_seconds": float(
                self.settings.performance_gpu_sample_interval_seconds
            ),
            "cloud_offload_under_pressure": bool(
                self.settings.performance_cloud_offload_under_pressure
            ),
            "background_defer_under_pressure": bool(
                self.settings.performance_background_defer_under_pressure
            ),
            "release_llm_on_pressure": bool(
                self.settings.performance_release_llm_on_pressure
            ),
        }

    def start(
        self,
        on_sustained_pressure: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._on_sustained_pressure = on_sustained_pressure
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            name="jarvis-performance-governor",
            daemon=True,
        )
        self._thread.start()
        self.events.emit(
            "PERFORMANCE_GOVERNOR_STARTED",
            mode=self.mode,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.events.emit("PERFORMANCE_GOVERNOR_STOPPED")

    def _loop(self) -> None:
        interval = max(
            1.0,
            float(self.settings.performance_monitor_interval_seconds),
        )
        required = max(
            2,
            int(self.settings.performance_sustained_high_samples),
        )

        while not self._stop.wait(interval):
            pressure = self.pressure()
            level = pressure.get("level")

            if self.request_active():
                # Never treat JARVIS's own active inference burst as an
                # external sustained-pressure event.
                self._high_samples = 0
                continue

            if level in {"high", "critical"}:
                self._high_samples += 1
            else:
                self._high_samples = 0
                self._pressure_callback_fired = False

            if (
                self._high_samples >= required
                and not self._pressure_callback_fired
            ):
                self._pressure_callback_fired = True
                self.events.emit(
                    "PERFORMANCE_SUSTAINED_PRESSURE",
                    **pressure,
                )

                callback = self._on_sustained_pressure
                if callback is not None:
                    try:
                        callback(pressure)
                    except Exception as exc:
                        self.events.emit(
                            "PERFORMANCE_PRESSURE_CALLBACK_ERROR",
                            error=f"{type(exc).__name__}: {exc}",
                        )
