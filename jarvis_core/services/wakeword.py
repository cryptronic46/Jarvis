from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable
from uuid import uuid4
from tempfile import gettempdir
import math
import wave

import numpy as np

from jarvis_core.services.av_devices import webcam_audio_score


@dataclass(slots=True)
class WakeWordConfig:
    enabled: bool = True
    auto_start: bool = True
    keyword: str = "JARVIS"

    # Microphone / speech onset.
    calibration_seconds: float = 0.8
    threshold_multiplier: float = 2.0
    threshold_floor: float = 0.006
    threshold_ceiling: float = 0.040
    block_seconds: float = 0.10
    speech_confirm_blocks: int = 2
    pre_roll_seconds: float = 0.30
    no_signal_rms: float = 0.00015

    # Acoustic wake matching. No Whisper here.
    enrollment_samples: int = 5
    template_path: str = "voice_profiles/wake_jarvis.npz"
    interrupt_template_path: str = "voice_profiles/interrupt_calate.npz"
    interrupt_enrollment_samples: int = 3
    interrupt_match_floor: float = 0.66
    feature_sample_rate: int = 16000
    feature_frame_ms: float = 25.0
    feature_hop_ms: float = 10.0
    feature_bands: int = 24
    probe_min_seconds: float = 0.35
    probe_max_seconds: float = 1.40
    wake_match_floor: float = 0.72
    wake_match_margin: float = 0.08
    wake_start_slack_seconds: float = 0.18
    candidate_whisper_confirm: bool = True
    candidate_reject_cooldown_seconds: float = 0.80
    # Independent Whisper confirmation guard. Candidate audio is isolated
    # around the acoustic match and must look like the keyword itself, not a
    # prompted hallucination inside arbitrary speech.
    candidate_window_seconds: float = 1.05
    candidate_tail_seconds: float = 0.06
    candidate_min_avg_logprob: float = -0.55
    candidate_max_no_speech_prob: float = 0.20
    candidate_max_words: int = 2

    # After wake: capture the command from the SAME open JBL stream.
    command_start_timeout_seconds: float = 5.0
    command_silence_seconds: float = 1.00
    command_max_seconds: float = 12.0
    command_min_seconds: float = 0.25
    command_preroll_seconds: float = 0.42
    command_threshold_ratio: float = 0.65

    preferred_device_index: int | None = None
    preferred_device_name: str = "GENERAL WEBCAM"
    preferred_handsfree: bool = False
    preferred_samplerate: int = 48000
    prefer_webcam_audio: bool = True
    webcam_name_hint: str = ""

    # TTS self-trigger suppression while keeping the same stream open.
    tts_tail_seconds: float = 0.35
    rearm_seconds: float = 0.20


def _rms(samples: np.ndarray) -> float:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(values * values)))


def _int16_to_float(raw: bytes) -> np.ndarray:
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if samples.size:
        samples /= 32768.0
    return samples.reshape(-1)


def _robust_noise_floor(values: list[float]) -> float:
    if not values:
        return 0.0
    cleaned = sorted(float(v) for v in values if v >= 0.0)
    quiet = cleaned[: max(1, (len(cleaned) + 1) // 2)]
    return float(np.median(np.asarray(quiet, dtype=np.float32)))


def _windows_capture_hostapi_score(name: str) -> int:
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


def _resample_linear(
    samples: np.ndarray,
    source_rate: int,
    target_rate: int,
) -> np.ndarray:
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0 or source_rate <= 0 or target_rate <= 0:
        return values
    if int(source_rate) == int(target_rate):
        return values

    target_size = max(
        1,
        int(round(values.size * float(target_rate) / float(source_rate))),
    )
    old_x = np.linspace(0.0, 1.0, num=values.size, endpoint=False)
    new_x = np.linspace(0.0, 1.0, num=target_size, endpoint=False)
    return np.interp(new_x, old_x, values).astype(np.float32)


def _trim_voice(
    samples: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    """
    Trim leading/trailing low-energy padding from enrollment recordings.
    Pure NumPy; no external scientific signal-processing package.
    """
    values = np.asarray(samples, dtype=np.float32).reshape(-1)
    if values.size == 0:
        return values

    frame = max(1, int(sample_rate * 0.020))
    hop = max(1, int(sample_rate * 0.010))
    rms_values = []
    positions = []

    for start in range(0, max(1, values.size - frame + 1), hop):
        chunk = values[start:start + frame]
        if chunk.size < frame // 2:
            break
        rms_values.append(_rms(chunk))
        positions.append(start)

    if not rms_values:
        return values

    peak = max(rms_values)
    threshold = max(0.004, peak * 0.14)
    active = [
        i for i, value in enumerate(rms_values)
        if value >= threshold
    ]
    if not active:
        return values

    pad = int(sample_rate * 0.08)
    start_sample = max(0, positions[active[0]] - pad)
    end_sample = min(
        values.size,
        positions[active[-1]] + frame + pad,
    )
    return values[start_sample:end_sample]


def _band_edges(
    fft_bins: int,
    sample_rate: int,
    bands: int,
    f_min: float = 180.0,
    f_max: float = 4200.0,
) -> list[tuple[int, int]]:
    nyquist = sample_rate / 2.0
    f_max = min(float(f_max), nyquist * 0.95)
    freqs = np.linspace(f_min, f_max, bands + 1)
    hz_per_bin = nyquist / max(1, fft_bins - 1)

    edges = []
    for i in range(bands):
        left = max(0, int(math.floor(freqs[i] / hz_per_bin)))
        right = max(left + 1, int(math.ceil(freqs[i + 1] / hz_per_bin)))
        right = min(fft_bins, right)
        edges.append((left, right))
    return edges


def acoustic_features(
    samples: np.ndarray,
    source_rate: int,
    config: WakeWordConfig,
    *,
    trim: bool,
) -> np.ndarray:
    """
    Small spectral fingerprint for the word "Jarvis".

    The feature matrix contains log spectral-band energies plus a few
    time-domain descriptors. It intentionally depends only on NumPy.
    """
    target_rate = int(config.feature_sample_rate)
    values = _resample_linear(samples, source_rate, target_rate)
    if trim:
        values = _trim_voice(values, target_rate)

    if values.size == 0:
        return np.zeros((0, int(config.feature_bands) + 3), dtype=np.float32)

    values = values - float(np.mean(values))
    peak = float(np.max(np.abs(values))) if values.size else 0.0
    if peak > 1e-6:
        values = values / peak

    frame_size = max(
        64,
        int(round(target_rate * float(config.feature_frame_ms) / 1000.0)),
    )
    hop_size = max(
        32,
        int(round(target_rate * float(config.feature_hop_ms) / 1000.0)),
    )
    n_fft = 1
    while n_fft < frame_size:
        n_fft *= 2

    if values.size < frame_size:
        values = np.pad(values, (0, frame_size - values.size))

    window = np.hanning(frame_size).astype(np.float32)
    fft_bins = n_fft // 2 + 1
    edges = _band_edges(
        fft_bins,
        target_rate,
        int(config.feature_bands),
    )

    rows = []
    for start in range(0, values.size - frame_size + 1, hop_size):
        frame = values[start:start + frame_size].astype(np.float32)
        frame_windowed = frame * window
        spectrum = np.abs(
            np.fft.rfft(frame_windowed, n=n_fft)
        ).astype(np.float32)
        power = spectrum * spectrum

        band_values = []
        for left, right in edges:
            energy = float(np.mean(power[left:right])) if right > left else 0.0
            band_values.append(math.log1p(energy * 1000.0))

        rms_value = _rms(frame)
        zero_cross = float(
            np.mean(np.abs(np.diff(np.signbit(frame))).astype(np.float32))
        ) if frame.size > 1 else 0.0

        freqs = np.linspace(0.0, target_rate / 2.0, num=power.size)
        denom = float(np.sum(power)) + 1e-9
        centroid = float(np.sum(freqs * power) / denom) / (target_rate / 2.0)

        rows.append(
            band_values
            + [
                math.log1p(rms_value * 100.0),
                zero_cross,
                centroid,
            ]
        )

    matrix = np.asarray(rows, dtype=np.float32)
    if matrix.size == 0:
        return matrix

    # Per-feature normalization makes matching less sensitive to volume/headset
    # gain and more sensitive to the shape of the spoken word.
    mean = np.mean(matrix, axis=0, keepdims=True)
    std = np.std(matrix, axis=0, keepdims=True)
    matrix = (matrix - mean) / np.maximum(std, 0.15)
    return np.clip(matrix, -4.0, 4.0).astype(np.float32)


def _resample_feature_time(
    matrix: np.ndarray,
    target_frames: int,
) -> np.ndarray:
    source = np.asarray(matrix, dtype=np.float32)
    if source.ndim != 2 or source.shape[0] == 0:
        return np.zeros(
            (max(1, target_frames), source.shape[1] if source.ndim == 2 else 1),
            dtype=np.float32,
        )
    if source.shape[0] == target_frames:
        return source

    old_x = np.linspace(0.0, 1.0, num=source.shape[0])
    new_x = np.linspace(0.0, 1.0, num=target_frames)
    result = np.empty((target_frames, source.shape[1]), dtype=np.float32)
    for col in range(source.shape[1]):
        result[:, col] = np.interp(new_x, old_x, source[:, col])
    return result


def feature_similarity(
    template: np.ndarray,
    candidate: np.ndarray,
) -> float:
    """
    Time-normalized cosine similarity mapped to [0, 1].
    """
    t = np.asarray(template, dtype=np.float32)
    c = np.asarray(candidate, dtype=np.float32)
    if t.ndim != 2 or c.ndim != 2:
        return 0.0
    if t.shape[0] < 4 or c.shape[0] < 4 or t.shape[1] != c.shape[1]:
        return 0.0

    c = _resample_feature_time(c, t.shape[0])
    t_flat = t.reshape(-1)
    c_flat = c.reshape(-1)

    denom = float(np.linalg.norm(t_flat) * np.linalg.norm(c_flat))
    if denom <= 1e-9:
        return 0.0

    cosine = float(np.dot(t_flat, c_flat) / denom)
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


class WakeWordService:
    """
    True two-stage wake architecture.

    Stage 1 (always on):
        JBL -> RMS -> local NumPy acoustic "Jarvis" matcher.
        Whisper is NOT called.

    Stage 2 (only after wake match):
        same JBL stream -> capture command -> Faster Whisper ONCE -> router.
    """

    def __init__(
        self,
        events,
        config: WakeWordConfig,
        on_wake: Callable[[str | None], None],
        transcribe_callback: Callable[[str | Path], dict[str, Any]],
        wake_transcribe_callback: Callable[[str | Path], dict[str, Any]] | None = None,
        on_interrupt: Callable[[], None] | None = None,
        on_interrupt_probe_start: Callable[[], bool] | None = None,
        on_interrupt_probe_end: Callable[[bool], None] | None = None,
        cleanup_callback: Callable[[str | Path | None], None] | None = None,
    ):
        self.events = events
        self.config = config
        self.on_wake = on_wake
        self.on_interrupt = on_interrupt
        self.on_interrupt_probe_start = on_interrupt_probe_start
        self.on_interrupt_probe_end = on_interrupt_probe_end
        self.transcribe_callback = transcribe_callback
        self.wake_transcribe_callback = wake_transcribe_callback or transcribe_callback
        self.cleanup_callback = cleanup_callback

        self._stop = Event()
        self._paused = Event()

        self._suppressed = Event()
        self._suppression_lock = Lock()
        self._suppression_reasons: set[str] = set()
        self._ignore_until = 0.0

        self._thread: Thread | None = None
        self._state_lock = Lock()
        self._stream_active = False
        self._stream_open_count = 0

        self._templates: list[np.ndarray] = []
        self._template_threshold = float(config.wake_match_floor)
        self._template_durations: list[float] = []
        self._template_loaded = False
        self._interrupt_templates: list[np.ndarray] = []
        self._interrupt_threshold = float(config.interrupt_match_floor)

        self._last_error: str | None = None
        self._detections = 0
        self._wake_checks = 0
        self._commands_transcribed = 0
        self._wake_candidates_confirmed = 0
        self._wake_candidates_rejected = 0
        self._last_wake_score: float | None = None
        self._last_command: str | None = None
        self._current_audio_threshold: float | None = None
        self._last_device_index: int | None = None
        self._last_device_name: str | None = None
        self._last_samplerate: int | None = None
        # Windows can expose duplicate webcam endpoints that open successfully
        # yet return digital zeroes. Quarantine them briefly so the service can
        # rotate to a live duplicate instead of reopening the same dead stream.
        self._silent_device_until: dict[int, float] = {}
        self._interrupt_reject_until = 0.0
        self._interrupt_probe_checks = 0

        self._load_templates()
        self._load_interrupt_templates()

    # ------------------------------------------------------------------
    # Template enrollment / persistence
    # ------------------------------------------------------------------
    @property
    def template_path(self) -> Path:
        return Path(self.config.template_path)

    def enrolled(self) -> bool:
        return len(self._templates) >= 3

    def _load_templates(self) -> None:
        path = self.template_path
        self._template_loaded = True
        if not path.exists():
            self._templates = []
            self._template_durations = []
            self._template_threshold = float(self.config.wake_match_floor)
            return

        try:
            data = np.load(path, allow_pickle=False)
            count = int(data["count"])
            templates = []
            durations = []
            for i in range(count):
                templates.append(
                    np.asarray(data[f"template_{i}"], dtype=np.float32)
                )
                durations.append(float(data[f"duration_{i}"]))

            self._templates = templates
            self._template_durations = durations
            saved_threshold = float(
                data.get("threshold", self.config.wake_match_floor)
            )
            # Runtime safety floor: older enrollment files may carry a very
            # permissive threshold. Never let persisted state weaken the
            # currently shipped false-wake guard. OWNER-tuned values above the
            # floor are preserved.
            self._template_threshold = max(
                float(self.config.wake_match_floor),
                saved_threshold,
            )
            if self._template_threshold > saved_threshold + 1e-9:
                self.events.emit(
                    "WAKE_THRESHOLD_HARDENED",
                    saved_threshold=round(saved_threshold, 4),
                    runtime_threshold=round(self._template_threshold, 4),
                )
        except Exception as exc:
            self._templates = []
            self._template_durations = []
            self._template_threshold = float(self.config.wake_match_floor)
            self._last_error = f"WAKE_TEMPLATE_LOAD: {type(exc).__name__}: {exc}"

    @property
    def interrupt_template_path(self) -> Path:
        return Path(self.config.interrupt_template_path)

    def interrupt_enrolled(self) -> bool:
        return len(self._interrupt_templates) >= 3

    def _load_interrupt_templates(self) -> None:
        path = self.interrupt_template_path
        if not path.exists():
            self._interrupt_templates = []
            self._interrupt_threshold = float(self.config.interrupt_match_floor)
            return
        try:
            data = np.load(path, allow_pickle=False)
            count = int(data["count"])
            self._interrupt_templates = [np.asarray(data[f"template_{i}"], dtype=np.float32) for i in range(count)]
            self._interrupt_threshold = float(data.get("threshold", self.config.interrupt_match_floor))
        except Exception as exc:
            self._interrupt_templates = []
            self._interrupt_threshold = float(self.config.interrupt_match_floor)
            self._last_error = f"INTERRUPT_TEMPLATE_LOAD: {type(exc).__name__}: {exc}"

    def enroll_interrupt(self, wav_paths: list[str | Path]) -> dict[str, Any]:
        if len(wav_paths) < 3:
            return {"ok": False, "error": "INTERRUPT_ENROLL_TOO_FEW_SAMPLES"}
        templates = []
        durations = []
        for wav_path in wav_paths:
            samples, rate = self._read_wav_mono(wav_path)
            trimmed = _trim_voice(_resample_linear(samples, rate, int(self.config.feature_sample_rate)), int(self.config.feature_sample_rate))
            duration = float(trimmed.size) / float(self.config.feature_sample_rate) if trimmed.size else 0.0
            if duration < 0.25 or duration > 1.8:
                return {"ok": False, "error": "INTERRUPT_ENROLL_BAD_DURATION", "duration_seconds": round(duration, 3)}
            features = acoustic_features(trimmed, int(self.config.feature_sample_rate), self.config, trim=False)
            templates.append(features); durations.append(duration)
        scores = [feature_similarity(templates[i], templates[j]) for i in range(len(templates)) for j in range(i+1, len(templates))]
        mean_score = float(np.mean(scores)) if scores else 0.0
        min_score = float(np.min(scores)) if scores else 0.0
        threshold = min(0.92, max(float(self.config.interrupt_match_floor), mean_score - 0.10, min_score - 0.06))
        path = self.interrupt_template_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"count": np.asarray(len(templates), dtype=np.int32), "threshold": np.asarray(threshold, dtype=np.float32)}
        for i, (template, duration) in enumerate(zip(templates, durations)):
            payload[f"template_{i}"] = template
            payload[f"duration_{i}"] = np.asarray(duration, dtype=np.float32)
        np.savez_compressed(path, **payload)
        self._interrupt_templates = templates
        self._interrupt_threshold = threshold
        self.events.emit("VOICE_INTERRUPT_PROFILE_ENROLLED", samples=len(templates), threshold=round(threshold,4), mean_similarity=round(mean_score,4))
        return {"ok": True, "samples": len(templates), "threshold": round(threshold,4), "mean_similarity": round(mean_score,4), "profile": str(path)}

    def delete_interrupt_profile(self) -> bool:
        self._interrupt_templates = []
        self._interrupt_threshold = float(self.config.interrupt_match_floor)
        path = self.interrupt_template_path
        existed = path.exists()
        try: path.unlink(missing_ok=True)
        except OSError: pass
        return existed

    def delete_profile(self) -> bool:
        self._templates = []
        self._template_durations = []
        self._template_threshold = float(self.config.wake_match_floor)
        path = self.template_path
        existed = path.exists()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self.events.emit("WAKE_PROFILE_DELETED", existed=existed)
        return existed

    @staticmethod
    def _read_wav_mono(path: str | Path) -> tuple[np.ndarray, int]:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())

        if width != 2:
            raise ValueError("WAKE_ENROLL_REQUIRES_PCM16")

        values = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            values = values.reshape(-1, channels).mean(axis=1)
        return values.reshape(-1), int(rate)

    def enroll(self, wav_paths: list[str | Path]) -> dict[str, Any]:
        if len(wav_paths) < 3:
            return {
                "ok": False,
                "error": "WAKE_ENROLL_TOO_FEW_SAMPLES",
                "message": "São necessárias pelo menos 3 amostras de 'Jarvis'.",
            }

        templates: list[np.ndarray] = []
        durations: list[float] = []

        for wav_path in wav_paths:
            samples, rate = self._read_wav_mono(wav_path)
            trimmed = _trim_voice(
                _resample_linear(
                    samples,
                    rate,
                    int(self.config.feature_sample_rate),
                ),
                int(self.config.feature_sample_rate),
            )
            duration = (
                float(trimmed.size) / float(self.config.feature_sample_rate)
                if trimmed.size
                else 0.0
            )
            if duration < 0.25 or duration > 1.80:
                return {
                    "ok": False,
                    "error": "WAKE_ENROLL_BAD_DURATION",
                    "duration_seconds": round(duration, 3),
                    "message": (
                        "Cada amostra deve conter apenas a palavra 'Jarvis', "
                        "dita normalmente."
                    ),
                }

            features = acoustic_features(
                trimmed,
                int(self.config.feature_sample_rate),
                self.config,
                trim=False,
            )
            if features.shape[0] < 8:
                return {
                    "ok": False,
                    "error": "WAKE_ENROLL_FEATURES_TOO_SHORT",
                    "message": "A amostra ficou demasiado curta para criar o padrão.",
                }

            templates.append(features)
            durations.append(duration)

        pair_scores = []
        for i in range(len(templates)):
            for j in range(i + 1, len(templates)):
                pair_scores.append(
                    feature_similarity(templates[i], templates[j])
                )

        if not pair_scores:
            return {
                "ok": False,
                "error": "WAKE_ENROLL_SCORE_ERROR",
            }

        mean_score = float(np.mean(pair_scores))
        min_score = float(np.min(pair_scores))

        # Require internally consistent enrollment. A bad sample should be
        # re-recorded rather than creating a dangerously permissive matcher.
        if mean_score < 0.64:
            return {
                "ok": False,
                "error": "WAKE_ENROLL_INCONSISTENT",
                "mean_similarity": round(mean_score, 4),
                "min_similarity": round(min_score, 4),
                "message": (
                    "As amostras de 'Jarvis' ficaram demasiado diferentes. "
                    "Repete o registo com o microfone na posição habitual."
                ),
            }

        calibrated = min(
            0.90,
            max(
                float(self.config.wake_match_floor),
                min_score - float(self.config.wake_match_margin),
                mean_score - 0.11,
            ),
        )

        path = self.template_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "count": np.asarray(len(templates), dtype=np.int32),
            "threshold": np.asarray(calibrated, dtype=np.float32),
        }
        for i, (template, duration) in enumerate(zip(templates, durations)):
            payload[f"template_{i}"] = template
            payload[f"duration_{i}"] = np.asarray(duration, dtype=np.float32)

        np.savez_compressed(path, **payload)

        self._templates = templates
        self._template_durations = durations
        self._template_threshold = calibrated

        self.events.emit(
            "WAKE_PROFILE_ENROLLED",
            samples=len(templates),
            threshold=round(calibrated, 4),
            mean_similarity=round(mean_score, 4),
            min_similarity=round(min_score, 4),
        )

        return {
            "ok": True,
            "samples": len(templates),
            "threshold": round(calibrated, 4),
            "mean_similarity": round(mean_score, 4),
            "min_similarity": round(min_score, 4),
            "profile": str(path),
        }

    # ------------------------------------------------------------------
    # Public state / controls
    # ------------------------------------------------------------------
    def configured(self) -> bool:
        try:
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401
            return callable(self.transcribe_callback)
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            stream_state = {
                "stream_active": self._stream_active,
                "stream_open_count": self._stream_open_count,
                "device": self._last_device_index,
                "device_name": self._last_device_name,
                "sample_rate": self._last_samplerate,
            }

        return {
            "enabled": self.config.enabled,
            "configured": self.configured(),
            "enrolled": self.enrolled(),
            "interrupt_enrolled": self.interrupt_enrolled(),
            "interrupt_threshold": round(self._interrupt_threshold, 4),
            "keyword": self.config.keyword,
            "backend": "numpy-acoustic-wake+faster-whisper-command",
            "architecture": "wake-first-whisper-after",
            "whisper_while_idle": False,
            "templates": len(self._templates),
            "wake_match_threshold": round(self._template_threshold, 4),
            "audio_threshold": self._current_audio_threshold,
            "running": bool(self._thread and self._thread.is_alive()),
            "hard_paused": self._paused.is_set(),
            "audio_suppressed": self._audio_is_suppressed(),
            "detections": self._detections,
            "wake_checks": self._wake_checks,
            "commands_transcribed": self._commands_transcribed,
            "wake_candidate_whisper_confirm": bool(self.config.candidate_whisper_confirm),
            "wake_candidates_confirmed": self._wake_candidates_confirmed,
            "wake_candidates_rejected": self._wake_candidates_rejected,
            "last_wake_score": self._last_wake_score,
            "last_command": self._last_command,
            "last_error": self._last_error,
            **stream_state,
        }

    def start(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "error": "WAKE_DISABLED"}
        if not self.enrolled():
            return {
                "ok": False,
                "error": "WAKE_NOT_ENROLLED",
                "message": "Executa /wake enroll para registar a palavra 'Jarvis'.",
            }
        if self._thread and self._thread.is_alive():
            return {"ok": True, "already_running": True}
        if not self.configured():
            return {"ok": False, "error": "WAKE_NOT_CONFIGURED"}

        self._stop.clear()
        self._paused.clear()
        self._thread = Thread(
            target=self._run,
            name="jarvis-true-wake",
            daemon=True,
        )
        self._thread.start()
        return {
            "ok": True,
            "backend": "numpy-acoustic-wake+faster-whisper-command",
            "whisper_while_idle": False,
        }

    def stop(self) -> None:
        self._stop.set()
        self._paused.clear()
        self._suppressed.clear()
        with self._suppression_lock:
            self._suppression_reasons.clear()
            self._ignore_until = 0.0
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self.events.emit("WAKE_SERVICE_STOPPED")

    def suspend(self, timeout: float = 1.5) -> None:
        self._paused.set()
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            with self._state_lock:
                if not self._stream_active:
                    return
            sleep(0.03)

    def resume(self) -> None:
        self._paused.clear()

    def suppress_audio(
        self,
        enabled: bool,
        *,
        reason: str = "external",
        tail_seconds: float | None = None,
    ) -> None:
        reason = (reason or "external").strip().lower()
        with self._suppression_lock:
            if enabled:
                self._suppression_reasons.add(reason)
                self._suppressed.set()
            else:
                self._suppression_reasons.discard(reason)
                if not self._suppression_reasons:
                    self._suppressed.clear()
                    tail = (
                        self.config.tts_tail_seconds
                        if tail_seconds is None
                        else max(0.0, float(tail_seconds))
                    )
                    self._ignore_until = max(
                        self._ignore_until,
                        monotonic() + tail,
                    )

    # ------------------------------------------------------------------
    # Device / audio helpers
    # ------------------------------------------------------------------
    def _resolve_device(self):
        import sounddevice as sd

        needle = self.config.preferred_device_name.lower().strip()
        devices = list(sd.query_devices())
        hostapis = list(sd.query_hostapis())
        now = monotonic()
        candidates = []
        quarantined = []

        # OWNER-selected A/V binding is authoritative. Windows may expose the
        # same webcam under several host APIs with the same display name; name
        # scoring alone can therefore choose the wrong duplicate endpoint.
        preferred_index = self.config.preferred_device_index
        if preferred_index is not None:
            try:
                idx = int(preferred_index)
                if 0 <= idx < len(devices):
                    dev = devices[idx]
                    if int(dev.get("max_input_channels", 0)) > 0 and self._silent_device_until.get(idx, 0.0) <= now:
                        item = dict(dev)
                        try:
                            api_index = dev.get("hostapi")
                            item["_hostapi_name"] = str(hostapis[int(api_index)].get("name", "")) if api_index is not None else ""
                        except Exception:
                            item["_hostapi_name"] = ""
                        # A stale persisted Windows device index can resolve to
                        # the WDM-KS duplicate after reboot/device reordering.
                        # Do not make that fragile endpoint authoritative; let
                        # the ranked WASAPI/DirectSound candidates win instead.
                        if _windows_capture_hostapi_score(item["_hostapi_name"]) > -1000:
                            return idx, item
            except Exception:
                pass

        for idx, dev in enumerate(devices):
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue
            name = str(dev.get("name", ""))
            lower = name.lower()

            rate = int(float(dev.get("default_samplerate", 0) or 0))
            score = 0
            if self.config.prefer_webcam_audio:
                score += webcam_audio_score(name, self.config.webcam_name_hint)
            if needle and needle in lower:
                score += 1000
            elif needle and not self.config.prefer_webcam_audio:
                continue
            if self.config.preferred_handsfree and "hands-free" in lower:
                score += 100
            if rate == int(self.config.preferred_samplerate):
                score += 50
            channels = int(dev.get("max_input_channels", 0))
            if channels >= 2:
                score += 20
            elif channels == 1:
                score += 5

            hostapi_name = ""
            try:
                api_index = dev.get("hostapi")
                if api_index is not None:
                    hostapi_name = str(hostapis[int(api_index)].get("name", ""))
            except Exception:
                hostapi_name = ""
            score += _windows_capture_hostapi_score(hostapi_name)

            item = dict(dev)
            item["_hostapi_name"] = hostapi_name
            row = (score, idx, item)
            if self._silent_device_until.get(int(idx), 0.0) > now:
                quarantined.append(row)
            else:
                candidates.append(row)

        # If every input is quarantined, allow retry rather than declaring the
        # machine microphone-less. Otherwise dead endpoints remain excluded.
        pool = candidates or quarantined
        if not pool:
            default_index = int(sd.default.device[0])
            return default_index, sd.query_devices(default_index, "input")

        pool.sort(key=lambda row: (row[0], row[1]), reverse=True)
        _, idx, dev = pool[0]
        return int(idx), dev

    def _audio_threshold(self, noise_rms: float) -> float:
        value = max(
            float(self.config.threshold_floor),
            float(noise_rms) * float(self.config.threshold_multiplier),
        )
        return min(value, float(self.config.threshold_ceiling))

    def _audio_is_suppressed(self) -> bool:
        if self._suppressed.is_set():
            return True
        with self._suppression_lock:
            return monotonic() < self._ignore_until

    def _suppression_reason_active(self, reason: str) -> bool:
        wanted = str(reason or "").strip().lower()
        with self._suppression_lock:
            return wanted in self._suppression_reasons

    def _suppression_tail_active(self) -> bool:
        with self._suppression_lock:
            return (
                not self._suppression_reasons
                and monotonic() < self._ignore_until
            )

    @staticmethod
    def _drain_queue(audio_queue: Queue[bytes]) -> int:
        count = 0
        while True:
            try:
                audio_queue.get_nowait()
                count += 1
            except Empty:
                return count

    # ------------------------------------------------------------------
    # Wake match
    # ------------------------------------------------------------------
    def _match_templates(self, samples: np.ndarray, samplerate: int, templates: list[np.ndarray], threshold: float) -> tuple[bool, float, int]:
        source = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not templates or source.size == 0:
            return False, 0.0, 0
        target_rate = int(self.config.feature_sample_rate)
        features = acoustic_features(_resample_linear(source, samplerate, target_rate), target_rate, self.config, trim=False)
        if features.shape[0] < 8:
            return False, 0.0, 0
        hop_seconds = float(self.config.feature_hop_ms) / 1000.0
        slack_frames = max(0, int(round(float(self.config.wake_start_slack_seconds) / hop_seconds)))
        best_score = 0.0; best_end_frame = 0
        for template in templates:
            template_len = int(template.shape[0])
            min_len = max(6, int(round(template_len * 0.72)))
            max_len = max(min_len, int(round(template_len * 1.38)))
            for start in range(0, min(slack_frames, features.shape[0] - 4) + 1, 2):
                available = features.shape[0] - start
                if available < min_len: continue
                stop_len = min(max_len, available)
                step = max(2, (stop_len - min_len) // 4 or 2)
                lengths = list(range(min_len, stop_len + 1, step))
                if lengths[-1] != stop_len: lengths.append(stop_len)
                for length in lengths:
                    score = feature_similarity(template, features[start:start+length])
                    if score > best_score:
                        best_score = score; best_end_frame = start + length
        end_sample = min(source.size, int(round(best_end_frame * hop_seconds * samplerate)))
        return best_score >= float(threshold), float(best_score), int(end_sample)

    def _match_probe(self, samples: np.ndarray, samplerate: int) -> tuple[bool, float, int]:
        self._wake_checks += 1
        return self._match_templates(samples, samplerate, self._templates, self._template_threshold)

    def _match_interrupt_probe(self, samples: np.ndarray, samplerate: int) -> tuple[bool, float, int]:
        return self._match_templates(samples, samplerate, self._interrupt_templates, self._interrupt_threshold)

    def _match_interrupt_probe_sensitive(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> tuple[bool, float, int]:
        """
        Candidate-only matcher used while TTS is active.
        A match never stops speech without Whisper confirmation.
        """
        threshold = max(
            0.50,
            float(self._interrupt_threshold) - 0.10,
        )
        return self._match_templates(
            samples,
            samplerate,
            self._interrupt_templates,
            threshold,
        )

    # ------------------------------------------------------------------
    # Command capture / Whisper -- runs ONLY after wake detection
    # ------------------------------------------------------------------
    def _save_command_wav(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> Path:
        values = np.clip(
            np.asarray(samples, dtype=np.float32).reshape(-1),
            -1.0,
            1.0,
        )
        pcm = (values * 32767.0).astype("<i2")
        path = Path(gettempdir()) / f"jarvis_command_{uuid4().hex}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(samplerate))
            wf.writeframes(pcm.tobytes())
        return path

    def _cleanup(self, path: str | Path | None) -> None:
        if self.cleanup_callback is not None:
            self.cleanup_callback(path)
            return
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass

    def _capture_command(
        self,
        audio_queue: Queue[bytes],
        samplerate: int,
        threshold: float,
        initial_audio: np.ndarray,
    ) -> np.ndarray:
        block_seconds = float(self.config.block_seconds)
        silence_needed = max(
            1,
            int(round(
                float(self.config.command_silence_seconds) / block_seconds
            )),
        )
        max_blocks = max(
            1,
            int(round(
                float(self.config.command_max_seconds) / block_seconds
            )),
        )
        start_timeout = float(self.config.command_start_timeout_seconds)

        frames: list[np.ndarray] = []
        command_started = False
        command_threshold = max(0.0025, float(threshold) * float(self.config.command_threshold_ratio))
        silent_blocks = 0
        started_waiting = monotonic()

        initial = np.asarray(initial_audio, dtype=np.float32).reshape(-1)
        if initial.size:
            # Remove a tiny transition after the matched keyword.
            trim_transition = min(
                initial.size,
                int(round(samplerate * 0.015)),
            )
            initial = initial[trim_transition:]

            if initial.size:
                frames.append(initial)
                if _rms(initial) >= command_threshold:
                    command_started = True

        while len(frames) < max_blocks:
            if self._stop.is_set() or self._paused.is_set():
                break
            if self._audio_is_suppressed():
                return np.zeros(0, dtype=np.float32)

            if not command_started and monotonic() - started_waiting > start_timeout:
                return np.zeros(0, dtype=np.float32)

            try:
                raw = audio_queue.get(timeout=0.5)
            except Empty:
                continue

            mono = _int16_to_float(raw)
            value = _rms(mono)

            if not command_started:
                if value >= command_threshold:
                    command_started = True
                    frames.append(mono)
                    silent_blocks = 0
                continue

            frames.append(mono)
            if value < command_threshold:
                silent_blocks += 1
            else:
                silent_blocks = 0

            if silent_blocks >= silence_needed:
                break

        if not frames:
            return np.zeros(0, dtype=np.float32)

        result = np.concatenate(frames)
        min_samples = int(
            samplerate * float(self.config.command_min_seconds)
        )
        if result.size < min_samples:
            return np.zeros(0, dtype=np.float32)
        return result

    def _transcribe_command(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> str | None:
        path = self._save_command_wav(samples, samplerate)
        try:
            result = self.transcribe_callback(path)
            self._commands_transcribed += 1
            if not result.get("ok"):
                self.events.emit(
                    "WAKE_COMMAND_TRANSCRIPTION_FAILED",
                    error=result.get("error"),
                    message=result.get("message"),
                )
                return None

            text = str(result.get("text", "")).strip()
            lowered = text.lower().lstrip(" ,.-:;")
            keyword = str(self.config.keyword or "Jarvis").strip().lower()
            if keyword and lowered.startswith(keyword):
                text = text[len(keyword):].lstrip(" ,.-:;")
            self._last_command = text or None
            self.events.emit(
                "WAKE_COMMAND_TRANSCRIBED",
                text=text,
                backend=result.get("backend"),
                profile=result.get("profile"),
                beam=result.get("beam_size"),
                elapsed_ms=result.get("elapsed_ms"),
                whisper_passes=1,
            )
            return text or None
        finally:
            self._cleanup(path)

    @staticmethod
    def _normalize_interrupt_text(text: str | None) -> str:
        value = str(text or "").lower().strip()
        value = value.replace("-", " ")
        value = "".join(
            ch for ch in value
            if ch.isalnum() or ch.isspace()
        )
        return " ".join(value.split())

    @classmethod
    def _interrupt_transcript_confirmed(
        cls,
        text: str | None,
    ) -> bool:
        normalized = cls._normalize_interrupt_text(text)
        if not normalized:
            return False
        tokens = normalized.split()
        compact = normalized.replace(" ", "")
        if "calate" in compact:
            return True
        for idx, token in enumerate(tokens):
            if token == "cala":
                if idx + 1 < len(tokens) and tokens[idx + 1] == "te":
                    return True
        return False

    def _begin_interrupt_probe(self) -> bool:
        if self.on_interrupt_probe_start is None:
            return False
        try:
            return bool(self.on_interrupt_probe_start())
        except Exception as exc:
            self.events.emit(
                "VOICE_INTERRUPT_PROBE_PAUSE_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )
            return False

    def _end_interrupt_probe(
        self,
        *,
        confirmed: bool,
        paused: bool,
    ) -> None:
        if self.on_interrupt_probe_end is None or not paused:
            return
        try:
            self.on_interrupt_probe_end(confirmed)
        except Exception as exc:
            self.events.emit(
                "VOICE_INTERRUPT_PROBE_RESUME_FAILED",
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _normalize_wake_text(text: str | None) -> str:
        import unicodedata
        value = unicodedata.normalize("NFKD", str(text or "").lower())
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = "".join(ch if ch.isalnum() else " " for ch in value)
        return " ".join(value.split())

    @classmethod
    def _wake_transcript_confirmed(
        cls,
        text: str | None,
        keyword: str = "JARVIS",
        *,
        max_words: int = 8,
    ) -> bool:
        """Strict lexical confirmation for an acoustic wake candidate.

        The candidate waveform is deliberately isolated around the acoustic
        match.  A confirmation therefore needs to look like the keyword itself,
        not merely contain a keyword hallucination somewhere in normal speech.
        "Hey Jarvis"/"Ei Jarvis" remain accepted, but "Jarvis obrigado" does
        not.  This is independent from the acoustic matcher and is intentionally
        conservative because a false positive opens the command channel.
        """
        normalized = cls._normalize_wake_text(text)
        if not normalized:
            return False
        target = cls._normalize_wake_text(keyword).replace(" ", "") or "jarvis"
        aliases = {target, "jarvis", "jervis", "jarviz", "jarves"}
        fillers = {"hey", "ei", "ola", "olá"}
        tokens = normalized.split()
        limit = max(1, int(max_words))
        if len(tokens) > limit:
            return False
        if limit > 2:
            return any(token in aliases for token in tokens[:2])
        if len(tokens) == 1:
            return tokens[0] in aliases
        if len(tokens) == 2:
            return (
                (tokens[0] in fillers and tokens[1] in aliases)
                or (tokens[0] in aliases and tokens[1] in fillers)
            )
        return False

    def _isolate_wake_candidate(
        self,
        probe: np.ndarray,
        samplerate: int,
        keyword_end: int,
    ) -> np.ndarray:
        """Return only the audio surrounding the acoustic keyword match.

        Previously the whole rolling probe was sent to Whisper.  Combined with
        an initial prompt/hotwords containing "Jarvis", ordinary speech could be
        decoded as the keyword.  Keeping only a short window ending at the
        acoustic match makes Whisper an independent veto rather than a second
        biased detector.
        """
        source = np.asarray(probe, dtype=np.float32).reshape(-1)
        if source.size == 0:
            return source
        end = max(0, min(int(keyword_end), source.size))
        tail = max(0, int(round(float(self.config.candidate_tail_seconds) * samplerate)))
        end_with_tail = min(source.size, end + tail)
        window = max(0.35, float(self.config.candidate_window_seconds))
        start = max(0, end - int(round(window * samplerate)))
        return source[start:end_with_tail]

    def _wake_candidate_result_confirmed(
        self,
        result: dict[str, Any] | None,
        keyword: str,
    ) -> tuple[bool, str]:
        if not isinstance(result, dict) or not result.get("ok"):
            return False, "transcription_failed"
        text = str(result.get("raw_text") or result.get("text") or "").strip()
        if not self._wake_transcript_confirmed(
            text,
            keyword,
            max_words=int(self.config.candidate_max_words),
        ):
            return False, "keyword_not_exact"
        avg_logprob = result.get("avg_logprob")
        if avg_logprob is not None:
            try:
                if float(avg_logprob) < float(self.config.candidate_min_avg_logprob):
                    return False, "low_confidence"
            except (TypeError, ValueError):
                pass
        no_speech = result.get("max_no_speech_prob")
        if no_speech is not None:
            try:
                if float(no_speech) > float(self.config.candidate_max_no_speech_prob):
                    return False, "no_speech_probability"
            except (TypeError, ValueError):
                pass
        return True, "confirmed"

    def _transcribe_wake_candidate_result(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> dict[str, Any] | None:
        path = self._save_command_wav(samples, samplerate)
        try:
            result = self.wake_transcribe_callback(path)
            if not result.get("ok"):
                self.events.emit(
                    "WAKE_CANDIDATE_TRANSCRIPTION_FAILED",
                    error=result.get("error"),
                    message=result.get("message"),
                )
                return result
            text = str(result.get("raw_text") or result.get("text") or "").strip()
            self.events.emit(
                "WAKE_CANDIDATE_TRANSCRIBED",
                text=text,
                backend=result.get("backend"),
                elapsed_ms=result.get("elapsed_ms"),
                avg_logprob=result.get("avg_logprob"),
                no_speech_prob=result.get("max_no_speech_prob"),
                prompt_used=bool(result.get("initial_prompt_used")),
                hotwords_used=bool(result.get("hotwords_used")),
            )
            return dict(result)
        finally:
            self._cleanup(path)

    def _transcribe_wake_candidate(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> str | None:
        """Compatibility wrapper returning only the candidate text."""
        result = self._transcribe_wake_candidate_result(samples, samplerate)
        if not isinstance(result, dict) or not result.get("ok"):
            return None
        text = str(result.get("raw_text") or result.get("text") or "").strip()
        return text or None

    def _transcribe_interrupt_candidate(
        self,
        samples: np.ndarray,
        samplerate: int,
    ) -> str | None:
        """
        Second-stage confirmation for acoustic interruption during TTS.

        The acoustic template is only a cheap candidate detector. We never
        stop JARVIS on that score alone: Whisper must also hear "Cala-te".
        """
        path = self._save_command_wav(samples, samplerate)
        try:
            result = self.transcribe_callback(path)
            if not result.get("ok"):
                self.events.emit(
                    "VOICE_INTERRUPT_TRANSCRIPTION_FAILED",
                    error=result.get("error"),
                    message=result.get("message"),
                )
                return None

            text = str(result.get("text", "")).strip()
            self.events.emit(
                "VOICE_INTERRUPT_TRANSCRIBED",
                text=text,
                backend=result.get("backend"),
                profile=result.get("profile"),
                beam=result.get("beam_size"),
                elapsed_ms=result.get("elapsed_ms"),
            )
            return text or None
        finally:
            self._cleanup(path)


    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def doctor(self) -> dict[str, Any]:
        return {
            **self.status(),
            "ok": self.configured() and self.enrolled(),
            "profile": str(self.template_path),
            "profile_exists": self.template_path.exists(),
            "extra_native_wake_dll": False,
            "wake_engine_uses_whisper": False,
        }

    # ------------------------------------------------------------------
    # Persistent JBL stream
    # ------------------------------------------------------------------
    def _listen_persistent_stream(self) -> None:
        import sounddevice as sd

        device_index, device = self._resolve_device()
        samplerate = int(float(device.get("default_samplerate", 0) or 0))
        if samplerate <= 0:
            samplerate = 48000

        block_frames = max(
            256,
            int(samplerate * float(self.config.block_seconds)),
        )
        calibration_blocks = max(
            2,
            int(
                float(self.config.calibration_seconds)
                / float(self.config.block_seconds)
            ),
        )
        pre_roll_blocks = max(
            1,
            int(
                float(self.config.pre_roll_seconds)
                / float(self.config.block_seconds)
            ),
        )
        probe_max_blocks = max(
            1,
            int(
                float(self.config.probe_max_seconds)
                / float(self.config.block_seconds)
            ),
        )

        audio_queue: Queue[bytes] = Queue(maxsize=160)

        def callback(indata, frames, time_info, status):
            if status:
                self.events.emit(
                    "WAKE_STREAM_STATUS",
                    status=str(status),
                )
            payload = bytes(indata)
            try:
                audio_queue.put_nowait(payload)
            except Full:
                try:
                    audio_queue.get_nowait()
                except Empty:
                    pass
                try:
                    audio_queue.put_nowait(payload)
                except Full:
                    pass

        self.events.emit(
            "WAKE_LISTENING",
            backend="numpy-acoustic-wake",
            device=device_index,
            device_name=str(device.get("name", "")),
            sample_rate=samplerate,
            whisper_while_idle=False,
        )

        with sd.RawInputStream(
            channels=1,
            dtype="int16",
            samplerate=samplerate,
            blocksize=block_frames,
            device=device_index,
            callback=callback,
        ):
            with self._state_lock:
                self._stream_active = True
                self._stream_open_count += 1
                self._last_device_index = device_index
                self._last_device_name = str(device.get("name", ""))
                self._last_samplerate = samplerate
                open_count = self._stream_open_count

            self.events.emit(
                "WAKE_STREAM_OPENED",
                open_count=open_count,
                device=device_index,
                sample_rate=samplerate,
            )

            try:
                noise_values = []
                for _ in range(calibration_blocks):
                    if self._stop.is_set() or self._paused.is_set():
                        return
                    try:
                        raw = audio_queue.get(timeout=1.0)
                    except Empty:
                        continue
                    noise_values.append(_rms(_int16_to_float(raw)))

                if not noise_values:
                    raise RuntimeError(
                        "WAKE_CALLBACK_NO_AUDIO: stream abriu mas não recebeu áudio."
                    )

                calibration_max_rms = max(noise_values) if noise_values else 0.0
                # A webcam with hardware/driver noise gating can legitimately
                # output exact zero while the room is silent, then produce a
                # strong signal as soon as the owner speaks. Callback delivery
                # proves that the stream is alive; do not quarantine it merely
                # because the calibration window itself was silent.
                if calibration_max_rms <= 1e-7:
                    self.events.emit(
                        "WAKE_ZERO_NOISE_FLOOR",
                        device=int(device_index),
                        device_name=str(device.get("name", device_index)),
                        hostapi=str(device.get("_hostapi_name", "")),
                    )
                self._silent_device_until.pop(int(device_index), None)
                noise_rms = _robust_noise_floor(noise_values)
                threshold = self._audio_threshold(noise_rms)
                self._current_audio_threshold = round(threshold, 6)

                self.events.emit(
                    "WAKE_CALIBRATED",
                    noise_rms=round(noise_rms, 6),
                    threshold=round(threshold, 6),
                )

                pre_roll = deque(maxlen=pre_roll_blocks)
                pending: list[np.ndarray] = []

                interrupt_roll_blocks = max(
                    6,
                    int(round(
                        0.90 / float(self.config.block_seconds)
                    )),
                )
                interrupt_roll = deque(
                    maxlen=interrupt_roll_blocks
                )
                tts_rms_ema = 0.0
                tts_spike_blocks = 0

                while not self._stop.is_set() and not self._paused.is_set():
                    try:
                        raw = audio_queue.get(timeout=0.75)
                    except Empty:
                        pending.clear()
                        continue

                    mono = _int16_to_float(raw)
                    value = _rms(mono)

                    if self._audio_is_suppressed():
                        # Barge-In v2. Wake remains muted during TTS.
                        # A possible user interruption is promoted to Whisper
                        # via either a sensitive acoustic match or a sustained
                        # voice-energy spike over the current TTS leakage.
                        tts_active = self._suppression_reason_active("tts")

                        if (
                            not tts_active
                            or self._suppression_tail_active()
                            or monotonic() < self._interrupt_reject_until
                        ):
                            pending.clear()
                            interrupt_roll.clear()
                            tts_spike_blocks = 0
                            pre_roll.append(mono)
                            continue

                        interrupt_roll.append(mono)

                        if tts_rms_ema <= 0:
                            tts_rms_ema = value
                        else:
                            tts_rms_ema = (
                                0.92 * tts_rms_ema
                                + 0.08 * value
                            )

                        spike_threshold = max(
                            threshold * 1.10,
                            tts_rms_ema * 1.35,
                            0.006,
                        )
                        if value >= spike_threshold:
                            tts_spike_blocks += 1
                        else:
                            tts_spike_blocks = max(
                                0,
                                tts_spike_blocks - 1,
                            )

                        self._interrupt_probe_checks += 1
                        stride_ready = (
                            self._interrupt_probe_checks % 2 == 0
                        )
                        enough_audio = (
                            len(interrupt_roll)
                            >= max(
                                5,
                                int(round(
                                    0.45
                                    / float(self.config.block_seconds)
                                )),
                            )
                        )

                        acoustic_match = False
                        acoustic_score = 0.0
                        if (
                            self.interrupt_enrolled()
                            and enough_audio
                            and stride_ready
                        ):
                            probe = np.concatenate(
                                list(interrupt_roll)
                            )
                            (
                                acoustic_match,
                                acoustic_score,
                                _,
                            ) = self._match_interrupt_probe_sensitive(
                                probe,
                                samplerate,
                            )

                        strong_voice_spike = (
                            tts_spike_blocks >= 2
                            and enough_audio
                        )

                        if not (
                            acoustic_match
                            or strong_voice_spike
                        ):
                            pending.clear()
                            continue

                        probe = np.concatenate(
                            list(interrupt_roll)
                        )
                        self.events.emit(
                            "VOICE_INTERRUPT_CANDIDATE",
                            acoustic_match=acoustic_match,
                            acoustic_score=round(
                                acoustic_score,
                                4,
                            ),
                            strong_voice_spike=strong_voice_spike,
                            tts_rms=round(tts_rms_ema, 6),
                            current_rms=round(value, 6),
                        )

                        paused = self._begin_interrupt_probe()
                        transcript = (
                            self._transcribe_interrupt_candidate(
                                probe,
                                samplerate,
                            )
                        )
                        confirmed = (
                            self._interrupt_transcript_confirmed(
                                transcript
                            )
                        )

                        if confirmed:
                            self.events.emit(
                                "VOICE_INTERRUPT_DETECTED",
                                phrase="Cala-te",
                                transcript=transcript,
                                score=round(
                                    acoustic_score,
                                    4,
                                ),
                                threshold=round(
                                    max(
                                        0.50,
                                        float(
                                            self._interrupt_threshold
                                        ) - 0.10,
                                    ),
                                    4,
                                ),
                                confirmation="bargein-v2+whisper",
                                candidate=(
                                    "acoustic"
                                    if acoustic_match
                                    else "voice-spike"
                                ),
                            )

                            pre_roll.clear()
                            pending.clear()
                            interrupt_roll.clear()
                            tts_spike_blocks = 0
                            self._end_interrupt_probe(
                                confirmed=True,
                                paused=paused,
                            )

                            if self.on_interrupt is not None:
                                try:
                                    self.on_interrupt()
                                except Exception as exc:
                                    self.events.emit(
                                        "VOICE_INTERRUPT_ERROR",
                                        error=(
                                            f"{type(exc).__name__}: "
                                            f"{exc}"
                                        ),
                                    )
                            continue

                        self.events.emit(
                            "VOICE_INTERRUPT_REJECTED_SELF_AUDIO",
                            transcript=transcript,
                            score=round(
                                acoustic_score,
                                4,
                            ),
                            candidate=(
                                "acoustic"
                                if acoustic_match
                                else "voice-spike"
                            ),
                            reason="whisper_not_calate",
                        )
                        self._end_interrupt_probe(
                            confirmed=False,
                            paused=paused,
                        )
                        self._interrupt_reject_until = (
                            monotonic() + 0.8
                        )
                        pending.clear()
                        interrupt_roll.clear()
                        tts_spike_blocks = 0
                        continue

                    if not pending:
                        # This is the PRE-WAKE speech gate. `command_threshold`
                        # only exists inside _capture_command(), after JARVIS
                        # has already matched. Using it here crashed the wake
                        # thread on the first live audio block.
                        if value < threshold:
                            pre_roll.append(mono)
                            continue
                        pending.append(mono)
                        continue

                    pending.append(mono)

                    # Confirm actual speech before doing the acoustic wake check.
                    if len(pending) < int(self.config.speech_confirm_blocks):
                        continue

                    probe = np.concatenate([
                        *list(pre_roll),
                        *pending,
                    ])

                    probe_seconds = float(probe.size) / float(samplerate)
                    if probe_seconds < float(self.config.probe_min_seconds):
                        continue

                    # "Cala-te" is an OWNER-priority interrupt even while
                    # JARVIS is idle or thinking. Acoustic matching is only a
                    # cheap candidate gate; Whisper must confirm the literal
                    # phrase before the callback is allowed to latch silence.
                    if self.interrupt_enrolled():
                        interrupt_matched, interrupt_score, _ = self._match_interrupt_probe(
                            probe, samplerate
                        )
                        if interrupt_matched:
                            interrupt_text = self._transcribe_interrupt_candidate(
                                probe, samplerate
                            )
                            if self._interrupt_transcript_confirmed(interrupt_text):
                                self.events.emit(
                                    "VOICE_INTERRUPT_DETECTED",
                                    phrase="Cala-te",
                                    transcript=interrupt_text,
                                    score=round(interrupt_score, 4),
                                    threshold=round(self._interrupt_threshold, 4),
                                    confirmation="idle-acoustic+whisper",
                                    candidate="idle",
                                )
                                pre_roll.clear()
                                pending.clear()
                                if self.on_interrupt is not None:
                                    try:
                                        self.on_interrupt()
                                    except Exception as exc:
                                        self.events.emit(
                                            "VOICE_INTERRUPT_ERROR",
                                            error=f"{type(exc).__name__}: {exc}",
                                        )
                                continue
                            self.events.emit(
                                "VOICE_INTERRUPT_REJECTED",
                                transcript=interrupt_text,
                                score=round(interrupt_score, 4),
                                reason="idle_whisper_not_calate",
                            )

                    matched, score, keyword_end = self._match_probe(
                        probe,
                        samplerate,
                    )

                    if matched:
                        self.events.emit(
                            "WAKE_CANDIDATE",
                            keyword=self.config.keyword,
                            score=round(score, 4),
                            threshold=round(self._template_threshold, 4),
                        )

                        candidate_transcript = None
                        candidate_result = None
                        if bool(self.config.candidate_whisper_confirm):
                            candidate_audio = self._isolate_wake_candidate(
                                probe,
                                samplerate,
                                keyword_end,
                            )
                            candidate_result = self._transcribe_wake_candidate_result(
                                candidate_audio,
                                samplerate,
                            )
                            candidate_transcript = (
                                str((candidate_result or {}).get("raw_text") or (candidate_result or {}).get("text") or "").strip()
                                or None
                            )
                            confirmed, reject_reason = self._wake_candidate_result_confirmed(
                                candidate_result,
                                self.config.keyword,
                            )
                            if not confirmed:
                                self._wake_candidates_rejected += 1
                                self.events.emit(
                                    "WAKE_CANDIDATE_REJECTED",
                                    transcript=candidate_transcript,
                                    score=round(score, 4),
                                    reason=reject_reason,
                                    avg_logprob=(candidate_result or {}).get("avg_logprob"),
                                    no_speech_prob=(candidate_result or {}).get("max_no_speech_prob"),
                                )
                                pre_roll.clear()
                                pending.clear()
                                with self._suppression_lock:
                                    self._ignore_until = max(
                                        self._ignore_until,
                                        monotonic() + max(0.0, float(self.config.candidate_reject_cooldown_seconds)),
                                    )
                                continue
                            self._wake_candidates_confirmed += 1
                            self.events.emit(
                                "WAKE_CANDIDATE_CONFIRMED",
                                transcript=candidate_transcript,
                                score=round(score, 4),
                                avg_logprob=(candidate_result or {}).get("avg_logprob"),
                            )

                        self._detections += 1
                        self._last_wake_score = round(score, 4)

                        self.events.emit(
                            "WAKE_WORD_DETECTED",
                            keyword=self.config.keyword,
                            score=round(score, 4),
                            threshold=round(self._template_threshold, 4),
                            stream_open_count=self._stream_open_count,
                            whisper_used=bool(self.config.candidate_whisper_confirm),
                            candidate_transcript=candidate_transcript,
                        )

                        command_preroll = int(round(
                            samplerate * float(self.config.command_preroll_seconds)
                        ))
                        command_start = max(0, int(keyword_end) - command_preroll)
                        initial_command = probe[command_start:]
                        pre_roll.clear()
                        pending.clear()

                        command_audio = self._capture_command(
                            audio_queue,
                            samplerate,
                            threshold,
                            initial_command,
                        )

                        if command_audio.size == 0:
                            self.events.emit(
                                "WAKE_COMMAND_TIMEOUT",
                                message="Wake reconhecido, mas não ouvi um comando.",
                            )
                            try:
                                self.on_wake(None)
                            except Exception as exc:
                                self.events.emit(
                                    "WAKE_CALLBACK_ERROR",
                                    error=f"{type(exc).__name__}: {exc}",
                                )
                        else:
                            command = self._transcribe_command(
                                command_audio,
                                samplerate,
                            )
                            if command:
                                try:
                                    self.on_wake(command)
                                except Exception as exc:
                                    self.events.emit(
                                        "WAKE_CALLBACK_ERROR",
                                        error=f"{type(exc).__name__}: {exc}",
                                    )

                        # Same JBL stream continues to live. Drop stale audio
                        # accumulated while routing/TTS started.
                        self._drain_queue(audio_queue)
                        with self._suppression_lock:
                            self._ignore_until = max(
                                self._ignore_until,
                                monotonic() + float(self.config.rearm_seconds),
                            )
                        continue

                    # Not Jarvis. Let the speech burst grow a little more so a
                    # continuous "Jarvis, abre..." can still match its prefix.
                    if len(pending) >= probe_max_blocks:
                        pre_roll.clear()
                        pending.clear()
                        continue

                    # If speech already fell back below threshold and no wake
                    # matched, discard it quietly. No Whisper, no noisy log.
                    if value < threshold and probe_seconds >= 0.45:
                        pre_roll.clear()
                        pending.clear()

            finally:
                with self._state_lock:
                    self._stream_active = False
                self.events.emit(
                    "WAKE_STREAM_CLOSED",
                    reason=(
                        "stop"
                        if self._stop.is_set()
                        else "hard_pause"
                        if self._paused.is_set()
                        else "stream_exit"
                    ),
                )

    def _run(self) -> None:
        self.events.emit(
            "WAKE_SERVICE_STARTED",
            backend="numpy-acoustic-wake",
            whisper_while_idle=False,
            keyword=self.config.keyword,
        )

        while not self._stop.is_set():
            if self._paused.is_set():
                sleep(0.05)
                continue
            try:
                self._listen_persistent_stream()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                self.events.emit(
                    "WAKE_ERROR",
                    error=self._last_error,
                )
                sleep(0.8)
