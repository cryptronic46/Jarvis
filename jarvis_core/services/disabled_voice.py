from __future__ import annotations


def _disabled_result() -> dict:
    return {
        "ok": True,
        "skipped": "local_voice_disabled",
    }


class _Config:
    def __init__(self, **values) -> None:
        self.__dict__.update(values)


class DisabledSpeechService:
    """No-audio contract used when PC-local speech is retired."""

    def __init__(self) -> None:
        self.config = _Config(enabled=False)

    def start(self):
        return _disabled_result()

    def shutdown(self):
        return _disabled_result()

    def say(self, *_args, **_kwargs) -> bool:
        return False

    def stop(self, *_args, **_kwargs):
        return _disabled_result()

    def status(self) -> dict:
        return {
            "ok": True,
            "enabled": False,
            "speaking": False,
            "queued": 0,
            "reason": "local_voice_disabled",
        }

    def pause_for_bargein(self) -> bool:
        return False

    def resume_after_bargein(self) -> bool:
        return False

    def test_phrase(self):
        return _disabled_result()

    def set_enabled(self, _enabled: bool) -> bool:
        return False


class DisabledMicrophoneService:
    """No-device STT contract. Never opens an input device."""

    def __init__(self, settings) -> None:
        self.config = _Config(
            device=None,
            language=settings.stt_language,
            model=settings.stt_model,
            stt_device=settings.stt_device,
            command_beam_size=settings.wake_stt_beam_size,
            command_retry_beam_size=settings.wake_stt_retry_beam_size,
            normalize_command_audio=settings.stt_normalize_command_audio,
            command_target_rms=settings.stt_command_target_rms,
            command_max_gain=settings.stt_command_max_gain,
            preferred_device_index=None,
            preferred_device_name="",
            preferred_samplerate=0,
            prefer_webcam_audio=False,
            webcam_name_hint="",
        )

    def status(self) -> dict:
        return {
            "ok": True,
            "enabled": False,
            "device": None,
            "model_backend": None,
            "reason": "local_voice_disabled",
        }

    def stt_residency_status(self) -> dict:
        return {
            "ok": True,
            "loaded": False,
            "backend": None,
            "device_preference": None,
            "reason": "local_voice_disabled",
        }

    def release_stt(self):
        return _disabled_result()

    def preload_stt(self):
        return _disabled_result()

    def capture_phrase(self):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def transcribe_command_file(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def transcribe_wake_file(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def cleanup_capture(self, *_args, **_kwargs):
        return _disabled_result()

    def list_devices(self) -> list:
        return []

    def probe_devices(self, *_args, **_kwargs) -> list:
        return []

    def select_best_probe(self, _rows):
        return None

    def _input_device_candidates(self) -> list:
        return []

    def set_device(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }


class DisabledSpeakerVerifier:
    """Voice-ID contract that can never authenticate or load a model."""

    def __init__(self) -> None:
        self.config = _Config(enabled=False)

    def status(self) -> dict:
        return {
            "ok": True,
            "enabled": False,
            "enrolled": False,
            "reason": "local_voice_disabled",
        }

    def enrolled(self) -> bool:
        return False

    def ensure_ready(self):
        return _disabled_result()

    def set_enabled(self, _enabled: bool) -> bool:
        return False

    def verify(self, *_args, **_kwargs):
        return {
            "ok": False,
            "accepted": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def set_threshold(self, value: float) -> float:
        return float(value)

    def delete_profile(self) -> bool:
        return False

    def enroll(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }


class DisabledWakeService:
    """Wake contract used by Core observability while audio is absent."""

    def __init__(self, settings) -> None:
        self.config = _Config(
            enabled=False,
            command_silence_seconds=settings.wake_command_silence_seconds,
            command_preroll_seconds=settings.wake_command_preroll_seconds,
            command_threshold_ratio=settings.wake_command_threshold_ratio,
            preferred_device_index=None,
            preferred_device_name="",
            preferred_samplerate=0,
            prefer_webcam_audio=False,
            webcam_name_hint="",
        )

    def status(self) -> dict:
        return {
            "ok": True,
            "enabled": False,
            "running": False,
            "device": None,
            "last_command": None,
            "reason": "local_voice_disabled",
        }

    def configured(self) -> bool:
        return False

    def enrolled(self) -> bool:
        return False

    def interrupt_enrolled(self) -> bool:
        return False

    def start(self):
        return _disabled_result()

    def stop(self):
        return _disabled_result()

    def suspend(self):
        return _disabled_result()

    def resume(self):
        return _disabled_result()

    def suppress_audio(self, *_args, **_kwargs):
        return _disabled_result()

    def doctor(self):
        return _disabled_result()

    def benchmark(self):
        return _disabled_result()

    def delete_profile(self) -> bool:
        return False

    def enroll(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def test_wake_file(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def enroll_interrupt(self, *_args, **_kwargs):
        return {
            "ok": False,
            "error": "LOCAL_VOICE_DISABLED",
        }

    def delete_interrupt_profile(self) -> bool:
        return False


class DisabledListeningWatchdog:
    """No-thread listening watchdog contract."""

    def __init__(self) -> None:
        self._armed = False

    def start(self):
        return _disabled_result()

    def stop(self):
        return _disabled_result()

    def set_armed(self, armed: bool) -> None:
        self._armed = bool(armed)

    def status(self) -> dict:
        return {
            "ok": True,
            "enabled": False,
            "armed": False,
            "running": False,
            "reason": "local_voice_disabled",
        }

    def recover(self, *_args, **_kwargs):
        return _disabled_result()
