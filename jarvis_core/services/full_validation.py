from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
import json
import os

from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridRoutePolicy
from jarvis_core.services.windows_block_audit import audit_windows_blocked_files


def _row(name: str, ok: bool, **data: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), **data}


LOCAL_VOICE_DISABLED_FIELDS = (
    "local_voice_enabled",
)


def validate_local_voice_retired(
    settings: Settings,
) -> dict[str, Any]:
    """Verify retired PC-local voice stays disabled.

    This check is deliberately state-only. It never imports or
    instantiates microphone, STT, wakeword, TTS, speaker verification
    or physical audio-device services.
    """
    state = {
        field: bool(getattr(settings, field, False))
        for field in LOCAL_VOICE_DISABLED_FIELDS
    }

    enabled_fields = [
        field
        for field, enabled in state.items()
        if enabled
    ]

    ok = not enabled_fields

    return _row(
        "local_voice_retired",
        ok,
        configured=False,
        effective=False,
        device_access=False,
        microphone_opened=False,
        stt_started=False,
        wakeword_started=False,
        audio_playback_started=False,
        enabled_fields=enabled_fields,
        state=state,
        error=None if ok else "LOCAL_VOICE_REENABLED",
    )


def validate_local_brain(settings: Settings) -> dict[str, Any]:
    """Exercise the same JARVIS-owned local client used by runtime."""
    started = monotonic()
    try:
        from jarvis_core.core.local_llm import build_local_client
        client = build_local_client(settings)
        response = client.chat(
            model=str(settings.model),
            messages=[{"role": "user", "content": "Responde apenas com OK."}],
            think=False,
            stream=False,
            options={"num_ctx": 512, "num_predict": 24, "temperature": 0},
        )
        message = getattr(response, "message", None)
        text = str(getattr(message, "content", "") or "").strip()
        return _row(
            "jarvis_native_local_reasoning", bool(text), model=settings.model,
            backend=settings.local_llm_backend, response=text[:100],
            elapsed_ms=round((monotonic() - started) * 1000),
            error=None if text else "EMPTY_LOCAL_RESPONSE",
        )
    except Exception as exc:
        return _row(
            "jarvis_native_local_reasoning", False, model=settings.model,
            backend=getattr(settings, "local_llm_backend", ""),
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=round((monotonic() - started) * 1000),
        )


def validate_routing(settings: Settings) -> dict[str, Any]:
    policy = HybridRoutePolicy(settings)
    simple = policy.decide("Abre o Brave")
    complex_text = (
        "Faz uma auditoria completa desta arquitetura complexa, analisa profundamente os trade-offs, "
        "refatora o desenho e apresenta um plano detalhado multi-etapa com riscos e alternativas. " * 4
    )
    complex_decision = policy.decide(complex_text)
    threshold = int(settings.external_ai_complexity_threshold)
    ok = (
        simple.route == "local"
        and simple.complexity_score < threshold
        and complex_decision.route == "local"
        and complex_decision.complexity_score >= threshold
        and settings.external_ai_complex_only
        and not settings.cloud_fallback_on_local_error
        and not settings.performance_cloud_offload_under_pressure
    )
    return _row(
        "local_first_policy", ok,
        simple_score=simple.complexity_score,
        complex_score=complex_decision.complexity_score,
        threshold=threshold,
        external_ai_complex_only=settings.external_ai_complex_only,
    )


def run_full_validation(root: str | Path = ".") -> dict[str, Any]:
    root = Path(root).resolve()
    os.chdir(root)
    settings = Settings.load(root / "settings.json")
    checks = [
        validate_local_voice_retired(settings),
        validate_local_brain(settings),
        validate_routing(settings),
    ]
    audit = audit_windows_blocked_files(root=root, save_report=True)
    checks.append(_row(
        "windows_block_audit",
        bool(audit.get("ok"))
        and len(audit.get("active_block_events") or []) == 0
        and len(audit.get("native_import_failures") or []) == 0,
        status=audit.get("status"),
        active_blocks=len(audit.get("active_block_events") or []),
        resolved_historical=len(audit.get("resolved_historical_block_events") or []),
        mitigated=len(audit.get("mitigated_block_events") or []),
        motw=len(audit.get("motw_current") or []),
        native_failures=audit.get("native_import_failures") or [],
    ))
    report = {
        "ok": all(row.get("ok") for row in checks),
        "version": "0.27.8",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "root": str(root),
        "checks": checks,
    }
    out = root / "logs" / "full_validation_0277.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(out)
    return report


if __name__ == "__main__":
    report = run_full_validation()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report.get("ok") else 1)
