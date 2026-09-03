from __future__ import annotations

from typing import Any

from jarvis_core.services.listening import ListeningConfig
from jarvis_core.services.voice_engine_v2 import VoiceV2Config
from jarvis_core.services.speaker_verification import SpeakerConfig


def listening_config_from_settings(settings: Any, *, voice_v2: bool = False) -> ListeningConfig:
    """Build the microphone/STT config used by the live runtime and validation.

    0.27.6 centralizes this mapping so the acceptance validator cannot silently
    exercise a different Faster-Whisper configuration from the CLI runtime.
    """
    return ListeningConfig(
        device=settings.mic_device,
        language=settings.stt_language,
        model=settings.voice_v2_stt_model if voice_v2 else settings.stt_model,
        stt_device=settings.voice_v2_stt_device if voice_v2 else settings.stt_device,
        download_root=settings.stt_download_root,
        calibration_seconds=settings.mic_calibration_seconds,
        start_timeout_seconds=settings.mic_start_timeout_seconds,
        max_phrase_seconds=settings.mic_max_phrase_seconds,
        silence_seconds=settings.mic_silence_seconds,
        threshold_multiplier=settings.mic_threshold_multiplier,
        threshold_floor=settings.mic_threshold_floor,
        beam_size=settings.stt_beam_size,
        wake_candidate_beam_size=settings.wake_candidate_beam_size,
        command_beam_size=settings.wake_stt_beam_size,
        command_retry_beam_size=settings.wake_stt_retry_beam_size,
        command_low_confidence_avg_logprob=settings.wake_stt_low_confidence_avg_logprob,
        command_low_confidence_no_speech=settings.wake_stt_low_confidence_no_speech,
        command_reject_avg_logprob=settings.wake_stt_reject_avg_logprob,
        command_reject_no_speech=settings.wake_stt_reject_no_speech,
        wake_reject_avg_logprob=settings.wake_candidate_reject_avg_logprob,
        wake_reject_no_speech=settings.wake_candidate_reject_no_speech,
        normalize_command_audio=settings.stt_normalize_command_audio,
        command_target_rms=settings.stt_command_target_rms,
        command_max_gain=settings.stt_command_max_gain,
        command_trim_silence=settings.stt_command_trim_silence,
        command_trim_padding_ms=settings.stt_command_trim_padding_ms,
        command_trim_floor_rms=settings.stt_command_trim_floor_rms,
        command_initial_prompt=settings.wake_stt_initial_prompt,
        command_hotwords=settings.wake_stt_hotwords,
        stream_retries=settings.mic_stream_retries,
        stream_recovery_seconds=settings.mic_stream_recovery_seconds,
        no_signal_rms=settings.mic_no_signal_rms,
        cpu_threads=settings.stt_cpu_threads,
        calibration_cache_seconds=settings.mic_calibration_cache_seconds,
        cached_calibration_blocks=settings.mic_cached_calibration_blocks,
        preferred_device_index=settings.mic_device,
        preferred_device_name=settings.mic_preferred_device_name,
        preferred_handsfree=settings.mic_preferred_handsfree,
        preferred_samplerate=settings.mic_preferred_samplerate,
        prefer_webcam_audio=settings.av_webcam_primary_enabled,
        webcam_name_hint=settings.av_webcam_name_hint,
        probe_min_signal_rms=settings.av_probe_min_signal_rms,
        verified_signal_ttl_seconds=settings.av_verified_signal_ttl_seconds,
    )


def voice_v2_config_from_settings(settings: Any, *, preferred_device_name: str = "") -> VoiceV2Config:
    """Build the exact Voice Engine v2 config used by the live runtime."""
    return VoiceV2Config(
        enabled=settings.wake_enabled,
        auto_start=settings.wake_auto_start,
        keyword=settings.wake_keyword,
        preferred_device_index=None,
        preferred_device_name=(
            settings.voice_v2_device_name
            or preferred_device_name
            or settings.av_webcam_name_hint
        ),
        prefer_webcam_audio=settings.av_webcam_primary_enabled,
        webcam_name_hint=settings.av_webcam_name_hint,
        frame_ms=settings.voice_v2_frame_ms,
        wake_threshold=settings.voice_v2_wake_threshold,
        custom_wake_model_path=settings.voice_v2_custom_wake_model_path,
        wake_vad_threshold=settings.voice_v2_wake_vad_threshold,
        wake_strong_threshold=settings.voice_v2_wake_strong_threshold,
        wake_confirm_frames=settings.voice_v2_wake_confirm_frames,
        wake_confirm_window_seconds=settings.voice_v2_wake_confirm_window_seconds,
        inline_command_grace_seconds=settings.voice_v2_inline_command_grace_seconds,
        wake_debounce_seconds=settings.voice_v2_debounce_seconds,
        command_start_timeout_seconds=settings.wake_command_start_timeout_seconds,
        command_silence_seconds=settings.wake_command_silence_seconds,
        command_max_seconds=settings.wake_command_max_seconds,
        command_min_seconds=settings.wake_command_min_seconds,
        command_preroll_seconds=settings.wake_command_preroll_seconds,
        command_vad_threshold=settings.voice_v2_command_vad_threshold,
        command_threshold_ratio=settings.wake_command_threshold_ratio,
        tts_tail_seconds=settings.wake_tts_tail_seconds,
        rearm_seconds=settings.wake_rearm_seconds,
        stream_recovery_seconds=settings.mic_stream_recovery_seconds,
        interrupt_template_path=settings.interrupt_template_path,
        interrupt_enrollment_samples=settings.interrupt_enrollment_samples,
        interrupt_match_floor=settings.interrupt_match_floor,
        feature_sample_rate=settings.wake_feature_sample_rate,
        feature_frame_ms=settings.wake_feature_frame_ms,
        feature_hop_ms=settings.wake_feature_hop_ms,
        feature_bands=settings.wake_feature_bands,
        stt_idle_release_seconds=settings.voice_v2_stt_idle_release_seconds,
        wake_verifier_path=settings.voice_v2_verifier_path,
        wake_verifier_threshold=settings.voice_v2_verifier_threshold,
        wake_template_path=settings.wake_template_path,
        wake_match_floor=settings.voice_v2_owner_wake_floor,
        wake_match_margin=settings.wake_match_margin,
        wake_start_slack_seconds=settings.wake_start_slack_seconds,
        owner_wake_fast_accept_threshold=settings.voice_v2_owner_fast_accept_threshold,
        owner_wake_semantic_confirm=settings.voice_v2_owner_semantic_confirm,
        owner_wake_max_phrase_seconds=settings.voice_v2_owner_max_phrase_seconds,
    )


def speaker_config_from_settings(settings: Any) -> SpeakerConfig:
    """Build the same Voice Lock configuration for runtime and validation."""
    return SpeakerConfig(
        enabled=settings.speaker_lock_enabled,
        profile_name=settings.speaker_profile_name,
        profile_dir=settings.speaker_profile_dir,
        model_path=settings.speaker_model_path,
        model_sha256=settings.speaker_model_sha256,
        threshold=settings.speaker_threshold,
        min_seconds=settings.speaker_min_seconds,
        enrollment_samples=settings.speaker_enrollment_samples,
    )
