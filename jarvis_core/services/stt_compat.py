from __future__ import annotations

from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace
from typing import Any
import sys
import wave


WHISPER_SAMPLE_RATE = 16000
_PYAV_STUB_MARKER = "__jarvis_pcm_only_pyav_stub__"
_IMPORT_LOCK = Lock()
_CACHED_WHISPER_MODEL = None


class PyAVDecodeUnavailable(RuntimeError):
    """Raised only if faster-whisper tries to decode media through the PyAV shim."""


def _pyav_decode_unavailable(*_args, **_kwargs):
    raise PyAVDecodeUnavailable(
        "PyAV decoding is disabled for the JARVIS microphone path. "
        "JARVIS supplies 16 kHz float32 PCM directly to faster-whisper."
    )


class _UnavailableFactory:
    def __call__(self, *_args, **_kwargs):
        return _pyav_decode_unavailable()

    def __getattr__(self, _name: str):
        return _pyav_decode_unavailable()


class _InvalidDataError(Exception):
    pass


def _build_pyav_stub() -> ModuleType:
    """
    Build the smallest object faster-whisper.audio needs at import time.

    faster-whisper currently imports ``av`` at module import time even when the
    caller supplies an already-decoded NumPy waveform. Smart App Control can
    therefore block PyAV before the microphone PCM path is reached. This stub
    exists only during faster-whisper import; faster_whisper.audio retains the
    reference afterwards, while ``sys.modules['av']`` is restored immediately.

    Any attempt to use file/media decoding through this stub fails closed.
    """
    module = ModuleType("av")
    setattr(module, _PYAV_STUB_MARKER, True)
    module.open = _pyav_decode_unavailable  # type: ignore[attr-defined]
    module.error = SimpleNamespace(InvalidDataError=_InvalidDataError)  # type: ignore[attr-defined]
    module.audio = SimpleNamespace(  # type: ignore[attr-defined]
        resampler=SimpleNamespace(AudioResampler=_UnavailableFactory()),
        fifo=SimpleNamespace(AudioFifo=_UnavailableFactory()),
    )
    return module


def load_whisper_model_class():
    """
    Import ``faster_whisper.WhisperModel`` without requiring PyAV to load.

    Security properties:
    - does not change Windows policy;
    - does not unblock or modify third-party binaries;
    - does not fake successful media decoding;
    - the shim is temporary in ``sys.modules`` and fails closed if decoding is
      accidentally requested.
    """
    global _CACHED_WHISPER_MODEL
    if _CACHED_WHISPER_MODEL is not None:
        return _CACHED_WHISPER_MODEL

    with _IMPORT_LOCK:
        if _CACHED_WHISPER_MODEL is not None:
            return _CACHED_WHISPER_MODEL

        existing_av = sys.modules.get("av")
        installed_stub = existing_av is None
        stub = None
        if installed_stub:
            stub = _build_pyav_stub()
            sys.modules["av"] = stub

        try:
            from faster_whisper import WhisperModel
        finally:
            if installed_stub and sys.modules.get("av") is stub:
                sys.modules.pop("av", None)

        _CACHED_WHISPER_MODEL = WhisperModel
        return WhisperModel


def load_wav_pcm_float32(
    wav_path: str | Path,
    *,
    target_rate: int = WHISPER_SAMPLE_RATE,
) -> tuple[Any, dict[str, Any]]:
    """
    Read a PCM WAV with the standard library and return mono float32 NumPy PCM.

    JARVIS microphone captures are mono signed 16-bit PCM. A small amount of
    defensive support is kept for 8-bit and 32-bit PCM so older captures can
    still be transcribed. 24-bit PCM is rejected instead of being guessed.
    """
    import numpy as np

    path = Path(wav_path)
    with wave.open(str(path), "rb") as stream:
        channels = int(stream.getnchannels())
        sample_width = int(stream.getsampwidth())
        source_rate = int(stream.getframerate())
        frame_count = int(stream.getnframes())
        compression = str(stream.getcomptype())
        raw = stream.readframes(frame_count)

    if compression != "NONE":
        raise ValueError(f"WAV_COMPRESSION_UNSUPPORTED:{compression}")
    if channels < 1:
        raise ValueError("WAV_CHANNELS_INVALID")
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError("WAV_SAMPLE_RATE_INVALID")

    if sample_width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sample_width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"WAV_SAMPLE_WIDTH_UNSUPPORTED:{sample_width}")

    if samples.size == 0:
        return np.asarray([], dtype=np.float32), {
            "source_rate": source_rate,
            "target_rate": int(target_rate),
            "channels": channels,
            "sample_width": sample_width,
            "resampled": source_rate != int(target_rate),
            "samples": 0,
        }

    if samples.size % channels != 0:
        raise ValueError("WAV_FRAME_ALIGNMENT_INVALID")

    if channels > 1:
        samples = samples.reshape((-1, channels)).mean(axis=1, dtype=np.float32)

    target_rate = int(target_rate)
    resampled = source_rate != target_rate
    if resampled and samples.size > 1:
        target_size = max(1, int(round(samples.size * target_rate / source_rate)))
        source_positions = np.arange(samples.size, dtype=np.float64)
        target_positions = np.linspace(
            0.0,
            float(samples.size - 1),
            num=target_size,
            dtype=np.float64,
        )
        samples = np.interp(target_positions, source_positions, samples).astype(np.float32)
    else:
        samples = samples.astype(np.float32, copy=False)

    samples = np.ascontiguousarray(samples, dtype=np.float32)
    return samples, {
        "source_rate": source_rate,
        "target_rate": target_rate,
        "channels": channels,
        "sample_width": sample_width,
        "resampled": resampled,
        "samples": int(samples.size),
    }


def probe_faster_whisper_pcm_import() -> dict[str, Any]:
    """Read-only import probe used by setup/preflight diagnostics."""
    try:
        model_class = load_whisper_model_class()
        return {
            "ok": True,
            "status": "ok",
            "component": "faster_whisper_pcm",
            "class_name": getattr(model_class, "__name__", "WhisperModel"),
            "pyav_required": False,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "blocked_or_unavailable",
            "component": "faster_whisper_pcm",
            "error": type(exc).__name__,
            "message": str(exc)[:500],
            "pyav_required": False,
        }
