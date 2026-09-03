from __future__ import annotations

from typing import Any


_WEBCAM_AUDIO_MARKERS = (
    "webcam",
    "camera",
    "cam ",
    " cam",
    "usb camera",
    "usb video",
    "usb audio device",
    "usb microphone",
    "microphone (usb",
    "microfone (usb",
    "hd pro webcam",
    "hd webcam",
    "streamcam",
    "lifecam",
    "brio",
    "c920",
    "c922",
    "c925",
    "c930",
    "kiyo",
    "obsbot",
    "insta360",
    "emeet",
    "ausdom",
    "depstech",
)


def webcam_audio_score(name: str, hint: str = "") -> int:
    """Return a conservative score for webcam-integrated audio endpoints.

    Explicit OWNER hints win. Generic USB audio is considered, but scores below
    a name that explicitly mentions webcam/camera. This is intentionally only a
    ranking signal; opening the PortAudio stream remains the final authority.
    """
    text = str(name or "").strip().lower()
    wanted = str(hint or "").strip().lower()
    if not text:
        return 0

    score = 0
    if wanted and wanted in text:
        score += 5000

    if "webcam" in text or "camera" in text:
        score += 2600
    if any(marker in text for marker in _WEBCAM_AUDIO_MARKERS):
        score += 1700
    if "microphone" in text or "microfone" in text or "mic" in text:
        score += 120
    if "usb" in text:
        score += 180

    # Bluetooth headset endpoints must not accidentally beat an obvious webcam.
    if "hands-free" in text or "headset" in text or "bluetooth" in text:
        score -= 500
    return score


def is_probable_webcam_audio(name: str, hint: str = "") -> bool:
    return webcam_audio_score(name, hint) >= 1200


def summarize_audio_device(index: int, dev: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(index),
        "name": str(dev.get("name", "")),
        "input_channels": int(dev.get("max_input_channels", 0) or 0),
        "default_samplerate": int(float(dev.get("default_samplerate", 0) or 0)),
        "hostapi": str(dev.get("_hostapi_name", "")),
    }
