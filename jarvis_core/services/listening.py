from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from tempfile import gettempdir
from time import monotonic, sleep
from threading import Lock
from typing import Any
from uuid import uuid4
import math
import gc
import wave

from jarvis_core.core.events import EventBus
from jarvis_core.services.stt_compat import (
    load_whisper_model_class,
    load_wav_pcm_float32,
)
from jarvis_core.services.av_devices import webcam_audio_score


@dataclass(slots=True)
class ListeningConfig:
    device: int | None = None
    language: str = "pt"
    model: str = "small"
    stt_device: str = "cpu"  # auto | cuda | cpu
    download_root: str = "models/faster-whisper"
    calibration_seconds: float = 0.4
    start_timeout_seconds: float = 8.0
    max_phrase_seconds: float = 14.0
    silence_seconds: float = 0.65
    min_phrase_seconds: float = 0.35
    threshold_multiplier: float = 2.0
    threshold_floor: float = 0.006
    beam_size: int = 1

    # Lightweight second-stage confirmation for an acoustic wake candidate.
    # It only needs to distinguish the keyword from normal speech, so it must
    # stay much cheaper than the full command transcription profile.
    wake_candidate_beam_size: int = 1
    # Wake confirmation must be unbiased. Prompting/hotwords with "Jarvis" made
    # normal speech such as "Obrigado" hallucinate the keyword. The acoustic
    # matcher already narrows candidates; Whisper is only an independent veto.
    wake_candidate_initial_prompt: str = ""
    wake_candidate_hotwords: str = ""

    # Higher-accuracy decode profile for Always Listening commands.
    # Latency-first decode: greedy/beam-1 handles clear short commands; only
    # weak-confidence audio pays for the stronger second pass.
    command_beam_size: int = 1
    command_retry_beam_size: int = 5
    command_low_confidence_avg_logprob: float = -0.72
    command_low_confidence_no_speech: float = 0.35
    # Final fail-closed limits after the accuracy retry. The retry threshold is
    # intentionally earlier; these only reject clearly unreliable/hallucinated
    # decodes such as room noise becoming a fluent sentence.
    command_reject_avg_logprob: float = -1.00
    command_reject_no_speech: float = 0.55
    wake_reject_avg_logprob: float = -0.80
    wake_reject_no_speech: float = 0.40
    normalize_command_audio: bool = True
    command_target_rms: float = 0.08
    command_max_gain: float = 4.0
    command_trim_silence: bool = True
    command_trim_padding_ms: int = 140
    command_trim_floor_rms: float = 0.0025
    command_initial_prompt: str = (
        "Transcrição fiel em português europeu (pt-PT). Não traduzir. "
        "Preservar nomes próprios, marcas, números e termos técnicos. "
        "O utilizador fala naturalmente com a assistente Jarvis. "
        "Comandos e perguntas podem mencionar Brave, Spotify, Steam, Discord, "
        "Cyberpunk 2077, Windows, Kali Linux, volume, áudio, microfone, webcam, "
        "GPU, gráfica, VRAM, CPU, temperatura, memória, ficheiros e aplicações."
    )
    command_hotwords: str = (
        "Jarvis Brave Spotify Steam Discord Cyberpunk "
        "GPU CPU volume áudio gráfica temperatura"
    )

    stream_retries: int = 2
    stream_recovery_seconds: float = 0.8
    no_signal_rms: float = 0.00015
    cpu_threads: int = 6
    calibration_cache_seconds: float = 180.0
    cached_calibration_blocks: int = 1
    preferred_device_index: int | None = None
    preferred_device_name: str = "GENERAL WEBCAM"
    preferred_handsfree: bool = False
    preferred_samplerate: int = 48000
    prefer_webcam_audio: bool = True
    webcam_name_hint: str = ""
    probe_min_signal_rms: float = 0.001
    verified_signal_ttl_seconds: float = 120.0


def adaptive_threshold(
    noise_rms: float,
    multiplier: float = 2.0,
    floor: float = 0.006,
    ceiling: float = 0.030,
) -> float:
    """
    Speech-start threshold for close headset microphones.

    A hard ceiling prevents nearby speech/noise during calibration from making
    the detector effectively deaf to the owner. Speaker verification later in
    the pipeline is responsible for rejecting the wrong person.
    """
    return max(
        float(floor),
        min(float(ceiling), float(noise_rms) * float(multiplier)),
    )


def robust_noise_floor(values: list[float]) -> float:
    """
    Estimate ambient noise from the quieter half of the calibration window.

    This deliberately ignores loud blocks (for example, another person talking
    next to the user) instead of averaging them into the speech threshold.
    """
    cleaned = sorted(float(v) for v in values if v >= 0.0)
    if not cleaned:
        return 0.0
    quiet_count = max(1, (len(cleaned) + 1) // 2)
    quiet = cleaned[:quiet_count]
    mid = len(quiet) // 2
    if len(quiet) % 2:
        return quiet[mid]
    return (quiet[mid - 1] + quiet[mid]) / 2.0


def _rms_int16(raw_bytes: bytes) -> float:
    import numpy as np

    samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
    if samples.size == 0:
        return 0.0
    samples /= 32768.0
    return float(np.sqrt(np.mean(samples * samples)))


def _windows_hostapi_score(name: str) -> int:
    """Prefer stable shared Windows capture APIs over fragile WDM-KS duplicates."""
    value = str(name or "").lower()
    if "wasapi" in value:
        return 120
    if "directsound" in value:
        return 60
    if "mme" in value:
        return 30
    if "wdm-ks" in value or "wdm ks" in value:
        return -5000
    return 0


class MicrophoneService:
    """
    One-shot microphone capture + Faster Whisper transcription.

    Recording is intentionally push-to-talk in Core 0.4. Wake-word mode is
    layered on later after microphone and STT behavior are proven stable.
    """

    def __init__(self, events: EventBus, config: ListeningConfig):
        self.events = events
        self.config = config
        self._model = None
        self._model_backend: str | None = None
        self._model_error: str | None = None
        self._model_lock = Lock()
        self._threshold_cache: dict[tuple[int, int], tuple[float, float]] = {}
        self._verified_signal: dict[int, tuple[float, float]] = {}

    def release_stt(self) -> dict[str, Any]:
        """Release Faster Whisper model memory (CPU/GPU) without stopping audio.

        CTranslate2 frees its CUDA allocations when the model object is dropped.
        Voice Engine v2 calls this after an idle window so STT does not keep
        VRAM resident while JARVIS is only waiting for the wake word.
        """
        with self._model_lock:
            had_model = self._model is not None
            backend = self._model_backend
            self._model = None
            self._model_backend = None
        gc.collect()
        try:
            import ctranslate2
            unload = getattr(ctranslate2, "unload_model", None)
            if callable(unload):
                try:
                    unload()
                except Exception:
                    pass
        except Exception:
            pass
        self.events.emit("STT_MODEL_RELEASED", backend=backend, had_model=had_model)
        return {"ok": True, "released": had_model, "backend": backend}

    def stt_residency_status(self) -> dict[str, Any]:
        return {
            "loaded": self._model is not None,
            "backend": self._model_backend,
            "model": self.config.model,
            "device_preference": self.config.stt_device,
        }

    def preload_stt(self) -> dict[str, Any]:
        started = monotonic()
        try:
            self._load_model()
            elapsed_ms = round((monotonic() - started) * 1000)
            self.events.emit(
                "STT_PRELOADED",
                backend=self._model_backend,
                elapsed_ms=elapsed_ms,
            )
            return {
                "ok": True,
                "backend": self._model_backend,
                "elapsed_ms": elapsed_ms,
            }
        except Exception as exc:
            self.events.emit(
                "STT_PRELOAD_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    def _input_device_candidates(self) -> list[tuple[int, dict[str, Any]]]:
        """
        Return input candidates in real-use priority order.

        Windows Bluetooth devices often appear several times through different
        PortAudio host APIs. A device can be present in query_devices() and
        still fail when RawInputStream actually opens it. Therefore selection
        is a candidate list, not a single guessed index.
        """
        import sounddevice as sd

        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
        needle = (
            self.config.preferred_device_name
            or ""
        ).strip().lower()

        ranked: list[tuple[int, int, dict[str, Any]]] = []
        for idx, dev in enumerate(devices):
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue

            name = str(dev.get("name", ""))
            lower = name.lower()
            rate = int(
                float(dev.get("default_samplerate", 0) or 0)
            )

            score = 0
            if self.config.prefer_webcam_audio:
                score += webcam_audio_score(
                    name,
                    self.config.webcam_name_hint,
                )
            if needle and needle in lower:
                score += 1000
            elif needle and not self.config.prefer_webcam_audio:
                # Legacy behavior when webcam preference is explicitly disabled.
                score -= 1000

            if (
                self.config.preferred_handsfree
                and "hands-free" in lower
            ):
                score += 200
            if (
                self.config.preferred_samplerate
                and rate == int(self.config.preferred_samplerate)
            ):
                score += 100
            channels = int(dev.get("max_input_channels", 0))
            if channels >= 2:
                score += 80
            elif channels == 1:
                score += 10

            hostapi_index = dev.get("hostapi")
            hostapi_name = ""
            try:
                if hostapi_index is not None:
                    hostapi_name = str(
                        hostapis[int(hostapi_index)].get("name", "")
                    )
            except Exception:
                hostapi_name = ""

            score += _windows_hostapi_score(hostapi_name)

            item = dict(dev)
            item["_hostapi_name"] = hostapi_name
            ranked.append((score, idx, item))

        # Highest score first. For equal duplicates, newer/higher indexes first
        # because Windows commonly appends the current Bluetooth endpoint.
        ranked.sort(
            key=lambda row: (row[0], row[1]),
            reverse=True,
        )

        ordered: list[tuple[int, dict[str, Any]]] = []
        seen: set[int] = set()

        # A manually AV-bound webcam may stay first. A stale/legacy configured
        # headset index must not outrank webcam-primary mode merely because it
        # was persisted by an older release.
        deferred_configured: tuple[int, dict[str, Any]] | None = None
        exact_bound = self.config.preferred_device_index
        configured_source = exact_bound if exact_bound is not None else self.config.device
        if configured_source is not None:
            configured = int(configured_source)
            for _, idx, dev in ranked:
                if idx != configured:
                    continue
                fragile_host = _windows_hostapi_score(
                    str(dev.get("_hostapi_name", ""))
                ) <= -1000
                if (
                    not fragile_host
                    and (
                        not self.config.prefer_webcam_audio
                        or webcam_audio_score(
                            str(dev.get("name", "")),
                            self.config.webcam_name_hint,
                        ) >= 1200
                    )
                ):
                    ordered.append((idx, dev))
                    seen.add(idx)
                else:
                    deferred_configured = (idx, dev)
                break

        # Then probable webcam-integrated microphones. They outrank the old
        # headset preference when AV webcam-primary mode is enabled.
        if self.config.prefer_webcam_audio:
            for score, idx, dev in ranked:
                if idx in seen:
                    continue
                if webcam_audio_score(
                    str(dev.get("name", "")),
                    self.config.webcam_name_hint,
                ) >= 1200:
                    ordered.append((idx, dev))
                    seen.add(idx)

        # Then a legacy explicitly configured index, after webcam candidates.
        if deferred_configured is not None:
            idx, dev = deferred_configured
            if idx not in seen:
                ordered.append((idx, dev))
                seen.add(idx)

        # Then every legacy preferred-name candidate (for example JBL).
        if needle:
            for score, idx, dev in ranked:
                if idx in seen:
                    continue
                if needle in str(dev.get("name", "")).lower():
                    ordered.append((idx, dev))
                    seen.add(idx)

        # Then default input.
        try:
            default_index = int(sd.default.device[0])
        except Exception:
            default_index = -1

        if default_index >= 0 and default_index not in seen:
            for _, idx, dev in ranked:
                if idx == default_index:
                    ordered.append((idx, dev))
                    seen.add(idx)
                    break

        # Last-resort remaining inputs.
        for _, idx, dev in ranked:
            if idx not in seen:
                ordered.append((idx, dev))
                seen.add(idx)

        return ordered

    def _preferred_devices(self) -> list[tuple[int, dict[str, Any]]]:
        candidates = self._input_device_candidates()
        if self.config.prefer_webcam_audio:
            webcam = [
                (idx, dev)
                for idx, dev in candidates
                if webcam_audio_score(
                    str(dev.get("name", "")),
                    self.config.webcam_name_hint,
                ) >= 1200
            ]
            if webcam:
                return webcam
        needle = (self.config.preferred_device_name or "").strip().lower()
        return [
            (idx, dev)
            for idx, dev in candidates
            if not needle or needle in str(dev.get("name", "")).lower()
        ]

    def _preferred_device(self):
        candidates = self._preferred_devices()
        return candidates[0] if candidates else None

    def set_device(self, index: int | None) -> dict[str, Any]:
        if index is None:
            self.config.device = None
            self.config.preferred_device_index = None
            return {"ok": True, "device": None, "message": "Default input device selected."}

        devices = self.list_devices()
        match = next((x for x in devices if x["index"] == int(index)), None)
        if not match:
            return {"ok": False, "error": "INVALID_MIC_DEVICE", "device": index}
        self.config.device = int(index)
        self.config.preferred_device_index = int(index)
        return {"ok": True, "device": match}

    def list_devices(self) -> list[dict[str, Any]]:
        import sounddevice as sd

        devices = sd.query_devices()
        default_input = None
        try:
            default_input = int(sd.default.device[0])
        except Exception:
            pass

        try:
            hostapis = list(sd.query_hostapis())
        except Exception:
            hostapis = []

        result = []
        for idx, dev in enumerate(devices):
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue
            hostapi_name = ""
            try:
                api_index = dev.get("hostapi")
                if api_index is not None and hostapis:
                    hostapi_name = str(hostapis[int(api_index)].get("name", ""))
            except Exception:
                hostapi_name = ""
            result.append({
                "index": idx,
                "name": str(dev.get("name", f"Device {idx}")),
                "input_channels": int(dev.get("max_input_channels", 0)),
                "default_samplerate": int(float(dev.get("default_samplerate", 0) or 0)),
                "hostapi": hostapi_name,
                "is_default": idx == default_input,
                "is_selected": (
                    idx == int(self.config.preferred_device_index)
                    if self.config.preferred_device_index is not None
                    else idx == int(self.config.device)
                    if self.config.device is not None
                    else False
                ),
            })
        return result

    def _mark_verified_signal(self, index: int, max_rms: float) -> None:
        value = float(max_rms or 0.0)
        if value > 0.0:
            self._verified_signal[int(index)] = (value, monotonic())

    def _recent_verified_signal(self, index: int) -> tuple[float, float] | None:
        item = self._verified_signal.get(int(index))
        if item is None:
            return None
        value, seen_at = item
        age = monotonic() - float(seen_at)
        if age > float(self.config.verified_signal_ttl_seconds):
            self._verified_signal.pop(int(index), None)
            return None
        return float(value), float(age)

    @staticmethod
    def select_best_probe(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        live = [row for row in rows if row.get("ok")]
        if not live:
            return None
        def key(row: dict[str, Any]):
            return (
                1 if row.get("verified_recent") else 0,
                int(row.get("webcam_score", 0) or 0),
                float(row.get("effective_rms", row.get("max_rms", 0.0)) or 0.0),
                -int(row.get("candidate_position", 9999) or 9999),
            )
        return max(live, key=key)

    def probe_device_signal(
        self,
        index: int,
        seconds: float = 0.45,
    ) -> dict[str, Any]:
        """Open one input briefly and prove that it delivers non-zero PCM."""
        import sounddevice as sd

        devices = list(sd.query_devices())
        idx = int(index)
        if idx < 0 or idx >= len(devices):
            return {"ok": False, "error": "INVALID_MIC_DEVICE", "index": idx}
        dev = devices[idx]
        if int(dev.get("max_input_channels", 0)) <= 0:
            return {"ok": False, "error": "NOT_INPUT_DEVICE", "index": idx}

        samplerate = int(float(dev.get("default_samplerate", 0) or 0)) or 48000
        block_seconds = 0.10
        blocksize = max(256, int(samplerate * block_seconds))
        queue: Queue[bytes] = Queue()

        def callback(indata, frames, time_info, status):
            queue.put(bytes(indata))

        values: list[float] = []
        try:
            with sd.RawInputStream(
                samplerate=samplerate,
                blocksize=blocksize,
                device=idx,
                channels=1,
                dtype="int16",
                callback=callback,
            ):
                blocks = max(2, int(max(0.2, float(seconds)) / block_seconds))
                for _ in range(blocks):
                    try:
                        values.append(_rms_int16(queue.get(timeout=0.6)))
                    except Empty:
                        values.append(0.0)
        except Exception as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
                "index": idx,
                "name": str(dev.get("name", idx)),
            }

        max_rms = max(values) if values else 0.0
        avg_rms = sum(values) / len(values) if values else 0.0
        min_signal = max(float(self.config.no_signal_rms), float(self.config.probe_min_signal_rms))
        recent = self._recent_verified_signal(idx)
        verified_rms = recent[0] if recent is not None else 0.0
        effective_rms = max(max_rms, verified_rms)
        live = effective_rms >= min_signal
        if live and max_rms >= min_signal:
            signal_class = "live_signal"
            error = None
        elif live and recent is not None:
            signal_class = "recently_verified"
            error = None
        elif max_rms <= 1e-7:
            signal_class = "digital_silence"
            error = "MIC_STREAM_DIGITAL_SILENCE"
        else:
            signal_class = "near_silence"
            error = "MIC_STREAM_BELOW_USEFUL_SIGNAL"
        return {
            "ok": live,
            "error": error,
            "index": idx,
            "name": str(dev.get("name", idx)),
            "samplerate": samplerate,
            "max_rms": round(max_rms, 8),
            "avg_rms": round(avg_rms, 8),
            "effective_rms": round(effective_rms, 8),
            "min_signal_rms": round(min_signal, 8),
            "signal_class": signal_class,
            "verified_recent": recent is not None,
            "verified_recent_rms": round(verified_rms, 8) if recent is not None else None,
            "verified_age_seconds": round(recent[1], 2) if recent is not None else None,
        }

    def probe_devices(self, limit: int = 12) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for position, (idx, dev) in enumerate(
            self._input_device_candidates()[: max(1, int(limit))],
            start=1,
        ):
            probe = self.probe_device_signal(idx)
            probe["candidate_position"] = position
            probe["hostapi"] = str(dev.get("_hostapi_name", ""))
            probe["webcam_score"] = webcam_audio_score(
                str(dev.get("name", "")),
                self.config.webcam_name_hint,
            )
            rows.append(probe)
        return rows

    @staticmethod
    def _is_invalid_device_error(exc: Exception) -> bool:
        """
        PortAudio device indexes are ephemeral on Windows. Bluetooth reconnects,
        driver refreshes and reboots can renumber them.

        Treat -9996 / "Invalid device" as recoverable so the next attempt can
        resolve the JBL again by its preferred device name.
        """
        message = f"{type(exc).__name__}: {exc}".lower()
        return (
            "invalid device" in message
            or "paerrorcode -9996" in message
            or "errorcode -9996" in message
        )

    def _recover_stale_device_index(
        self,
        exc: Exception,
        attempt: int,
    ) -> bool:
        if not self._is_invalid_device_error(exc):
            return False

        stale_device = self.config.device
        self.config.device = None

        preferred = None
        try:
            preferred = self._preferred_device()
        except Exception:
            preferred = None

        self.events.emit(
            "MIC_DEVICE_RECOVERY",
            stale_device=stale_device,
            preferred_device=(
                int(preferred[0])
                if preferred is not None
                else None
            ),
            preferred_name=(
                str(preferred[1].get("name", ""))
                if preferred is not None
                else None
            ),
            attempt=attempt,
            error=f"{type(exc).__name__}: {exc}",
        )
        return True

    def capture_phrase(self) -> dict[str, Any]:
        """
        Capture one phrase without transcribing it.

        Bluetooth/Windows input endpoints can occasionally open successfully
        while returning only digital zeroes. Detect that state, close the
        stream, wait briefly and reopen automatically.
        """
        attempts = max(1, int(self.config.stream_retries) + 1)
        last_result = None

        for attempt in range(1, attempts + 1):
            try:
                result = self._capture_phrase()
            except Exception as exc:
                if (
                    self._recover_stale_device_index(exc, attempt)
                    and attempt < attempts
                ):
                    sleep(
                        max(
                            0.1,
                            float(self.config.stream_recovery_seconds),
                        )
                    )
                    continue

                self.events.emit(
                    "MIC_ERROR",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }

            if result.get("ok"):
                if attempt > 1:
                    result["stream_recovery_attempt"] = attempt
                return result

            last_result = result
            if result.get("error") != "MIC_STREAM_NO_SIGNAL":
                return result

            if attempt < attempts:
                self.events.emit(
                    "MIC_STREAM_RECOVERY",
                    attempt=attempt,
                    next_attempt=attempt + 1,
                    wait_seconds=self.config.stream_recovery_seconds,
                )
                sleep(max(0.1, float(self.config.stream_recovery_seconds)))

        return last_result or {
            "ok": False,
            "error": "MIC_STREAM_NO_SIGNAL",
            "message": "O microfone abriu mas não entregou sinal de áudio.",
        }

    def transcribe_file(self, wav_path: str | Path) -> dict[str, Any]:
        """Transcribe a WAV file captured earlier."""
        try:
            return self._transcribe(Path(wav_path))
        except Exception as exc:
            self.events.emit("MIC_ERROR", error=f"{type(exc).__name__}: {exc}")
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    def transcribe_wake_file(self, wav_path: str | Path) -> dict[str, Any]:
        """Cheap transcription used only to confirm an acoustic ``Jarvis`` hit.

        The acoustic matcher already narrowed the candidate.  Using the full
        command beam/retry profile here added seconds of latency and made every
        false candidate expensive.  This profile is intentionally beam-1 and
        never performs the command confidence retry.
        """
        try:
            return self._transcribe(Path(wav_path), profile="wake")
        except Exception as exc:
            self.events.emit("MIC_ERROR", error=f"{type(exc).__name__}: {exc}")
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    def transcribe_command_file(self, wav_path: str | Path) -> dict[str, Any]:
        """Higher-accuracy decode for a captured Always Listening command."""
        try:
            return self._transcribe(Path(wav_path), profile="command")
        except Exception as exc:
            self.events.emit("MIC_ERROR", error=f"{type(exc).__name__}: {exc}")
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    @staticmethod
    def cleanup_capture(wav_path: str | Path | None) -> None:
        if not wav_path:
            return
        try:
            Path(wav_path).unlink(missing_ok=True)
        except OSError:
            pass

    def status(self) -> dict[str, Any]:
        selected = None
        try:
            devices = self.list_devices()
            if self.config.device is not None:
                selected = next(
                    (
                        x
                        for x in devices
                        if x["index"] == self.config.device
                    ),
                    None,
                )

            if selected is None:
                preferred = self._preferred_device()
                if preferred is not None:
                    preferred_index = int(preferred[0])
                    selected = next(
                        (
                            x
                            for x in devices
                            if x["index"] == preferred_index
                        ),
                        None,
                    )

            if selected is None:
                selected = next(
                    (x for x in devices if x["is_default"]),
                    None,
                )
        except Exception as exc:
            return {
                "ok": False,
                "device": self.config.device,
                "model": self.config.model,
                "stt_device": self.config.stt_device,
                "model_backend": self._model_backend,
                "error": f"{type(exc).__name__}: {exc}",
            }

        return {
            "ok": True,
            "device": selected,
            "language": self.config.language,
            "model": self.config.model,
            "stt_device": self.config.stt_device,
            "model_backend": self._model_backend,
            "model_error": self._model_error,
        }

    def listen_and_transcribe(self) -> dict[str, Any]:
        try:
            capture = self.capture_phrase()
            if not capture.get("ok"):
                return capture

            wav_path = Path(capture["wav_path"])
            try:
                transcription = self._transcribe(wav_path)
                transcription["capture"] = {
                    k: v for k, v in capture.items() if k != "wav_path"
                }
                return transcription
            finally:
                try:
                    wav_path.unlink(missing_ok=True)
                except OSError:
                    pass

        except Exception as exc:
            self.events.emit("MIC_ERROR", error=f"{type(exc).__name__}: {exc}")
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

    def _selected_device_info(self):
        candidates = self._input_device_candidates()
        if not candidates:
            raise RuntimeError("NO_INPUT_DEVICE")
        return candidates[0]

    def _capture_phrase(self) -> dict[str, Any]:
        """
        Try the configured/JBL/default input endpoints until one actually opens.

        The important distinction from 0.9.1: query_devices() is not treated as
        proof that a Windows Bluetooth endpoint is usable. RawInputStream is the
        final authority.
        """
        candidates = self._input_device_candidates()
        if not candidates:
            raise RuntimeError("NO_INPUT_DEVICE")

        last_exc: Exception | None = None
        last_result: dict[str, Any] | None = None

        for position, (device_index, device_info) in enumerate(candidates, start=1):
            try:
                result = self._capture_phrase_on_device(
                    int(device_index),
                    device_info,
                )

                # Opening a PortAudio endpoint is not proof that Windows is
                # delivering audio. Some duplicate webcam endpoints open and
                # return only digital zeroes. Treat those as dead candidates
                # and continue through the remaining inputs.
                if result.get("error") == "MIC_STREAM_NO_SIGNAL":
                    self.events.emit(
                        "MIC_DEVICE_CANDIDATE_SILENT",
                        device=int(device_index),
                        device_name=str(device_info.get("name", device_index)),
                        hostapi=str(device_info.get("_hostapi_name", "")),
                        candidate_position=position,
                        max_rms=float(result.get("max_rms", 0.0) or 0.0),
                    )
                    last_result = dict(result)
                    last_result["device_fallback_position"] = position
                    continue

                # A successful speech capture is proof that this exact Windows
                # endpoint works. Keep short-lived evidence so a later passive
                # /av probe does not demote a noise-gated webcam merely because
                # the owner happened to be silent during that short probe.
                if result.get("ok"):
                    self._mark_verified_signal(
                        int(device_index),
                        float(result.get("max_rms", 0.0) or 0.0),
                    )
                self.config.device = int(device_index)

                if position > 1:
                    result["device_fallback_position"] = position
                    self.events.emit(
                        "MIC_DEVICE_SELECTED",
                        device=int(device_index),
                        device_name=str(
                            device_info.get("name", device_index)
                        ),
                        hostapi=str(
                            device_info.get("_hostapi_name", "")
                        ),
                        fallback_position=position,
                    )
                return result
            except Exception as exc:
                last_exc = exc

                if self._is_invalid_device_error(exc) or (
                    "unanticipated host error" in str(exc).lower()
                    and "paerrorcode -9999" in str(exc).lower()
                ):
                    self.events.emit(
                        "MIC_DEVICE_CANDIDATE_FAILED",
                        device=int(device_index),
                        device_name=str(
                            device_info.get("name", device_index)
                        ),
                        hostapi=str(
                            device_info.get("_hostapi_name", "")
                        ),
                        candidate_position=position,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    continue

                # For device-open class failures, also try the next duplicate
                # endpoint. For errors after a stream has successfully opened,
                # do not silently switch microphones.
                msg = str(exc).lower()
                if (
                    "error opening rawinputstream" in msg
                    or "error querying device" in msg
                ):
                    self.events.emit(
                        "MIC_DEVICE_CANDIDATE_FAILED",
                        device=int(device_index),
                        device_name=str(
                            device_info.get("name", device_index)
                        ),
                        hostapi=str(
                            device_info.get("_hostapi_name", "")
                        ),
                        candidate_position=position,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    continue
                raise

        if last_result is not None:
            last_result["all_input_candidates_silent"] = True
            return last_result
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("NO_OPENABLE_INPUT_DEVICE")

    def _capture_phrase_on_device(
        self,
        device_index: int,
        device_info: dict[str, Any],
    ) -> dict[str, Any]:
        import sounddevice as sd

        samplerate = int(float(device_info["default_samplerate"]))
        if samplerate <= 0:
            samplerate = 48000

        block_seconds = 0.1
        blocksize = max(256, int(samplerate * block_seconds))
        audio_queue: Queue[bytes] = Queue()

        def callback(indata, frames, time_info, status):
            if status:
                self.events.emit("MIC_STREAM_STATUS", status=str(status))
            audio_queue.put(bytes(indata))

        self.events.emit(
            "LISTENING_STARTED",
            device=device_index,
            device_name=str(device_info.get("name", device_index)),
            samplerate=samplerate,
        )

        cache_key = (device_index, samplerate)
        cached = self._threshold_cache.get(cache_key)
        cache_valid = bool(
            cached
            and (monotonic() - cached[1]) <= float(self.config.calibration_cache_seconds)
        )
        calibration_blocks = (
            max(1, int(self.config.cached_calibration_blocks))
            if cache_valid
            else max(1, int(self.config.calibration_seconds / block_seconds))
        )
        pre_roll = deque(maxlen=max(2, int(0.35 / block_seconds)))
        noise_values: list[float] = []
        calibration_audio: list[tuple[bytes, float]] = []
        frames: list[bytes] = []
        speech_started = False
        max_observed_rms = 0.0
        speech_started_at = None
        silent_for = 0.0
        speech_peak_rms = 0.0
        trailing_threshold = 0.0
        started_at = monotonic()

        with sd.RawInputStream(
            samplerate=samplerate,
            blocksize=blocksize,
            device=device_index,
            channels=1,
            dtype="int16",
            callback=callback,
        ):
            # Calibration.
            for _ in range(calibration_blocks):
                try:
                    block = audio_queue.get(timeout=1.0)
                except Empty:
                    continue
                block_rms = _rms_int16(block)
                noise_values.append(block_rms)
                calibration_audio.append((block, block_rms))
                max_observed_rms = max(max_observed_rms, block_rms)

            raw_noise_mean = (
                sum(noise_values) / len(noise_values) if noise_values else 0.0
            )
            noise_rms = robust_noise_floor(noise_values)

            if cache_valid and cached:
                threshold = float(cached[0])
                self.events.emit(
                    "MIC_CALIBRATION_CACHED",
                    device=device_index,
                    threshold=round(threshold, 5),
                    age_seconds=round(monotonic() - cached[1], 2),
                )
            else:
                threshold = adaptive_threshold(
                    noise_rms,
                    multiplier=self.config.threshold_multiplier,
                    floor=self.config.threshold_floor,
                )
                self.events.emit(
                    "MIC_CALIBRATED",
                    noise_rms=round(noise_rms, 5),
                    raw_noise_mean=round(raw_noise_mean, 5),
                    threshold=round(threshold, 5),
                )

            # Do not throw away speech that starts while a newly-opened WASAPI
            # stream is calibrating. This was especially visible after the
            # wake acknowledgement: short commands such as "Spotify" could
            # begin inside the first 100-400 ms and lose their onset. Replay
            # only calibration audio that looked speech-like (plus a tiny
            # pre-roll), so ordinary room noise is not promoted to a command.
            startup_blocks: deque[bytes] = deque()
            for idx, (cal_block, cal_rms) in enumerate(calibration_audio):
                if cal_rms >= max(float(threshold) * 0.85, 0.0045):
                    begin = max(0, idx - 2)
                    startup_blocks.extend(row[0] for row in calibration_audio[begin:])
                    self.events.emit(
                        "MIC_STARTUP_SPEECH_RECOVERED",
                        blocks=len(startup_blocks),
                        peak_rms=round(max(r for _, r in calibration_audio[begin:]), 5),
                        threshold=round(float(threshold), 5),
                    )
                    break

            while True:
                now = monotonic()
                total_elapsed = now - started_at

                if not speech_started and total_elapsed > (
                    self.config.calibration_seconds + self.config.start_timeout_seconds
                ):
                    if max_observed_rms <= float(self.config.no_signal_rms):
                        self._threshold_cache.pop(cache_key, None)
                        self.events.emit(
                            "MIC_STREAM_NO_SIGNAL",
                            max_rms=round(max_observed_rms, 6),
                            device=device_index,
                        )
                        return {
                            "ok": False,
                            "error": "MIC_STREAM_NO_SIGNAL",
                            "message": (
                                "O dispositivo abriu, mas o Windows entregou "
                                "apenas silêncio digital. Vou tentar reabrir."
                            ),
                            "threshold": threshold,
                            "max_rms": max_observed_rms,
                        }

                    self.events.emit(
                        "LISTENING_TIMEOUT",
                        max_rms=round(max_observed_rms, 5),
                    )
                    return {
                        "ok": False,
                        "error": "NO_SPEECH_DETECTED",
                        "message": "Não detetei voz antes do tempo limite.",
                        "threshold": threshold,
                        "max_rms": max_observed_rms,
                    }

                if startup_blocks:
                    block = startup_blocks.popleft()
                else:
                    try:
                        block = audio_queue.get(timeout=0.5)
                    except Empty:
                        continue

                rms = _rms_int16(block)
                max_observed_rms = max(max_observed_rms, rms)

                if not speech_started:
                    pre_roll.append(block)
                    if rms >= threshold:
                        speech_started = True
                        speech_started_at = monotonic()
                        frames.extend(pre_roll)
                        pre_roll.clear()
                        speech_peak_rms = max(speech_peak_rms, rms)
                        trailing_threshold = max(
                            float(threshold) * 1.35,
                            min(0.035, speech_peak_rms * 0.16),
                        )
                        silent_for = 0.0
                        self.events.emit(
                            "SPEECH_DETECTED",
                            rms=round(rms, 5),
                            trailing_threshold=round(trailing_threshold, 5),
                        )
                    continue

                frames.append(block)
                phrase_elapsed = monotonic() - float(speech_started_at)

                speech_peak_rms = max(speech_peak_rms, rms)
                trailing_threshold = max(
                    float(threshold) * 1.35,
                    min(0.035, speech_peak_rms * 0.16),
                )
                if rms < trailing_threshold:
                    silent_for += block_seconds
                else:
                    silent_for = 0.0

                if (
                    phrase_elapsed >= self.config.min_phrase_seconds
                    and silent_for >= self.config.silence_seconds
                ):
                    break

                if phrase_elapsed >= self.config.max_phrase_seconds:
                    self.events.emit("LISTENING_MAX_DURATION")
                    break

        if not frames:
            return {
                "ok": False,
                "error": "EMPTY_AUDIO",
                "message": "Não foi capturado áudio utilizável.",
            }

        wav_path = Path(gettempdir()) / f"jarvis_mic_{uuid4().hex}.wav"
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(b"".join(frames))

        duration = len(frames) * block_seconds
        self._threshold_cache[cache_key] = (float(threshold), monotonic())
        self.events.emit(
            "AUDIO_CAPTURED",
            seconds=round(duration, 2),
            samplerate=samplerate,
        )
        return {
            "ok": True,
            "wav_path": str(wav_path),
            "duration_seconds": round(duration, 2),
            "samplerate": samplerate,
            "device": device_index,
            "device_name": str(device_info.get("name", device_index)),
            "noise_rms": round(noise_rms, 5),
            "threshold": round(threshold, 5),
            "max_rms": round(max_observed_rms, 6),
            "trailing_threshold": round(trailing_threshold, 5),
        }

    def _load_model(self):
        if self._model is not None:
            return self._model

        with self._model_lock:
            if self._model is not None:
                return self._model

            WhisperModel = load_whisper_model_class()

            requested = self.config.stt_device.lower().strip()
            attempts = []

            if requested in {"auto", "cuda"}:
                attempts.append(("cuda", "float16"))
            if requested in {"auto", "cpu"}:
                attempts.append(("cpu", "int8"))

            last_error = None
            for device, compute_type in attempts:
                self.events.emit(
                    "STT_MODEL_LOADING",
                    model=self.config.model,
                    device=device,
                    compute_type=compute_type,
                )
                try:
                    kwargs = {
                        "device": device,
                        "compute_type": compute_type,
                    }
                    download_root = str(self.config.download_root or "").strip()
                    if download_root:
                        Path(download_root).mkdir(parents=True, exist_ok=True)
                        kwargs["download_root"] = download_root
                    if device == "cpu":
                        kwargs["cpu_threads"] = max(1, int(self.config.cpu_threads))

                    model = WhisperModel(self.config.model, **kwargs)
                    self._model = model
                    self._model_backend = f"{device}/{compute_type}"
                    self._model_error = None
                    self.events.emit(
                        "STT_MODEL_READY",
                        model=self.config.model,
                        backend=self._model_backend,
                    )
                    return model
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
                    self.events.emit(
                        "STT_BACKEND_FAILED",
                        device=device,
                        error=last_error,
                    )
                    if requested == device:
                        break

            self._model_error = last_error
            raise RuntimeError(
                "Não consegui carregar o modelo de reconhecimento de voz. "
                f"Último erro: {last_error}"
            )

    def _transcribe_kwargs(self, model, profile: str) -> dict[str, Any]:
        """
        Build decode arguments defensively across faster-whisper versions.
        Optional prompt/hotword parameters are passed only if supported.
        """
        import inspect

        profile_name = str(profile).lower().strip()
        command_profile = profile_name == "command"
        wake_profile = profile_name == "wake"
        selected_beam = 1 if (command_profile or wake_profile) else self.config.beam_size
        kwargs: dict[str, Any] = {
            "language": self.config.language,
            "beam_size": max(1, int(selected_beam)),
            # 0.26.2: use Whisper/Silero VAD for command audio as well.  The
            # capture-side energy gate decides when to record; this second VAD
            # removes room noise and long webcam tails before decoding.
            "vad_filter": bool(wake_profile or command_profile),
            "condition_on_previous_text": False,
            "temperature": 0.0,
            "without_timestamps": True,
        }

        try:
            supported = set(inspect.signature(model.transcribe).parameters)
        except Exception:
            supported = set(kwargs)

        if (wake_profile or command_profile) and "vad_parameters" in supported:
            kwargs["vad_parameters"] = {
                "min_silence_duration_ms": 120 if wake_profile else 280,
                "speech_pad_ms": 80 if wake_profile else 140,
            }

        if command_profile:
            prompt = str(self.config.command_initial_prompt or "").strip()
            hotwords = str(self.config.command_hotwords or "").strip()
            if prompt and "initial_prompt" in supported:
                kwargs["initial_prompt"] = prompt
            if hotwords and "hotwords" in supported:
                kwargs["hotwords"] = hotwords
        elif wake_profile:
            prompt = str(self.config.wake_candidate_initial_prompt or "").strip()
            hotwords = str(self.config.wake_candidate_hotwords or "").strip()
            if prompt and "initial_prompt" in supported:
                kwargs["initial_prompt"] = prompt
            if hotwords and "hotwords" in supported:
                kwargs["hotwords"] = hotwords

        return {key: value for key, value in kwargs.items() if key in supported}

    def _condition_audio(self, audio, *, profile: str) -> tuple[Any, dict[str, Any]]:
        """Gentle speech conditioning for distant/webcam microphones.

        This is intentionally conservative: remove DC offset and raise quiet
        speech toward a stable RMS target without clipping. It never performs
        destructive noise gating, which could remove Portuguese consonants.
        """
        import numpy as np

        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        meta = {
            "conditioned": False,
            "input_rms": 0.0,
            "output_rms": 0.0,
            "gain": 1.0,
        }
        if samples.size == 0:
            return samples, meta

        samples = samples - float(np.mean(samples))
        input_rms = float(np.sqrt(np.mean(samples * samples)))
        meta["input_rms"] = round(input_rms, 6)
        meta["trimmed"] = False
        meta["trimmed_seconds"] = 0.0

        # The command capture intentionally waits for a silence tail so it does
        # not cut the OWNER off. Whisper should not pay inference time for that
        # tail. Trim only clear leading/trailing low-energy regions and keep a
        # generous pad to preserve Portuguese plosives/consonants.
        if (
            str(profile).lower().strip() == "command"
            and bool(self.config.command_trim_silence)
            and samples.size >= 1600
        ):
            frame = 320  # 20 ms at the fixed 16 kHz Whisper PCM rate
            hop = 160
            rms_rows = []
            starts = []
            for start in range(0, max(1, samples.size - frame + 1), hop):
                chunk = samples[start:start + frame]
                if chunk.size < frame // 2:
                    break
                rms_rows.append(float(np.sqrt(np.mean(chunk * chunk))))
                starts.append(start)
            if rms_rows:
                rows = np.asarray(rms_rows, dtype=np.float32)
                peak_rms = float(np.max(rows))
                noise_rms = float(np.percentile(rows, 25))
                trim_threshold = max(
                    float(self.config.command_trim_floor_rms),
                    noise_rms * 2.2,
                    peak_rms * 0.07,
                )
                active = np.flatnonzero(rows >= trim_threshold)
                if active.size:
                    pad = int(round(max(0, int(self.config.command_trim_padding_ms)) * 16.0))
                    first = max(0, starts[int(active[0])] - pad)
                    last_start = starts[int(active[-1])]
                    last = min(samples.size, last_start + frame + pad)
                    if last - first >= int(0.20 * 16000):
                        original_size = int(samples.size)
                        if first > 0 or last < original_size:
                            samples = samples[first:last]
                            removed = original_size - int(samples.size)
                            meta["trimmed"] = True
                            meta["trimmed_seconds"] = round(removed / 16000.0, 3)

        if str(profile).lower().strip() in {"command", "wake"} and self.config.normalize_command_audio:
            target = max(0.01, float(self.config.command_target_rms))
            max_gain = max(1.0, float(self.config.command_max_gain))
            if input_rms > 1e-6 and input_rms < target:
                gain = min(max_gain, target / input_rms)
                samples = samples * float(gain)
                meta["gain"] = round(float(gain), 3)
            peak = float(np.max(np.abs(samples))) if samples.size else 0.0
            if peak > 0.98:
                limiter = 0.98 / peak
                samples = samples * float(limiter)
                meta["gain"] = round(float(meta["gain"]) * limiter, 3)
            meta["conditioned"] = True

        output_rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
        meta["output_rms"] = round(output_rms, 6)
        return np.ascontiguousarray(samples, dtype=np.float32), meta

    @staticmethod
    def _segment_quality(segments) -> dict[str, Any]:
        logprobs = []
        no_speech = []
        for seg in segments:
            value = getattr(seg, "avg_logprob", None)
            if value is not None:
                try:
                    logprobs.append(float(value))
                except Exception:
                    pass
            value = getattr(seg, "no_speech_prob", None)
            if value is not None:
                try:
                    no_speech.append(float(value))
                except Exception:
                    pass
        return {
            "avg_logprob": (sum(logprobs) / len(logprobs)) if logprobs else None,
            "max_no_speech_prob": max(no_speech) if no_speech else None,
        }

    def _run_transcription(
        self,
        model,
        wav_path: Path,
        *,
        profile: str = "default",
        beam_override: int | None = None,
    ):
        # Important for Windows Smart App Control compatibility: do not pass a
        # file path to faster-whisper. A path makes faster-whisper call PyAV,
        # whose unsigned native modules can be blocked by the
        # VerifiedAndReputableDesktop policy. Decode JARVIS PCM WAV locally and
        # pass the already-decoded 16 kHz float32 waveform instead.
        audio, audio_meta = load_wav_pcm_float32(wav_path)
        audio, conditioning = self._condition_audio(audio, profile=profile)
        audio_meta.update(conditioning)
        kwargs = self._transcribe_kwargs(model, profile)
        if beam_override is not None and "beam_size" in kwargs:
            kwargs["beam_size"] = max(1, int(beam_override))
        segments, info = model.transcribe(audio, **kwargs)
        segments = list(segments)
        spoken_text = " ".join(
            seg.text.strip() for seg in segments if seg.text.strip()
        ).strip()
        quality = self._segment_quality(segments)
        return spoken_text, info, kwargs, audio_meta, quality

    def _force_cpu_model(self):
        WhisperModel = load_whisper_model_class()

        self.events.emit(
            "STT_RUNTIME_FALLBACK",
            from_backend=self._model_backend,
            to_backend="cpu/int8",
        )

        self._model = None
        gc.collect()

        download_root = str(self.config.download_root or "").strip()
        if download_root:
            Path(download_root).mkdir(parents=True, exist_ok=True)
        model = WhisperModel(
            self.config.model,
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, int(self.config.cpu_threads)),
            **({"download_root": download_root} if download_root else {}),
        )
        self._model = model
        self._model_backend = "cpu/int8"
        self._model_error = None

        self.events.emit(
            "STT_MODEL_READY",
            model=self.config.model,
            backend=self._model_backend,
        )
        return model

    @staticmethod
    def _looks_like_cuda_runtime_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        markers = (
            "cublas",
            "cudnn",
            "cuda",
            "cudart",
            "cannot be loaded",
            "dll is not found",
        )
        return any(marker in msg for marker in markers)

    @staticmethod
    def _normalize_command_text(text: str) -> tuple[str, bool]:
        """Conservative PT-PT repair for recurrent first-verb ASR slips."""
        import re
        value = str(text or "").strip()
        if not value:
            return value, False
        # Only touch the command verb at the start (optionally after Jarvis).
        # Observed webcam/Whisper slip: "Jarvis, avie o Brave" -> "abre".
        pattern = re.compile(r'^(?P<prefix>\s*jarvis\s*[,;:-]?\s*)?(?P<verb>avie)(?=\s+(?:o|a|um|uma|brave|spotify|steam|discord)\b)', re.I)
        repaired = pattern.sub(lambda m: (m.group('prefix') or '') + 'abre', value, count=1)
        return repaired, repaired != value

    @staticmethod
    def _meaningful_transcript(text: str) -> bool:
        """Reject punctuation-only/noise hallucinations as speech.

        Whisper can emit strings such as ``. . . . .`` for room noise.  Such
        output is non-empty but must not be treated as a valid command.
        ``str.isalnum`` is Unicode-aware, so Portuguese text remains valid.
        """
        return any(ch.isalnum() for ch in str(text or ""))

    def _transcribe(
        self,
        wav_path: Path,
        *,
        profile: str = "default",
    ) -> dict[str, Any]:
        started = monotonic()
        self.events.emit(
            "TRANSCRIPTION_STARTED",
            file=str(wav_path),
            profile=profile,
        )
        model = self._load_model()
        fallback_used = False
        decode_kwargs = {}
        audio_meta: dict[str, Any] = {}
        quality: dict[str, Any] = {}
        retry_used = False

        try:
            spoken_text, info, decode_kwargs, audio_meta, quality = self._run_transcription(
                model,
                wav_path,
                profile=profile,
            )
        except Exception as exc:
            can_fallback = (
                self.config.stt_device.lower().strip() == "auto"
                and self._model_backend is not None
                and self._model_backend.startswith("cuda/")
                and self._looks_like_cuda_runtime_error(exc)
            )

            if not can_fallback:
                raise

            self.events.emit(
                "STT_BACKEND_FAILED",
                device="cuda",
                error=f"{type(exc).__name__}: {exc}",
                phase="transcription",
            )

            model = self._force_cpu_model()
            fallback_used = True
            spoken_text, info, decode_kwargs, audio_meta, quality = self._run_transcription(
                model,
                wav_path,
                profile=profile,
            )
        # Voice Reset: exactly one Faster-Whisper decode per utterance.
        raw_spoken_text = spoken_text
        command_normalized = False
        if str(profile).lower().strip() == "command" and spoken_text:
            spoken_text, command_normalized = self._normalize_command_text(spoken_text)
        meaningful_text = self._meaningful_transcript(spoken_text)
        quality_rejected = False
        quality_reject_reason = None
        avg_logprob = quality.get("avg_logprob")
        no_speech_prob = quality.get("max_no_speech_prob")

        result = {
            "ok": bool(meaningful_text),
            "text": spoken_text,
            "raw_text": raw_spoken_text if command_normalized else None,
            "command_text_normalized": command_normalized,
            "language": getattr(info, "language", self.config.language),
            "language_probability": round(
                float(getattr(info, "language_probability", 0.0) or 0.0), 4
            ),
            "backend": self._model_backend,
            "profile": profile,
            "beam_size": decode_kwargs.get("beam_size"),
            "initial_prompt_used": "initial_prompt" in decode_kwargs,
            "hotwords_used": "hotwords" in decode_kwargs,
            "fallback_used": fallback_used,
            "audio_input": "pcm_numpy",
            "audio_source_rate": audio_meta.get("source_rate"),
            "audio_target_rate": audio_meta.get("target_rate"),
            "audio_resampled": bool(audio_meta.get("resampled")),
            "audio_conditioned": bool(audio_meta.get("conditioned")),
            "audio_input_rms": audio_meta.get("input_rms"),
            "audio_output_rms": audio_meta.get("output_rms"),
            "audio_gain": audio_meta.get("gain"),
            "audio_trimmed": bool(audio_meta.get("trimmed")),
            "audio_trimmed_seconds": audio_meta.get("trimmed_seconds"),
            "avg_logprob": (round(float(quality["avg_logprob"]), 4) if quality.get("avg_logprob") is not None else None),
            "max_no_speech_prob": (round(float(quality["max_no_speech_prob"]), 4) if quality.get("max_no_speech_prob") is not None else None),
            "accuracy_retry_used": retry_used,
            "quality_rejected": quality_rejected,
            "quality_reject_reason": quality_reject_reason,
            "elapsed_ms": round((monotonic() - started) * 1000),
        }

        if not meaningful_text:
            result.update({
                "error": (
                    "LOW_CONFIDENCE_TRANSCRIPTION"
                    if quality_rejected
                    else "NON_SPEECH_TRANSCRIPTION" if spoken_text else "EMPTY_TRANSCRIPTION"
                ),
                "message": (
                    "A transcrição foi rejeitada por baixa confiança; não vou executar este áudio como comando."
                    if quality_rejected
                    else "O áudio parece conter ruído/silêncio, não uma frase reconhecível."
                    if spoken_text
                    else "O áudio foi capturado, mas não obtive uma transcrição."
                ),
            })

        self.events.emit(
            "TRANSCRIPTION_FINISHED",
            ok=bool(meaningful_text),
            chars=len(spoken_text),
            backend=self._model_backend,
            profile=profile,
            beam_size=result.get("beam_size"),
            initial_prompt_used=result.get("initial_prompt_used"),
            hotwords_used=result.get("hotwords_used"),
            fallback_used=fallback_used,
            elapsed_ms=result["elapsed_ms"],
        )
        return result
