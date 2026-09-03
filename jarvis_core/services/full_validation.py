from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
import json
import os

from jarvis_core.core.config import Settings
from jarvis_core.core.events import EventBus
from jarvis_core.core.hybrid_brain import HybridRoutePolicy
from jarvis_core.services.windows_block_audit import audit_windows_blocked_files
from jarvis_core.services.listening import MicrophoneService
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2
from jarvis_core.services.speaker_verification import SpeakerVerifier
from jarvis_core.services.voice_pipeline import listening_config_from_settings, voice_v2_config_from_settings, speaker_config_from_settings


def _row(name: str, ok: bool, **data: Any) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), **data}


def validate_native_runtime() -> dict[str, Any]:
    versions: dict[str, str] = {}
    try:
        import numpy
        import sounddevice
        import ctranslate2
        import onnxruntime
        import pyaudiowpatch
        versions.update({
            "numpy": getattr(numpy, "__version__", "unknown"),
            "sounddevice": getattr(sounddevice, "__version__", "unknown"),
            "ctranslate2": getattr(ctranslate2, "__version__", "unknown"),
            "onnxruntime": getattr(onnxruntime, "__version__", "unknown"),
            "pyaudiowpatch": getattr(pyaudiowpatch, "__version__", "unknown"),
        })
        from jarvis_core.services.openwakeword_compat import runtime_classes
        Model, Vad = runtime_classes()
        Model(wakeword_models=["hey_jarvis"], inference_framework="onnx", vad_threshold=0.0)
        Vad(n_threads=1)
        from jarvis_core.services.stt_compat import probe_faster_whisper_pcm_import
        probe = probe_faster_whisper_pcm_import()
        if not probe.get("ok"):
            raise RuntimeError(probe.get("message") or probe.get("error") or "STT probe failed")
        return _row("native_runtime", True, versions=versions, stt=probe)
    except Exception as exc:
        return _row("native_runtime", False, error=f"{type(exc).__name__}: {exc}", versions=versions)


def validate_voice_runtime_pipeline(settings: Settings) -> dict[str, Any]:
    """Exercise the exact Voice v2 configuration and classes used by the CLI.

    On the real Windows machine this validates the actual WASAPI/openWakeWord
    doctor and loads Faster-Whisper through MicrophoneService. No parallel
    model constructor or alternate device selector is used. Validation errors
    are reported as a structured failed row instead of aborting the entire
    full-system report.
    """
    if os.name != "nt":
        return _row("voice_runtime_pipeline", True, skipped=True, reason="non_windows")

    expected_backend = "cpu/int8"
    microphone = None
    voice = None
    preload: dict[str, Any] = {"ok": False, "skipped": True, "reason": "not_started"}
    residency: dict[str, Any] = {}
    release: dict[str, Any] = {"ok": True, "released": False}
    try:
        events = EventBus(
            settings.log_dir,
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
        microphone = MicrophoneService(
            events, listening_config_from_settings(settings, voice_v2=True)
        )
        voice = VoiceEngineV2(
            events,
            voice_v2_config_from_settings(settings),
            on_wake=lambda _inline=None: None,
            transcribe_callback=microphone.transcribe_command_file,
            wake_transcribe_callback=microphone.transcribe_wake_file,
            on_interrupt=lambda: None,
            cleanup_callback=microphone.cleanup_capture,
            release_stt_callback=microphone.release_stt,
        )
        doctor = voice.doctor()
        live_input = (
            voice.probe_live_input(seconds=0.60)
            if doctor.get("ok")
            else {"ok": False, "skipped": True, "reason": "voice_doctor_failed"}
        )
        preload = (
            microphone.preload_stt()
            if doctor.get("ok") and live_input.get("ok")
            else {"ok": False, "skipped": True, "reason": "voice_input_not_live"}
        )
        residency = microphone.stt_residency_status()
        release = microphone.release_stt() if preload.get("ok") else {"ok": True, "released": False}
        ok = (
            bool(doctor.get("ok"))
            and bool(live_input.get("ok"))
            and bool(preload.get("ok"))
            and str(preload.get("backend") or "").lower() == expected_backend
            and str(residency.get("device_preference") or "").lower() == "cpu"
            and bool(release.get("ok"))
        )
        return _row(
            "voice_runtime_pipeline",
            ok,
            doctor=doctor,
            live_input=live_input,
            stt_preload=preload,
            stt_residency=residency,
            stt_release=release,
            expected_backend=expected_backend,
            error=None if ok else "VOICE_RUNTIME_PIPELINE_NOT_HEALTHY",
        )
    except Exception as exc:
        if microphone is not None:
            try:
                residency = microphone.stt_residency_status()
            except Exception:
                residency = {}
        return _row(
            "voice_runtime_pipeline",
            False,
            stt_preload=preload,
            stt_residency=residency,
            stt_release=release,
            expected_backend=expected_backend,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        if microphone is not None:
            try:
                if microphone.stt_residency_status().get("loaded"):
                    microphone.release_stt()
            except Exception:
                pass
        if voice is not None:
            try:
                voice.stop()
            except Exception:
                pass

def validate_voice_lock_policy(settings: Settings) -> dict[str, Any]:
    """Verify Voice Lock is either healthy or fails closed into safe-disable."""
    events = EventBus(
        settings.log_dir,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    verifier = SpeakerVerifier(events, speaker_config_from_settings(settings))
    if not verifier.config.enabled:
        return _row("voice_lock_policy", True, configured=False, effective=False)
    health = verifier.ensure_ready()
    if health.get("ok"):
        return _row("voice_lock_policy", True, configured=True, effective=True, health=health)
    verifier.set_enabled(False)
    return _row(
        "voice_lock_policy", True, configured=True, effective=False,
        auto_disabled=True, health=health,
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
        validate_native_runtime(),
        validate_voice_runtime_pipeline(settings),
        validate_voice_lock_policy(settings),
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
