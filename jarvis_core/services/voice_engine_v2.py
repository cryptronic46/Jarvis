from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from threading import Event, Lock, Thread
from time import monotonic, sleep
from typing import Any, Callable
from uuid import uuid4
import math
import wave

import numpy as np

from jarvis_core.services.wakeword import (
    acoustic_features,
    feature_similarity,
    _resample_linear,
    _trim_voice,
)
from jarvis_core.services.wake_verifier import NumpyWakeVerifier
from jarvis_core.services.openwakeword_compat import (
    load_openwakeword,
    runtime_classes as openwakeword_runtime_classes,
    runtime_probe as openwakeword_runtime_probe,
)


@dataclass(slots=True)
class VoiceV2Config:
    enabled: bool = True
    auto_start: bool = True
    keyword: str = "JARVIS"

    # Input ownership: Voice v2 intentionally uses one WASAPI capture stream.
    preferred_device_index: int | None = None
    preferred_device_name: str = ""
    prefer_webcam_audio: bool = True
    webcam_name_hint: str = ""
    target_sample_rate: int = 16000
    frame_ms: int = 80

    # openWakeWord + built-in Silero VAD.
    wake_model_key: str = "jarvis"
    custom_wake_model_path: str = "models/openwakeword/jarvis.onnx"
    wake_threshold: float = 0.45
    wake_vad_threshold: float = 0.35
    # Medium-confidence hits must persist briefly. A strong dedicated KWS hit
    # may wake immediately; weaker single-frame spikes are ignored.
    wake_strong_threshold: float = 0.45
    wake_confirm_frames: int = 1
    wake_confirm_window_seconds: float = 0.15
    wake_debounce_seconds: float = 1.25

    # Turn capture after a verified wake.
    command_start_timeout_seconds: float = 4.0
    inline_command_grace_seconds: float = 0.45
    command_silence_seconds: float = 0.72
    command_max_seconds: float = 10.0
    command_min_seconds: float = 0.22
    command_preroll_seconds: float = 0.24
    command_vad_threshold: float = 0.48
    command_threshold_ratio: float = 0.65  # compatibility/status field

    # TTS suppression / restart behavior.
    tts_tail_seconds: float = 0.25
    rearm_seconds: float = 0.25
    stream_recovery_seconds: float = 0.75

    # Legacy local acoustic interrupt profile is reused on the SAME v2 stream.
    interrupt_template_path: str = "voice_profiles/interrupt_cala_te.npz"
    interrupt_enrollment_samples: int = 5
    interrupt_match_floor: float = 0.66
    feature_sample_rate: int = 16000
    feature_frame_ms: float = 25.0
    feature_hop_ms: float = 10.0
    feature_bands: int = 24

    # STT residency: Faster Whisper may use CUDA but must not squat in VRAM.
    stt_idle_release_seconds: float = 120.0

    # Optional owner-specific second-stage verifier trained with the official
    # openWakeWord sklearn pipeline (typically in WSL under strict App Control).
    wake_verifier_path: str = "models/wake_verifier_jarvis.npz"
    wake_verifier_threshold: float = 0.55

    # OWNER-enrolled acoustic wake profile. Voice v2 runs this in parallel
    # with the generic openWakeWord model so the natural command "Jarvis"
    # remains reliable without requiring "Hey Jarvis".
    wake_template_path: str = "voice_profiles/wake_jarvis.npz"
    wake_match_floor: float = 0.58
    wake_match_margin: float = 0.08
    wake_start_slack_seconds: float = 0.18
    # Medium-confidence OWNER-template hits are finalized only at phrase end
    # and independently confirmed by the lightweight wake STT callback. Strong
    # hits stay immediate so a clear "Jarvis" remains responsive.
    owner_wake_fast_accept_threshold: float = 0.70
    owner_wake_semantic_confirm: bool = True
    owner_wake_max_phrase_seconds: float = 1.15


class VoiceEngineV2:
    """Windows-first local voice front-end.

    Architecture:
        PyAudioWPatch / WASAPI -> Silero VAD -> openWakeWord
        -> command capture -> Faster Whisper.

    0.27.6 intentionally removes the accumulated acoustic-profile, semantic
    verifier and confidence-gate stack from the active wake path.

    The wake decision never calls Whisper. This is deliberate: a speech-to-text
    model should not be asked to decide whether arbitrary room speech was the
    wake word. openWakeWord owns that job and runs continuously on CPU.
    """

    def __init__(
        self,
        events,
        config: VoiceV2Config,
        on_wake: Callable[[str | None], None],
        transcribe_callback: Callable[[str | Path], dict[str, Any]],
        on_interrupt: Callable[[], None] | None = None,
        cleanup_callback: Callable[[str | Path | None], None] | None = None,
        release_stt_callback: Callable[[], dict[str, Any]] | None = None,
        before_stt_callback: Callable[[], dict[str, Any] | None] | None = None,
        wake_transcribe_callback: Callable[[str | Path], dict[str, Any]] | None = None,
    ):
        self.events = events
        self.config = config
        self.on_wake = on_wake
        self.transcribe_callback = transcribe_callback
        self.on_interrupt = on_interrupt
        self.cleanup_callback = cleanup_callback
        self.release_stt_callback = release_stt_callback
        self.before_stt_callback = before_stt_callback
        self.wake_transcribe_callback = wake_transcribe_callback

        self._stop = Event()
        self._paused = Event()
        self._suppressed = Event()
        self._suppression_lock = Lock()
        self._suppression_reasons: set[str] = set()
        self._ignore_until = 0.0
        self._state_lock = Lock()
        self._thread: Thread | None = None

        self._runtime_loaded = False
        self._runtime_error: str | None = None
        self._pyaudio_module = None
        self._oww_model = None
        self._vad = None
        self._wake_verifier: NumpyWakeVerifier | None = None
        self._wake_verifier_error: str | None = None
        self._last_verifier_score: float | None = None

        self._stream_active = False
        self._stream_open_count = 0
        self._last_device_index: int | None = None
        self._last_device_name: str | None = None
        self._last_samplerate: int | None = None
        self._last_error: str | None = None
        self._device_unavailable = False
        self._device_failure_count = 0
        self._device_retry_at = 0.0
        self._last_wake_score: float | None = None
        self._last_command: str | None = None
        self._detections = 0
        self._wake_checks = 0
        self._commands_transcribed = 0
        self._last_stt_at = 0.0
        self._stt_released_after_idle = False
        self._last_activation_at = 0.0
        self._wake_confirm_hits = 0
        self._wake_confirm_started_at = 0.0

        self._wake_templates: list[np.ndarray] = []
        self._wake_template_threshold = float(config.wake_match_floor)
        self._wake_template_durations: list[float] = []
        self._wake_profile_frames: list[np.ndarray] = []
        self._wake_profile_last_score = 0.0
        self._wake_profile_checks = 0
        self._wake_profile_last_check_frames = 0
        self._wake_profile_confirm_hits = 0
        self._wake_profile_silence_frames = 0
        self._wake_profile_active = False
        self._wake_profile_preroll: deque[np.ndarray] = deque(maxlen=3)
        self._wake_profile_last_vad = 0.0
        self._wake_profile_last_rms = 0.0
        self._wake_profile_best_score = 0.0
        self._wake_profile_candidate_audio: np.ndarray | None = None
        self._wake_profile_candidate_hits = 0
        self._wake_profile_candidate_duration = 0.0
        self._wake_profile_semantic_checks = 0
        self._wake_profile_semantic_rejects = 0
        self._wake_profile_last_semantic_text: str | None = None

        self._interrupt_templates: list[np.ndarray] = []
        self._interrupt_threshold = float(config.interrupt_match_floor)
        self._interrupt_vad_active = False
        self._interrupt_frames: list[np.ndarray] = []
        self._interrupt_silence_frames = 0
        self._load_wake_templates()
        self._load_interrupt_templates()

    @property
    def wake_template_path(self) -> Path:
        return Path(self.config.wake_template_path)

    def _load_wake_templates(self) -> None:
        path = self.wake_template_path
        self._wake_templates = []
        self._wake_template_durations = []
        self._wake_template_threshold = float(self.config.wake_match_floor)
        if not path.exists():
            return
        try:
            data = np.load(path, allow_pickle=False)
            count = int(data["count"])
            for i in range(count):
                self._wake_templates.append(
                    np.asarray(data[f"template_{i}"], dtype=np.float32)
                )
                self._wake_template_durations.append(float(data[f"duration_{i}"]))
            saved = float(data.get("threshold", self.config.wake_match_floor))
            # The profile threshold is calibrated from the OWNER's own voice.
            # Do not silently override it with a later global hardening floor:
            # 0.26.4 did exactly that (0.62 -> 0.72) and made valid enrolled
            # profiles effectively deaf. Clamp only against absurd/corrupt data.
            if math.isfinite(saved) and 0.45 <= saved <= 0.95:
                self._wake_template_threshold = saved
            else:
                self._wake_template_threshold = float(self.config.wake_match_floor)
        except Exception as exc:
            self._wake_templates = []
            self._wake_template_durations = []
            self._wake_template_threshold = float(self.config.wake_match_floor)
            self.events.emit(
                "VOICE_V2_OWNER_WAKE_PROFILE_FAILED",
                error=f"{type(exc).__name__}: {exc}",
                path=str(path),
            )

    def owner_wake_enrolled(self) -> bool:
        return len(self._wake_templates) >= 3

    def _owner_wake_match(self, samples16: np.ndarray) -> tuple[bool, float]:
        source_i16 = np.asarray(samples16, dtype=np.int16).reshape(-1)
        if source_i16.size == 0 or not self._wake_templates:
            return False, 0.0
        source = source_i16.astype(np.float32) / 32768.0
        features = acoustic_features(
            source, int(self.config.feature_sample_rate), self.config, trim=False
        )
        if features.shape[0] < 8:
            return False, 0.0
        hop_seconds = float(self.config.feature_hop_ms) / 1000.0
        slack_frames = max(
            0, int(round(float(self.config.wake_start_slack_seconds) / hop_seconds))
        )
        best = 0.0
        for template in self._wake_templates:
            template_len = int(template.shape[0])
            min_len = max(6, int(round(template_len * 0.72)))
            max_len = max(min_len, int(round(template_len * 1.38)))
            for start in range(0, min(slack_frames, features.shape[0] - 4) + 1, 2):
                available = features.shape[0] - start
                if available < min_len:
                    continue
                stop_len = min(max_len, available)
                step = max(2, (stop_len - min_len) // 4 or 2)
                lengths = list(range(min_len, stop_len + 1, step))
                if not lengths or lengths[-1] != stop_len:
                    lengths.append(stop_len)
                for length in lengths:
                    score = feature_similarity(template, features[start:start + length])
                    if score > best:
                        best = float(score)
        self._wake_profile_last_score = round(best, 4)
        self._wake_profile_checks += 1
        return best >= float(self._wake_template_threshold), best

    def _reset_owner_wake_capture(self) -> None:
        self._wake_profile_frames = []
        self._wake_profile_last_check_frames = 0
        self._wake_profile_confirm_hits = 0
        self._wake_profile_silence_frames = 0
        self._wake_profile_active = False
        self._wake_profile_preroll.clear()
        self._wake_profile_best_score = 0.0

    def _process_owner_wake_frame(
        self, frame16: np.ndarray, vad_score: float
    ) -> tuple[bool, float]:
        """Run the OWNER's enrolled ``Jarvis`` matcher on the v2 stream.

        0.26.7 deliberately distinguishes *strong* and *medium* template hits.
        A strong hit may activate immediately. A medium hit must survive the
        temporal matcher until the short utterance ends; this prevents an
        arbitrary longer room sentence from waking JARVIS merely because one
        sub-window resembles the enrolled word.
        """
        if not self.owner_wake_enrolled():
            return False, 0.0

        frame = np.asarray(frame16, dtype=np.int16).copy()
        rms = self._rms_int16(frame)
        self._wake_profile_last_vad = round(float(vad_score), 4)
        self._wake_profile_last_rms = round(float(rms), 6)
        speech = float(vad_score) >= 0.28 or float(rms) >= 0.006

        if not self._wake_profile_active:
            self._wake_profile_preroll.append(frame)
            if not speech:
                return False, self._wake_profile_last_score
            self._wake_profile_active = True
            self._wake_profile_frames = list(self._wake_profile_preroll)
            self._wake_profile_last_check_frames = 0
            self._wake_profile_confirm_hits = 0
            self._wake_profile_silence_frames = 0
            self._wake_profile_best_score = 0.0
        else:
            self._wake_profile_frames.append(frame)

        if speech:
            self._wake_profile_silence_frames = 0
        else:
            self._wake_profile_silence_frames += 1

        frame_ms = max(20, int(self.config.frame_ms))
        max_frames = max(8, int(round(1.65 * 1000.0 / frame_ms)))
        if len(self._wake_profile_frames) > max_frames:
            self._wake_profile_frames = self._wake_profile_frames[-max_frames:]

        current_frames = len(self._wake_profile_frames)
        min_frames = max(4, int(round(0.30 * 1000.0 / frame_ms)))
        should_check = (
            current_frames >= min_frames
            and (
                current_frames - self._wake_profile_last_check_frames >= 2
                or self._wake_profile_silence_frames >= 2
            )
        )
        score = float(self._wake_profile_last_score)
        if should_check:
            self._wake_profile_last_check_frames = current_frames
            samples = np.concatenate(self._wake_profile_frames)
            matched, score = self._owner_wake_match(samples)
            self._wake_profile_best_score = max(self._wake_profile_best_score, float(score))
            if matched:
                if score >= max(
                    float(self._wake_template_threshold),
                    float(self.config.owner_wake_fast_accept_threshold),
                ):
                    self._wake_profile_candidate_audio = samples.copy()
                    self._wake_profile_candidate_hits = max(1, self._wake_profile_confirm_hits + 1)
                    self._wake_profile_candidate_duration = float(samples.size) / float(self.config.feature_sample_rate)
                    self._reset_owner_wake_capture()
                    return True, score
                self._wake_profile_confirm_hits += 1
            elif self._wake_profile_confirm_hits:
                self._wake_profile_confirm_hits = max(0, self._wake_profile_confirm_hits - 1)

        # Medium hits are accepted only after the short utterance closes. This
        # is the main false-wake guard for TV/video/room speech.
        if self._wake_profile_silence_frames >= 2:
            samples = np.concatenate(self._wake_profile_frames) if self._wake_profile_frames else np.zeros(0, dtype=np.int16)
            duration = float(samples.size) / float(self.config.feature_sample_rate) if samples.size else 0.0
            best = float(self._wake_profile_best_score)
            needed = (1 if best >= float(self._wake_template_threshold) + 0.035 else max(1, int(self.config.wake_confirm_frames)))
            accepted = (
                self._wake_profile_confirm_hits >= needed
                and best >= float(self._wake_template_threshold)
                and 0.22 <= duration <= float(self.config.owner_wake_max_phrase_seconds)
            )
            if accepted:
                self._wake_profile_candidate_audio = samples.copy()
                self._wake_profile_candidate_hits = int(self._wake_profile_confirm_hits)
                self._wake_profile_candidate_duration = float(duration)
            self._reset_owner_wake_capture()
            return accepted, best

        return False, float(score)

    @staticmethod
    def _wake_transcript_is_keyword(text: str) -> bool:
        import re
        import unicodedata
        value = unicodedata.normalize("NFKD", str(text or "").lower())
        value = "".join(ch for ch in value if not unicodedata.combining(ch))
        value = re.sub(r"[^a-z0-9]+", " ", value).strip()
        return value in {"jarvis", "jervis", "jarves", "jarviz", "zarvis", "jarbis"}

    def _confirm_owner_wake_semantically(self, score: float) -> bool:
        """Independent veto for medium-confidence acoustic wakes.

        Whisper is *not* run continuously. It is invoked only after the local
        acoustic template already produced a candidate below the fast-accept
        threshold. This makes false wake-ups much harder without adding latency
        to clear/strong OWNER wakes.
        """
        if not bool(self.config.owner_wake_semantic_confirm):
            self._wake_profile_candidate_audio = None
            return True
        short_temporal_owner_hit = (
            int(self._wake_profile_candidate_hits) >= max(2, int(self.config.wake_confirm_frames))
            and 0.22 <= float(self._wake_profile_candidate_duration) <= float(self.config.owner_wake_max_phrase_seconds)
            and float(score) >= float(self._wake_template_threshold)
        )
        if (
            float(score) >= float(self.config.owner_wake_fast_accept_threshold)
            or short_temporal_owner_hit
        ):
            self._wake_profile_candidate_audio = None
            self._wake_profile_candidate_hits = 0
            self._wake_profile_candidate_duration = 0.0
            return True
        callback = self.wake_transcribe_callback
        samples = self._wake_profile_candidate_audio
        if callback is None or samples is None or samples.size == 0:
            self._wake_profile_candidate_hits = 0
            self._wake_profile_candidate_duration = 0.0
            return False
        path = self._write_wav16([samples])
        try:
            self._wake_profile_semantic_checks += 1
            result = callback(path)
            text = str(result.get("text") or "").strip()
            self._wake_profile_last_semantic_text = text or None
            accepted = bool(result.get("ok")) and self._wake_transcript_is_keyword(text)
            if not accepted:
                self._wake_profile_semantic_rejects += 1
                self.events.emit(
                    "VOICE_V2_OWNER_WAKE_SEMANTIC_REJECTED",
                    score=round(float(score), 4),
                    text=text,
                    avg_logprob=result.get("avg_logprob"),
                    no_speech_prob=result.get("max_no_speech_prob"),
                )
            return accepted
        finally:
            self._wake_profile_candidate_audio = None
            self._wake_profile_candidate_hits = 0
            self._wake_profile_candidate_duration = 0.0
            if self.cleanup_callback:
                self.cleanup_callback(path)
            else:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Dependencies / runtime
    # ------------------------------------------------------------------
    def configured(self) -> bool:
        try:
            import pyaudiowpatch  # noqa: F401
            import onnxruntime  # noqa: F401
            openwakeword_runtime_classes()
            return callable(self.transcribe_callback)
        except Exception:
            return False

    def enrolled(self) -> bool:
        # openWakeWord ships a pretrained "hey jarvis" model; owner enrollment
        # is not required for the wake engine itself.
        return self.configured()

    def _load_runtime(self) -> None:
        if self._runtime_loaded:
            return
        try:
            import pyaudiowpatch as pyaudio
            Model, VAD = openwakeword_runtime_classes()

            # Force the ONNX backend. openWakeWord 0.6.0 wraps Model.__init__
            # in a decorator whose public signature is ``(*args, **kwargs)``;
            # signature introspection therefore cannot be used to discover
            # ``inference_framework``. Falling back to bare ``Model()`` makes
            # openWakeWord choose TFLite and fails on our Windows inference-only
            # install. Never silently fall back to TFLite.
            custom_model = Path(self.config.custom_wake_model_path)
            wake_models = [str(custom_model)] if custom_model.is_file() else ["hey_jarvis"]
            kwargs: dict[str, Any] = {
                "wakeword_models": wake_models,
                "inference_framework": "onnx",
                # Silero is run explicitly before openWakeWord below.
                "vad_threshold": 0.0,
            }
            try:
                self._oww_model = Model(**kwargs)
            except TypeError as exc:
                # Older compatible builds may not expose vad_threshold. ONNX is
                # still mandatory; only the optional built-in VAD argument may
                # be removed because we also run Silero explicitly below.
                if "vad_threshold" not in str(exc):
                    raise
                kwargs.pop("vad_threshold", None)
                self._oww_model = Model(**kwargs)
            self._vad = VAD(n_threads=1)
            self._pyaudio_module = pyaudio
            self._wake_verifier = None
            self._wake_verifier_error = None
            self._runtime_loaded = True
            self._runtime_error = None
            self.events.emit(
                "VOICE_V2_RUNTIME_READY",
                wake="openwakeword-custom-or-hey-jarvis",
                vad="silero-onnx",
                capture="pyaudiowpatch-wasapi",
            )
        except Exception as exc:
            self._runtime_error = f"{type(exc).__name__}: {exc}"
            self._runtime_loaded = False
            self.events.emit("VOICE_V2_RUNTIME_FAILED", error=self._runtime_error)
            raise

    # ------------------------------------------------------------------
    # Device resolution: WASAPI only
    # ------------------------------------------------------------------
    @staticmethod
    def _norm(text: str | None) -> str:
        return str(text or "").strip().lower()

    def _device_score(self, info: dict[str, Any], default_index: int | None) -> int:
        name = self._norm(info.get("name"))
        preferred = self._norm(self.config.preferred_device_name)
        hint = self._norm(self.config.webcam_name_hint)
        score = 0
        if preferred and preferred in name:
            score += 5000
        if hint and hint in name:
            score += 4200
        if self.config.prefer_webcam_audio and any(
            marker in name for marker in ("webcam", "camera", "cam ", "general webcam", "usb video")
        ):
            score += 3000
        if "micro" in name or "mic" in name:
            score += 120
        if default_index is not None and int(info.get("index", -1)) == int(default_index):
            score += 500
        return score

    def _wasapi_devices(self, p) -> list[dict[str, Any]]:
        pa = self._pyaudio_module
        if pa is None:
            return []
        try:
            wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
            wasapi_index = int(wasapi.get("index"))
            default_index = wasapi.get("defaultInputDevice")
            if default_index is not None:
                default_index = int(default_index)
        except Exception:
            wasapi_index = -1
            default_index = None

        rows: list[dict[str, Any]] = []
        for i in range(int(p.get_device_count())):
            try:
                info = dict(p.get_device_info_by_index(i))
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0) or 0) <= 0:
                continue
            if wasapi_index >= 0 and int(info.get("hostApi", -1)) != wasapi_index:
                continue
            info["index"] = i
            info["hostapi"] = "Windows WASAPI"
            info["score"] = self._device_score(info, default_index)
            rows.append(info)
        rows.sort(key=lambda row: (int(row.get("score", 0)), -int(row.get("index", 0))), reverse=True)
        return rows

    def _select_device(self, p) -> dict[str, Any]:
        rows = self._wasapi_devices(p)
        if not rows:
            raise RuntimeError("VOICE_V2_NO_WASAPI_INPUT")

        # IMPORTANT: legacy sounddevice indices are not assumed to be PyAudio
        # indices. A v2 index is accepted only when it points to a WASAPI input;
        # otherwise name scoring safely resolves the equivalent endpoint.
        preferred = self.config.preferred_device_index
        if preferred is not None:
            expected_name = self._norm(self.config.preferred_device_name)
            for row in rows:
                if int(row["index"]) != int(preferred):
                    continue
                # A sounddevice index from the legacy backend may numerically
                # collide with a different PyAudioWPatch device. Only honor
                # the numeric index when the device name also agrees.
                if expected_name and expected_name not in self._norm(row.get("name")):
                    continue
                return row
        return rows[0]

    @staticmethod
    def _to_mono_int16(raw: bytes, channels: int) -> np.ndarray:
        values = np.frombuffer(raw, dtype=np.int16)
        if channels > 1 and values.size >= channels:
            usable = values[: (values.size // channels) * channels]
            values = usable.reshape(-1, channels).astype(np.int32).mean(axis=1).astype(np.int16)
        return np.ascontiguousarray(values, dtype=np.int16)

    @staticmethod
    def _resample_int16(values: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        src = np.asarray(values, dtype=np.int16).reshape(-1)
        if src.size == 0 or source_rate == target_rate:
            return np.ascontiguousarray(src, dtype=np.int16)
        target_len = max(1, int(round(src.size * float(target_rate) / float(source_rate))))
        old_x = np.linspace(0.0, 1.0, num=src.size, endpoint=True)
        new_x = np.linspace(0.0, 1.0, num=target_len, endpoint=True)
        out = np.interp(new_x, old_x, src.astype(np.float32))
        return np.clip(out, -32768, 32767).astype(np.int16)

    @staticmethod
    def _rms_int16(values: np.ndarray) -> float:
        x = np.asarray(values, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return 0.0
        x /= 32768.0
        return float(np.sqrt(np.mean(x * x)))

    def _read_frame16(self, stream, *, source_rate: int, channels: int, frames_per_buffer: int) -> np.ndarray:
        raw = stream.read(frames_per_buffer, exception_on_overflow=False)
        mono = self._to_mono_int16(raw, channels)
        return self._resample_int16(mono, source_rate, int(self.config.target_sample_rate))

    # ------------------------------------------------------------------
    # Wake / VAD
    # ------------------------------------------------------------------
    def _jarvis_score(self, predictions: dict[str, Any]) -> tuple[float, str | None]:
        best_score = 0.0
        best_key = None
        wanted = self._norm(self.config.wake_model_key) or "jarvis"
        for key, value in dict(predictions or {}).items():
            name = self._norm(key)
            if wanted not in name and "jarvis" not in name:
                continue
            try:
                score = float(value)
            except Exception:
                continue
            if score > best_score:
                best_score = score
                best_key = str(key)
        return best_score, best_key

    def _wake_gate(
        self,
        score: float,
        vad_score: float,
        *,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Minimal voice gate: Silero says speech, openWakeWord says Jarvis."""
        if float(vad_score) < float(self.config.wake_vad_threshold):
            return False, "vad_rejected"
        if float(score) < float(self.config.wake_threshold):
            return False, "score_rejected"
        return True, "vad+kws"

    def _verifier_score(self, model_key: str | None) -> float | None:
        verifier = self._wake_verifier
        if verifier is None or self._oww_model is None or not model_key:
            return None
        try:
            model_inputs = getattr(self._oww_model, "model_inputs", {})
            input_frames = model_inputs.get(model_key) if isinstance(model_inputs, dict) else None
            if input_frames is None:
                raise KeyError(f"WAKE_VERIFIER_MODEL_KEY:{model_key}")
            preprocessor = getattr(self._oww_model, "preprocessor", None)
            if preprocessor is None or not hasattr(preprocessor, "get_features"):
                raise RuntimeError("WAKE_VERIFIER_FEATURES_UNAVAILABLE")
            features = preprocessor.get_features(input_frames)
            score = float(verifier.score(features))
            self._last_verifier_score = round(score, 4)
            return score
        except Exception as exc:
            self._wake_verifier_error = f"{type(exc).__name__}: {exc}"
            self.events.emit("VOICE_V2_VERIFIER_FAILED", error=self._wake_verifier_error)
            return None

    def _vad_score(self, frame16: np.ndarray) -> float:
        if self._vad is None:
            rms = self._rms_int16(frame16)
            return min(1.0, rms / 0.03)
        try:
            # 1280 samples (80 ms) is divisible by 640, a size supported by the
            # Silero ONNX wrapper bundled with openWakeWord.
            return float(self._vad.predict(np.asarray(frame16, dtype=np.int16), frame_size=640))
        except Exception:
            rms = self._rms_int16(frame16)
            return min(1.0, rms / 0.03)

    def _reset_models(self) -> None:
        try:
            if self._oww_model is not None and hasattr(self._oww_model, "reset"):
                self._oww_model.reset()
        except Exception:
            pass
        try:
            if self._vad is not None and hasattr(self._vad, "reset_states"):
                self._vad.reset_states()
        except Exception:
            pass

    def _write_wav16(self, frames: list[np.ndarray]) -> Path:
        path = Path(gettempdir()) / f"jarvis_voice_v2_{uuid4().hex}.wav"
        pcm = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(int(self.config.target_sample_rate))
            wf.writeframes(np.asarray(pcm, dtype=np.int16).tobytes())
        return path

    def _capture_command(
        self,
        stream,
        *,
        source_rate: int,
        channels: int,
        frames_per_buffer: int,
        start_timeout_seconds: float | None = None,
    ) -> str | None:
        frame_seconds = max(0.02, float(self.config.frame_ms) / 1000.0)
        pre_roll_frames = max(0, int(round(float(self.config.command_preroll_seconds) / frame_seconds)))
        pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_frames)
        frames: list[np.ndarray] = []
        speech_started = False
        speech_started_at = 0.0
        silence_seconds = 0.0
        started = monotonic()

        try:
            if self._vad is not None and hasattr(self._vad, "reset_states"):
                self._vad.reset_states()
        except Exception:
            pass

        while not self._stop.is_set():
            elapsed = monotonic() - started
            if elapsed >= float(self.config.command_max_seconds):
                break
            frame = self._read_frame16(
                stream,
                source_rate=source_rate,
                channels=channels,
                frames_per_buffer=frames_per_buffer,
            )
            vad_score = self._vad_score(frame)
            is_speech = vad_score >= float(self.config.command_vad_threshold)

            if not speech_started:
                pre_roll.append(frame.copy())
                if is_speech:
                    speech_started = True
                    speech_started_at = monotonic()
                    frames.extend(list(pre_roll))
                    pre_roll.clear()
                    frames.append(frame.copy())
                    self.events.emit("VOICE_V2_COMMAND_SPEECH_STARTED", vad=round(vad_score, 4))
                    continue
                start_timeout = (
                    float(self.config.command_start_timeout_seconds)
                    if start_timeout_seconds is None
                    else max(0.15, float(start_timeout_seconds))
                )
                if elapsed >= start_timeout:
                    return None
                continue

            frames.append(frame.copy())
            if is_speech:
                silence_seconds = 0.0
            else:
                silence_seconds += frame_seconds
                if (
                    silence_seconds >= float(self.config.command_silence_seconds)
                    and monotonic() - speech_started_at >= float(self.config.command_min_seconds)
                ):
                    break

        if not frames:
            return None

        path = self._write_wav16(frames)
        try:
            if self.before_stt_callback is not None:
                try:
                    handoff = self.before_stt_callback()
                    self.events.emit("VOICE_V2_VRAM_TO_STT", result=handoff)
                except Exception as exc:
                    self.events.emit(
                        "VOICE_V2_VRAM_TO_STT_FAILED",
                        error=f"{type(exc).__name__}: {exc}",
                    )
            self.events.emit("VOICE_V2_STT_STARTED", path=str(path))
            result = self.transcribe_callback(path)
            self._last_stt_at = monotonic()
            self._stt_released_after_idle = False
            self._commands_transcribed += 1
            if not result.get("ok"):
                self.events.emit("VOICE_V2_STT_FAILED", result=result)
                return None
            text = str(result.get("text") or "").strip()
            self._last_command = text or None
            self.events.emit(
                "VOICE_V2_STT_FINISHED",
                text=text,
                raw_text=result.get("raw_text") or text,
                elapsed_ms=result.get("elapsed_ms"),
            )
            return text or None
        finally:
            if self.cleanup_callback:
                self.cleanup_callback(path)
            else:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # "Cala-te" template on the SAME stream (no second audio backend)
    # ------------------------------------------------------------------
    @property
    def interrupt_template_path(self) -> Path:
        return Path(self.config.interrupt_template_path)

    def _load_interrupt_templates(self) -> None:
        path = self.interrupt_template_path
        self._interrupt_templates = []
        self._interrupt_threshold = float(self.config.interrupt_match_floor)
        if not path.exists():
            return
        try:
            data = np.load(path, allow_pickle=False)
            count = int(data["count"])
            self._interrupt_templates = [
                np.asarray(data[f"template_{i}"], dtype=np.float32)
                for i in range(count)
            ]
            self._interrupt_threshold = float(data.get("threshold", self.config.interrupt_match_floor))
        except Exception as exc:
            self._last_error = f"INTERRUPT_TEMPLATE_LOAD: {type(exc).__name__}: {exc}"

    def interrupt_enrolled(self) -> bool:
        return len(self._interrupt_templates) >= 3

    def _interrupt_match(self, samples16: np.ndarray) -> float:
        if not self._interrupt_templates:
            return 0.0
        # VoiceV2Config exposes the feature fields used by acoustic_features.
        trimmed = _trim_voice(
            np.asarray(samples16, dtype=np.float32) / 32768.0,
            int(self.config.feature_sample_rate),
        )
        duration = float(trimmed.size) / float(self.config.feature_sample_rate) if trimmed.size else 0.0
        if duration < 0.22 or duration > 1.9:
            return 0.0
        features = acoustic_features(
            trimmed,
            int(self.config.feature_sample_rate),
            self.config,  # duck-typed feature settings
            trim=False,
        )
        if features.shape[0] < 4:
            return 0.0
        scores = [feature_similarity(t, features) for t in self._interrupt_templates]
        return max(scores) if scores else 0.0

    def _process_interrupt_frame(self, frame16: np.ndarray, vad_score: float) -> bool:
        if not self.interrupt_enrolled() or self.on_interrupt is None:
            return False
        speech = vad_score >= max(0.38, float(self.config.command_vad_threshold) - 0.06)
        if speech:
            if not self._interrupt_vad_active:
                self._interrupt_vad_active = True
                self._interrupt_frames = []
            self._interrupt_frames.append(frame16.copy())
            self._interrupt_silence_frames = 0
            if len(self._interrupt_frames) > 24:  # <2 s at 80 ms frames
                self._interrupt_frames = self._interrupt_frames[-24:]
            return False

        if not self._interrupt_vad_active:
            return False
        self._interrupt_silence_frames += 1
        if self._interrupt_silence_frames < 3:
            return False

        frames = self._interrupt_frames
        self._interrupt_vad_active = False
        self._interrupt_frames = []
        self._interrupt_silence_frames = 0
        if not frames:
            return False
        samples = np.concatenate(frames)
        score = self._interrupt_match(samples)
        self.events.emit("VOICE_V2_INTERRUPT_CHECK", score=round(score, 4), threshold=round(self._interrupt_threshold, 4))
        if score >= float(self._interrupt_threshold):
            self.events.emit("VOICE_V2_INTERRUPT_CONFIRMED", score=round(score, 4))
            self.on_interrupt()
            return True
        return False

    def enroll_interrupt(self, wav_paths: list[str | Path]) -> dict[str, Any]:
        if len(wav_paths) < 3:
            return {"ok": False, "error": "INTERRUPT_ENROLL_TOO_FEW_SAMPLES"}
        templates: list[np.ndarray] = []
        durations: list[float] = []
        for wav_path in wav_paths:
            with wave.open(str(wav_path), "rb") as wf:
                channels = wf.getnchannels()
                width = wf.getsampwidth()
                rate = wf.getframerate()
                raw = wf.readframes(wf.getnframes())
            if width != 2:
                return {"ok": False, "error": "INTERRUPT_ENROLL_REQUIRES_PCM16"}
            values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            if channels > 1:
                values = values.reshape(-1, channels).mean(axis=1)
            values = _trim_voice(
                _resample_linear(values, int(rate), int(self.config.feature_sample_rate)),
                int(self.config.feature_sample_rate),
            )
            duration = float(values.size) / float(self.config.feature_sample_rate) if values.size else 0.0
            if duration < 0.25 or duration > 1.8:
                return {"ok": False, "error": "INTERRUPT_ENROLL_BAD_DURATION", "duration_seconds": round(duration, 3)}
            features = acoustic_features(values, int(self.config.feature_sample_rate), self.config, trim=False)
            templates.append(features)
            durations.append(duration)

        pair_scores = [
            feature_similarity(templates[i], templates[j])
            for i in range(len(templates))
            for j in range(i + 1, len(templates))
        ]
        mean_score = float(np.mean(pair_scores)) if pair_scores else 0.0
        min_score = float(np.min(pair_scores)) if pair_scores else 0.0
        threshold = min(
            0.92,
            max(
                float(self.config.interrupt_match_floor),
                mean_score - 0.10,
                min_score - 0.06,
            ),
        )
        path = self.interrupt_template_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "count": np.asarray(len(templates), dtype=np.int32),
            "threshold": np.asarray(threshold, dtype=np.float32),
        }
        for i, (template, duration) in enumerate(zip(templates, durations)):
            payload[f"template_{i}"] = template
            payload[f"duration_{i}"] = np.asarray(duration, dtype=np.float32)
        np.savez_compressed(path, **payload)
        self._interrupt_templates = templates
        self._interrupt_threshold = threshold
        self.events.emit("VOICE_INTERRUPT_PROFILE_ENROLLED", samples=len(templates), threshold=round(threshold, 4), mean_similarity=round(mean_score, 4))
        return {"ok": True, "samples": len(templates), "threshold": round(threshold, 4), "mean_similarity": round(mean_score, 4), "profile": str(path)}

    def delete_interrupt_profile(self) -> bool:
        existed = self.interrupt_template_path.exists()
        try:
            self.interrupt_template_path.unlink(missing_ok=True)
        except OSError:
            pass
        self._interrupt_templates = []
        self._interrupt_threshold = float(self.config.interrupt_match_floor)
        return existed

    def _read_wav_mono_float(self, path: str | Path) -> tuple[np.ndarray, int]:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if width != 2:
            raise ValueError("WAKE_ENROLL_REQUIRES_PCM16")
        values = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        if channels > 1:
            values = values.reshape(-1, channels).mean(axis=1)
        return values.reshape(-1), int(rate)

    def enroll(self, wav_paths: list[str | Path]) -> dict[str, Any]:
        """Enroll the OWNER's natural ``Jarvis`` pronunciation for v2."""
        if len(wav_paths) < 3:
            return {"ok": False, "error": "WAKE_ENROLL_TOO_FEW_SAMPLES"}
        templates: list[np.ndarray] = []
        durations: list[float] = []
        for wav_path in wav_paths:
            samples, rate = self._read_wav_mono_float(wav_path)
            trimmed = _trim_voice(
                _resample_linear(samples, rate, int(self.config.feature_sample_rate)),
                int(self.config.feature_sample_rate),
            )
            duration = float(trimmed.size) / float(self.config.feature_sample_rate) if trimmed.size else 0.0
            if duration < 0.25 or duration > 1.80:
                return {
                    "ok": False,
                    "error": "WAKE_ENROLL_BAD_DURATION",
                    "duration_seconds": round(duration, 3),
                    "message": "Cada amostra deve conter apenas a palavra 'Jarvis'.",
                }
            features = acoustic_features(
                trimmed, int(self.config.feature_sample_rate), self.config, trim=False
            )
            if features.shape[0] < 8:
                return {"ok": False, "error": "WAKE_ENROLL_FEATURES_TOO_SHORT"}
            templates.append(features)
            durations.append(duration)

        pair_scores = [
            feature_similarity(templates[i], templates[j])
            for i in range(len(templates))
            for j in range(i + 1, len(templates))
        ]
        if not pair_scores:
            return {"ok": False, "error": "WAKE_ENROLL_SCORE_ERROR"}
        mean_score = float(np.mean(pair_scores))
        min_score = float(np.min(pair_scores))
        if mean_score < 0.60:
            return {
                "ok": False,
                "error": "WAKE_ENROLL_INCONSISTENT",
                "mean_similarity": round(mean_score, 4),
                "min_similarity": round(min_score, 4),
                "message": "As amostras ficaram demasiado diferentes; repete o registo na posição habitual.",
            }
        calibrated = min(
            0.90,
            max(
                float(self.config.wake_match_floor),
                min_score - float(self.config.wake_match_margin),
                mean_score - 0.11,
            ),
        )
        path = self.wake_template_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "count": np.asarray(len(templates), dtype=np.int32),
            "threshold": np.asarray(calibrated, dtype=np.float32),
        }
        for i, (template, duration) in enumerate(zip(templates, durations)):
            payload[f"template_{i}"] = template
            payload[f"duration_{i}"] = np.asarray(duration, dtype=np.float32)
        np.savez_compressed(path, **payload)
        self._load_wake_templates()
        self._reset_owner_wake_capture()
        self.events.emit(
            "VOICE_V2_OWNER_WAKE_PROFILE_ENROLLED",
            samples=len(templates),
            threshold=round(calibrated, 4),
            mean_similarity=round(mean_score, 4),
            min_similarity=round(min_score, 4),
        )
        return {
            "ok": True,
            "backend": "voice-v2-owner-template",
            "samples": len(templates),
            "threshold": round(calibrated, 4),
            "mean_similarity": round(mean_score, 4),
            "min_similarity": round(min_score, 4),
            "profile": str(path),
        }

    def test_wake_file(self, wav_path: str | Path) -> dict[str, Any]:
        """Offline diagnostic for a manually captured 'Jarvis' sample."""
        try:
            samples, rate = self._read_wav_mono_float(wav_path)
            resampled = _resample_linear(
                samples, rate, int(self.config.feature_sample_rate)
            )
            pcm = np.clip(resampled * 32768.0, -32768, 32767).astype(np.int16)
            matched, score = self._owner_wake_match(pcm)
            return {
                "ok": True,
                "owner_profile_configured": self.owner_wake_enrolled(),
                "score": round(float(score), 4),
                "threshold": round(float(self._wake_template_threshold), 4),
                "accepted": bool(matched),
                "duration_seconds": round(float(pcm.size) / float(self.config.feature_sample_rate), 3),
            }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def delete_profile(self) -> bool:
        path = self.wake_template_path
        existed = path.exists()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self._wake_templates = []
        self._wake_template_durations = []
        self._wake_template_threshold = float(self.config.wake_match_floor)
        self._reset_owner_wake_capture()
        return existed

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> dict[str, Any]:
        if not self.config.enabled:
            return {"ok": False, "error": "WAKE_DISABLED"}
        if self._thread and self._thread.is_alive():
            return {"ok": True, "already_running": True, "backend": "voice-v2"}
        if not self.configured():
            return {
                "ok": False,
                "error": "VOICE_V2_DEPENDENCIES_MISSING",
                "message": "Executa .\\setup_voice_v2.ps1 e reinicia o JARVIS.",
            }
        try:
            self._load_runtime()
        except Exception as exc:
            return {"ok": False, "error": "VOICE_V2_RUNTIME_FAILED", "message": str(exc)}

        self._stop.clear()
        self._paused.clear()
        self._thread = Thread(target=self._run, name="jarvis-voice-v2", daemon=True)
        self._thread.start()
        return {
            "ok": True,
            "backend": "pyaudiowpatch-wasapi+openwakeword+silero+faster-whisper",
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
            thread.join(timeout=2.5)
        self.events.emit("VOICE_V2_STOPPED")

    def suspend(self, timeout: float = 1.5) -> None:
        self._paused.set()
        deadline = monotonic() + max(0.1, float(timeout))
        while monotonic() < deadline:
            with self._state_lock:
                if not self._stream_active:
                    return
            sleep(0.03)

    def resume(self) -> None:
        self._paused.clear()

    def suppress_audio(self, enabled: bool, *, reason: str = "external", tail_seconds: float | None = None) -> None:
        reason = self._norm(reason) or "external"
        with self._suppression_lock:
            if enabled:
                self._suppression_reasons.add(reason)
                self._suppressed.set()
            else:
                self._suppression_reasons.discard(reason)
                if not self._suppression_reasons:
                    self._suppressed.clear()
                    tail = self.config.tts_tail_seconds if tail_seconds is None else max(0.0, float(tail_seconds))
                    self._ignore_until = max(self._ignore_until, monotonic() + float(tail))

    def _audio_is_suppressed(self) -> bool:
        if self._suppressed.is_set():
            return True
        with self._suppression_lock:
            return monotonic() < self._ignore_until

    def _maybe_release_stt(self) -> None:
        if not self.release_stt_callback:
            return
        if self._stt_released_after_idle or self._last_stt_at <= 0:
            return
        if monotonic() - self._last_stt_at < max(15.0, float(self.config.stt_idle_release_seconds)):
            return
        try:
            result = self.release_stt_callback()
            self._stt_released_after_idle = True
            self.events.emit("VOICE_V2_STT_IDLE_RELEASE", result=result)
        except Exception as exc:
            self.events.emit("VOICE_V2_STT_IDLE_RELEASE_FAILED", error=f"{type(exc).__name__}: {exc}")

    def _run(self) -> None:
        retry = max(0.2, float(self.config.stream_recovery_seconds))
        invalid_device_failures = 0
        retry_now = retry
        while not self._stop.is_set():
            if self._paused.is_set():
                with self._state_lock:
                    self._stream_active = False
                sleep(0.05)
                continue

            p = None
            stream = None
            try:
                self._load_runtime()
                pa = self._pyaudio_module
                p = pa.PyAudio()
                dev = self._select_device(p)
                idx = int(dev["index"])
                name = str(dev.get("name", idx))
                source_rate = int(round(float(dev.get("defaultSampleRate", 48000) or 48000)))
                source_rate = max(8000, source_rate)
                channels = 1
                frames_per_buffer = max(160, int(round(source_rate * float(self.config.frame_ms) / 1000.0)))

                stream = p.open(
                    format=pa.paInt16,
                    channels=channels,
                    rate=source_rate,
                    input=True,
                    input_device_index=idx,
                    frames_per_buffer=frames_per_buffer,
                )
                with self._state_lock:
                    self._stream_active = True
                    self._stream_open_count += 1
                    self._last_device_index = idx
                    self._last_device_name = name
                    self._last_samplerate = source_rate
                    self._device_unavailable = False
                    self._device_failure_count = 0
                    self._device_retry_at = 0.0
                self._last_error = None
                invalid_device_failures = 0
                retry_now = retry
                self.events.emit(
                    "VOICE_V2_STREAM_OPENED",
                    device=idx,
                    device_name=name,
                    source_rate=source_rate,
                    target_rate=int(self.config.target_sample_rate),
                    hostapi="Windows WASAPI",
                )
                self._reset_models()

                # openWakeWord is a streaming model: it needs the beginning of
                # the phrase to build its mel/embedding history.  Do not start
                # feeding it only after VAD is already high, otherwise the first
                # syllables are amputated and scores stay near zero.  Keep a
                # cheap PCM pre-roll while idle; when Silero detects speech,
                # replay that context into openWakeWord and continue through a
                # short post-speech hangover.
                frame_seconds = max(0.02, float(self.config.frame_ms) / 1000.0)
                preroll_frames = max(4, int(round(0.56 / frame_seconds)))
                hangover_frames = max(2, int(round(0.40 / frame_seconds)))
                wake_preroll: deque[np.ndarray] = deque(maxlen=preroll_frames)
                kws_active = False
                kws_hangover = 0

                while not self._stop.is_set() and not self._paused.is_set():
                    frame16 = self._read_frame16(
                        stream,
                        source_rate=source_rate,
                        channels=channels,
                        frames_per_buffer=frames_per_buffer,
                    )
                    vad_score = self._vad_score(frame16)

                    # "Cala-te" remains available while idle and while TTS is
                    # suppressing wake activation. It uses the existing OWNER
                    # acoustic profile but no second microphone stream.
                    if self._process_interrupt_frame(frame16, vad_score):
                        self._ignore_until = monotonic() + float(self.config.rearm_seconds)
                        self._reset_models()
                        continue

                    if self._audio_is_suppressed():
                        self._maybe_release_stt()
                        continue
                    if monotonic() < self._last_activation_at + float(self.config.wake_debounce_seconds):
                        self._maybe_release_stt()
                        continue
                    # 0.27.6: Silero decides when a speech episode starts, but
                    # openWakeWord receives pre-roll so it sees the complete wake
                    # phrase instead of only the tail after the VAD threshold.
                    vad_open = float(vad_score) >= float(self.config.wake_vad_threshold)
                    prediction_frames: list[np.ndarray] = []
                    if not kws_active:
                        wake_preroll.append(np.asarray(frame16, dtype=np.int16).copy())
                        if not vad_open:
                            self._maybe_release_stt()
                            continue
                        kws_active = True
                        kws_hangover = hangover_frames
                        self._reset_models()
                        prediction_frames = list(wake_preroll)
                        wake_preroll.clear()
                    else:
                        prediction_frames = [frame16]
                        if vad_open:
                            kws_hangover = hangover_frames
                        else:
                            kws_hangover -= 1

                    score = 0.0
                    model_key = None
                    for kws_frame in prediction_frames:
                        predictions = self._oww_model.predict(kws_frame)
                        self._wake_checks += 1
                        frame_score, frame_key = self._jarvis_score(predictions)
                        if frame_score >= score:
                            score, model_key = frame_score, frame_key
                    self._last_wake_score = round(score, 4)
                    effective_vad = max(float(vad_score), float(self.config.wake_vad_threshold))
                    wake_ready, gate_reason = self._wake_gate(score, effective_vad)
                    if not wake_ready:
                        if score >= float(self.config.wake_threshold):
                            self.events.emit(
                                "VOICE_V2_WAKE_CANDIDATE_REJECTED",
                                score=round(score, 4),
                                vad=round(vad_score, 4),
                                reason=gate_reason,
                            )
                        if kws_active and kws_hangover <= 0:
                            kws_active = False
                            kws_hangover = 0
                            self._reset_models()
                        self._maybe_release_stt()
                        continue
                    self._detections += 1
                    self._last_activation_at = monotonic()
                    self.events.emit(
                        "VOICE_V2_WAKE_CONFIRMED",
                        score=round(score, 4),
                        model=model_key,
                        vad=round(vad_score, 4),
                        gate=gate_reason,
                    )
                    command = self._capture_command(
                        stream,
                        source_rate=source_rate,
                        channels=channels,
                        frames_per_buffer=frames_per_buffer,
                            start_timeout_seconds=float(self.config.inline_command_grace_seconds),
                    )
                    self._reset_models()
                    self.on_wake(command)
                    self._ignore_until = monotonic() + float(self.config.rearm_seconds)

            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                invalid_device = "invalid device" in self._last_error.lower() or "-9996" in self._last_error
                if invalid_device:
                    invalid_device_failures += 1
                    # PyAudio device indexes are session-local. Re-entering the
                    # loop re-enumerates devices by configured name; back off
                    # while a USB webcam/microphone is physically absent.
                    retry_now = min(60.0, max(retry, retry * (2 ** min(invalid_device_failures, 8))))
                    with self._state_lock:
                        self._device_unavailable = True
                        self._device_failure_count = invalid_device_failures
                        self._device_retry_at = monotonic() + retry_now
                    self.events.emit(
                        "VOICE_V2_DEVICE_BACKOFF",
                        error=self._last_error,
                        failures=invalid_device_failures,
                        retry_seconds=round(retry_now, 2),
                    )
                else:
                    retry_now = retry
                    with self._state_lock:
                        self._device_unavailable = False
                        self._device_failure_count = 0
                        self._device_retry_at = 0.0
                self.events.emit("VOICE_V2_STREAM_ERROR", error=self._last_error)
            finally:
                with self._state_lock:
                    self._stream_active = False
                try:
                    if stream is not None:
                        stream.stop_stream()
                        stream.close()
                except Exception:
                    pass
                try:
                    if p is not None:
                        p.terminate()
                except Exception:
                    pass
            if not self._stop.is_set():
                # A disconnect can back off for up to a minute. Waiting on the
                # stop event keeps shutdown/restart responsive during that wait.
                self._stop.wait(retry_now)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def probe_live_input(self, seconds: float = 0.60) -> dict[str, Any]:
        """Open the exact Voice v2 WASAPI endpoint and prove live PCM arrives.

        This is intentionally implemented on VoiceEngineV2 rather than via the
        legacy/sounddevice microphone probe, so release validation exercises the
        same PyAudioWPatch device selection and stream-open path used by `_run`.
        """
        p = None
        stream = None
        try:
            self._load_runtime()
            pa = self._pyaudio_module
            p = pa.PyAudio()
            dev = self._select_device(p)
            idx = int(dev["index"])
            name = str(dev.get("name", idx))
            source_rate = max(8000, int(round(float(dev.get("defaultSampleRate", 48000) or 48000))))
            frames_per_buffer = max(160, int(round(source_rate * float(self.config.frame_ms) / 1000.0)))
            stream = p.open(
                format=pa.paInt16,
                channels=1,
                rate=source_rate,
                input=True,
                input_device_index=idx,
                frames_per_buffer=frames_per_buffer,
            )
            frame_seconds = frames_per_buffer / float(source_rate)
            count = max(3, int(math.ceil(max(0.25, float(seconds)) / max(0.01, frame_seconds))))
            rms_values: list[float] = []
            for _ in range(count):
                raw = stream.read(frames_per_buffer, exception_on_overflow=False)
                values = np.frombuffer(raw, dtype=np.int16)
                rms_values.append(self._rms_int16(values))
            max_rms = max(rms_values) if rms_values else 0.0
            avg_rms = sum(rms_values) / len(rms_values) if rms_values else 0.0
            min_signal_rms = 0.0001
            ok = bool(max_rms >= min_signal_rms)
            return {
                "ok": ok,
                "backend": "PyAudioWPatch/WASAPI",
                "device": idx,
                "device_name": name,
                "sample_rate": source_rate,
                "frames": count,
                "max_rms": round(max_rms, 8),
                "avg_rms": round(avg_rms, 8),
                "min_signal_rms": min_signal_rms,
                "error": None if ok else "VOICE_V2_DIGITAL_OR_NEAR_SILENCE",
            }
        except Exception as exc:
            return {
                "ok": False,
                "backend": "PyAudioWPatch/WASAPI",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        finally:
            try:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if p is not None:
                    p.terminate()
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            stream = {
                "stream_active": self._stream_active,
                "stream_open_count": self._stream_open_count,
                "device": self._last_device_index,
                "device_name": self._last_device_name,
                "sample_rate": self._last_samplerate,
                "device_unavailable": self._device_unavailable,
                "device_failure_count": self._device_failure_count,
                "device_reconnect_in_seconds": round(
                    max(0.0, self._device_retry_at - monotonic()), 2
                ),
            }
        return {
            "enabled": bool(self.config.enabled),
            "configured": self.configured(),
            "enrolled": self.enrolled(),
            "interrupt_enrolled": self.interrupt_enrolled(),
            "interrupt_threshold": round(self._interrupt_threshold, 4),
            "keyword": self.config.keyword,
            "backend": "voice-v2/openwakeword",
            "capture_backend": "PyAudioWPatch/WASAPI",
            "vad_backend": "Silero ONNX (openWakeWord)",
            "architecture": "wasapi->silero-vad->openwakeword->faster-whisper",
            "custom_wake_model": str(self.config.custom_wake_model_path) if Path(self.config.custom_wake_model_path).is_file() else None,
            "fallback_wake_model": None if Path(self.config.custom_wake_model_path).is_file() else "hey_jarvis",
            "whisper_while_idle": False,
            "wake_match_threshold": float(self.config.wake_threshold),
            "wake_vad_threshold": float(self.config.wake_vad_threshold),
            "wake_strong_threshold": float(self.config.wake_strong_threshold),
            "wake_confirm_frames": int(self.config.wake_confirm_frames),
            "inline_command_grace_seconds": float(self.config.inline_command_grace_seconds),
            "owner_wake_profile": {
                "configured": False,
                "active": False,
                "path": str(self.wake_template_path),
                "templates": len(self._wake_templates),
                "threshold": round(self._wake_template_threshold, 4),
                "last_score": self._wake_profile_last_score,
                "checks": self._wake_profile_checks,
                "last_vad": self._wake_profile_last_vad,
                "last_rms": self._wake_profile_last_rms,
                "fast_accept_threshold": float(self.config.owner_wake_fast_accept_threshold),
                "semantic_confirm": bool(self.config.owner_wake_semantic_confirm),
                "semantic_checks": self._wake_profile_semantic_checks,
                "semantic_rejects": self._wake_profile_semantic_rejects,
                "last_semantic_text": self._wake_profile_last_semantic_text,
                "threshold_source": "profile_calibration",
            },
            "wake_verifier": {
                "configured": False,
                "active": False,
                "path": str(self.config.wake_verifier_path),
                "threshold": float(self.config.wake_verifier_threshold),
                "last_score": self._last_verifier_score,
                "error": self._wake_verifier_error,
                "backend": "numpy-logistic" if self._wake_verifier is not None else None,
            },
            "running": bool(self._thread and self._thread.is_alive()),
            "hard_paused": self._paused.is_set(),
            "audio_suppressed": self._audio_is_suppressed(),
            "detections": self._detections,
            "wake_checks": self._wake_checks,
            "commands_transcribed": self._commands_transcribed,
            "last_wake_score": self._last_wake_score,
            "last_command": self._last_command,
            "last_error": self._last_error or self._runtime_error,
            "stt_idle_release_seconds": float(self.config.stt_idle_release_seconds),
            **stream,
        }

    def doctor(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "backend": "voice-v2",
            "dependencies": {},
            "wasapi_inputs": [],
            "wake_models": [],
        }
        for module in ("pyaudiowpatch", "onnxruntime"):
            try:
                __import__(module)
                result["dependencies"][module] = True
            except Exception as exc:
                result["dependencies"][module] = f"{type(exc).__name__}: {exc}"
        oww_probe = openwakeword_runtime_probe()
        result["openwakeword_compat"] = oww_probe
        result["dependencies"]["openwakeword_inference"] = (
            True if oww_probe.get("ok") else f"{oww_probe.get('error')}: {oww_probe.get('message')}"
        )
        if not all(value is True for value in result["dependencies"].values()):
            result["error"] = "VOICE_V2_DEPENDENCIES_MISSING"
            result["setup"] = ".\\setup_voice_v2.ps1"
            return result
        try:
            self._load_runtime()
            pa = self._pyaudio_module
            with pa.PyAudio() as p:
                rows = self._wasapi_devices(p)
            result["wasapi_inputs"] = [
                {
                    "index": int(row["index"]),
                    "name": str(row.get("name", "")),
                    "sample_rate": int(round(float(row.get("defaultSampleRate", 0) or 0))),
                    "score": int(row.get("score", 0)),
                }
                for row in rows
            ]
            # Discover loaded openWakeWord model names without depending on a
            # private attribute shape across versions.
            keys: set[str] = set()
            for attr in ("models", "model_inputs", "prediction_buffer"):
                value = getattr(self._oww_model, attr, None)
                if isinstance(value, dict):
                    keys.update(str(x) for x in value.keys())
            result["wake_models"] = sorted(keys)
            result["jarvis_model_detected"] = any("jarvis" in self._norm(k) for k in keys) if keys else True
            result["selected_device"] = result["wasapi_inputs"][0] if result["wasapi_inputs"] else None
            result["ok"] = bool(result["wasapi_inputs"]) and bool(result["jarvis_model_detected"])
            if not result["ok"]:
                result["error"] = "VOICE_V2_NO_USABLE_WASAPI_OR_JARVIS_MODEL"
            return result
        except Exception as exc:
            result["error"] = type(exc).__name__
            result["message"] = str(exc)
            return result

    def benchmark(self, frames: int = 40) -> dict[str, Any]:
        try:
            self._load_runtime()
            count = max(10, min(200, int(frames)))
            sample_count = int(self.config.target_sample_rate * self.config.frame_ms / 1000)
            probe = np.zeros(sample_count, dtype=np.int16)
            started = monotonic()
            max_score = 0.0
            for _ in range(count):
                pred = self._oww_model.predict(probe)
                score, _ = self._jarvis_score(pred)
                max_score = max(max_score, score)
            elapsed = monotonic() - started
            per_frame_ms = (elapsed * 1000.0) / count
            audio_ms = float(self.config.frame_ms)
            return {
                "ok": True,
                "frames": count,
                "audio_ms_per_frame": audio_ms,
                "inference_ms_per_frame": round(per_frame_ms, 3),
                "realtime_headroom_x": round(audio_ms / max(0.001, per_frame_ms), 2),
                "max_silence_score": round(max_score, 5),
                "backend": "openwakeword+silero/onnx-cpu",
            }
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}
