from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os


@dataclass(slots=True)
class Settings:
    assistant_name: str = "JARVIS"
    user_name: str = "Tiago"
    language: str = "pt-PT"
    # 0.27.8: JARVIS owns reasoning/orchestration and selects a local executor; learning/expert escalation is permission-gated.
    local_llm_backend: str = "jarvis_local"
    local_llm_allow_ollama_compat: bool = True
    local_llm_executor_state_path: str = "memory/local_llm_executor.json"
    native_llama_server_path: str = "runtime/llama.cpp/llama-server.exe"
    native_llama_model_path: str = "models/llm/qwen3-8b.gguf"
    native_llama_host: str = "127.0.0.1"
    native_llama_port: int = 11435
    native_llama_gpu_layers: int = 99
    native_llama_threads: int = 6
    native_llama_flash_attention: bool = False
    native_llama_start_timeout_seconds: float = 45.0
    native_llama_request_timeout_seconds: float = 180.0
    native_llama_state_path: str = "memory/native_llama_runtime.json"
    ollama_host: str = "http://localhost:11434"  # loopback compatibility executor / legacy model cache
    model: str = "qwen3:8b"
    think: bool = True
    think_mode: str = "adaptive"
    max_tool_rounds: int = 5
    history_limit: int = 16
    show_events: bool = False
    log_dir: str = "logs"
    log_max_bytes: int = 8388608
    log_backup_count: int = 6
    ollama_keep_alive: str = "30m"
    ollama_release_on_shutdown: bool = True
    llm_num_ctx: int = 8192
    llm_num_predict: int = 280
    llm_temperature: float = 0.2
    llm_auto_continue_truncated: bool = True
    llm_max_continuations: int = 3
    llm_continuation_num_predict: int = 360
    background_warmup: bool = True
    telemetry_interval_seconds: float = 1.0
    telemetry_history_seconds: int = 120

    # Desktop / Wallpaper Engine integration. The Core only launches known
    # local components and the bridge remains loopback/read-only.
    desktop_integration_enabled: bool = True
    desktop_wallpaper_root: str = ""
    desktop_bridge_auto_start: bool = True
    desktop_bridge_port: int = 8765
    desktop_wallpaper_engine_auto_start: bool = True
    desktop_wallpaper_engine_path: str = ""

    # 0.23 modular capabilities. Built-ins live under jarvis_core/skills;
    # OWNER-trusted external skills live in a persistent runtime folder and are
    # never trusted/installed by the model itself.
    skills_enabled: bool = True
    skills_external_enabled: bool = True
    skills_external_root: str = "skills"
    skills_trust_path: str = "memory/skills_trust.json"

    # Desktop Agent / local screen control. Consequential input primitives are
    # still registered as CONFIRM tools in SecurityPolicy.
    desktop_agent_screenshot_dir: str = "memory/screenshots"
    desktop_agent_max_windows: int = 50

    # Local screen vision. setup_vision.ps1 downloads a pinned GGUF + mmproj
    # pair into models/vision. Inference is served by a second JARVIS-owned
    # llama.cpp process bound to loopback only; no external AI provider is used.
    vision_enabled: bool = True
    vision_model: str = "Qwen2.5-VL-3B-Instruct-Q4_K_M"
    vision_keep_alive: str = "2m"
    vision_native_model_path: str = "models/vision/Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf"
    vision_native_mmproj_path: str = "models/vision/mmproj-Qwen2.5-VL-3B-Instruct-Q8_0.gguf"
    vision_native_port: int = 11436
    vision_native_ctx: int = 8192
    vision_native_gpu_layers: int = 99
    vision_native_threads: int = 6
    vision_native_max_tokens: int = 700
    vision_native_start_timeout_seconds: float = 90.0
    vision_native_request_timeout_seconds: float = 180.0
    vision_native_state_path: str = "memory/native_vision_runtime.json"
    vision_camera_enabled: bool = True
    vision_camera_index: int = 0
    vision_camera_auto_detect: bool = True
    vision_camera_probe_limit: int = 5
    vision_capture_dir: str = "memory/vision"

    # Unified webcam A/V preference. A clearly identified webcam microphone
    # outranks legacy headset preferences, but opening the stream remains the
    # final authority and the old input remains available as fallback.
    av_webcam_primary_enabled: bool = True
    av_webcam_name_hint: str = ""

    # System Guardian continuous host monitoring.
    guardian_enabled: bool = True
    guardian_interval_seconds: float = 120.0
    guardian_baseline_path: str = "memory/guardian_baseline.json"
    guardian_state_path: str = "memory/guardian_state.json"
    guardian_alert_cooldown_seconds: float = 900.0

    # Multi-step autonomous planning and bounded Purple Team orchestration.
    task_planner_state_path: str = "memory/task_plans.json"
    task_planner_max_steps: int = 10
    task_planner_max_adaptations: int = 1
    purple_team_report_path: str = "memory/purple_team_last.json"

    # Long-term relational memory + live Wallpaper state contract.
    memory_graph_path: str = "memory/memory_graph.json"
    wallpaper_live_state_path: str = "memory/live_hud.json"
    wallpaper_live_interval_seconds: float = 2.0

    # 0.25 Voice Engine v2. ``auto`` prefers the mature Windows-native
    # WASAPI/openWakeWord pipeline when its optional dependencies are ready,
    # while retaining the legacy acoustic engine as an explicit fallback.
    voice_input_backend: str = "v2"  # v2 active baseline | legacy explicit compatibility only
    voice_v2_device_name: str = ""
    voice_v2_wake_threshold: float = 0.45
    voice_v2_wake_vad_threshold: float = 0.35
    voice_v2_wake_strong_threshold: float = 0.45
    voice_v2_wake_confirm_frames: int = 1
    voice_v2_wake_confirm_window_seconds: float = 0.15
    voice_v2_inline_command_grace_seconds: float = 0.45
    voice_v2_command_vad_threshold: float = 0.48
    voice_v2_frame_ms: int = 80
    voice_v2_debounce_seconds: float = 1.25
    voice_v2_stt_model: str = "small"
    voice_v2_stt_device: str = "cpu"
    voice_v2_stt_idle_release_seconds: float = 120.0
    voice_v2_preload_stt: bool = True
    voice_v2_vram_handoff_enabled: bool = True
    voice_v2_setup_script: str = "setup_voice_reset.ps1"
    voice_v2_custom_wake_model_path: str = "models/openwakeword/jarvis.onnx"
    # Optional owner-specific wake verifier. Training may run in WSL when
    # Windows App Control blocks SciPy/scikit-learn native extensions; runtime
    # scoring uses NumPy only.
    voice_v2_verifier_path: str = "models/wake_verifier_jarvis.npz"
    voice_v2_verifier_threshold: float = 0.55
    # Separate from the legacy acoustic floor. Voice v2 uses the OWNER's
    # calibrated wake profile plus VAD/energy and temporal confirmation.
    voice_v2_owner_wake_floor: float = 0.58
    voice_v2_owner_fast_accept_threshold: float = 0.70
    voice_v2_owner_semantic_confirm: bool = True
    voice_v2_owner_max_phrase_seconds: float = 1.15

    # Listening resilience. The watchdog only repairs the local wake/audio
    # stream and never executes commands or changes security permissions.
    listening_watchdog_enabled: bool = True
    listening_watchdog_interval_seconds: float = 3.0
    listening_watchdog_stream_grace_seconds: float = 8.0
    listening_watchdog_recovery_cooldown_seconds: float = 15.0

    # 0.24.0 conversational silence + safe activity observability.
    silence_latch_enabled: bool = True
    activity_trace_enabled: bool = True
    activity_trace_live: bool = False
    activity_trace_path: str = "memory/activity_trace.json"
    wake_candidate_whisper_confirm: bool = True
    wake_candidate_beam_size: int = 1
    wake_candidate_reject_cooldown_seconds: float = 0.80
    wake_candidate_window_seconds: float = 1.05
    wake_candidate_tail_seconds: float = 0.06
    wake_candidate_min_avg_logprob: float = -0.55
    wake_candidate_max_no_speech_prob: float = 0.20
    wake_candidate_max_words: int = 2

    speech_enabled: bool = True
    speech_backend: str = "auto"
    speech_voice: str = "pt-PT-RaquelNeural"
    speech_rate: str = "-9%"
    speech_pitch: str = "-8Hz"
    speech_persona_profile: str = "velvet_feminine"
    speech_sapi_prefer_gender: str = "Female"
    speech_volume: str = "+0%"
    speech_max_chars: int = 1600
    speech_fallback_sapi: bool = True
    speech_cache_enabled: bool = True
    speech_cache_dir: str = ".cache/tts"
    speech_cache_max_bytes: int = 268435456
    speech_cache_max_files: int = 500
    mic_device: int | None = None
    stt_language: str = "pt"
    stt_model: str = "small"
    stt_device: str = "cpu"
    # Keep Faster Whisper model snapshots inside the JARVIS installation so a
    # dedicated drive does not spill multi-GB caches into the Windows profile.
    stt_download_root: str = "models/faster-whisper"
    mic_calibration_seconds: float = 0.4
    mic_start_timeout_seconds: float = 8.0
    mic_max_phrase_seconds: float = 14.0
    mic_silence_seconds: float = 0.65
    mic_threshold_multiplier: float = 2.0
    mic_threshold_floor: float = 0.006
    stt_beam_size: int = 1
    wake_stt_beam_size: int = 1
    wake_stt_retry_beam_size: int = 5
    wake_stt_low_confidence_avg_logprob: float = -0.72
    wake_stt_low_confidence_no_speech: float = 0.35
    wake_stt_reject_avg_logprob: float = -1.00
    wake_stt_reject_no_speech: float = 0.55
    wake_candidate_reject_avg_logprob: float = -0.80
    wake_candidate_reject_no_speech: float = 0.40
    stt_normalize_command_audio: bool = True
    stt_command_target_rms: float = 0.08
    stt_command_max_gain: float = 4.0
    stt_command_trim_silence: bool = True
    stt_command_trim_padding_ms: int = 140
    stt_command_trim_floor_rms: float = 0.0025
    wake_stt_initial_prompt: str = (
        "Transcrição fiel em português europeu (pt-PT). Não traduzir. "
        "Preservar nomes próprios, marcas, números e termos técnicos. "
        "O utilizador fala naturalmente com a assistente Jarvis. "
        "Comandos e perguntas podem mencionar Brave, Spotify, Steam, Discord, "
        "Cyberpunk 2077, Windows, Kali Linux, volume, áudio, microfone, webcam, "
        "GPU, gráfica, VRAM, CPU, temperatura, memória, ficheiros e aplicações. "
        "Exemplos de comandos: abre o Brave; fecha o Spotify; mostra a temperatura da GPU."
    )
    wake_stt_hotwords: str = (
        "Jarvis abre abrir fecha fechar mostra diz procura verifica aumenta baixa "
        "liga desliga inicia para escreve clica Brave Spotify Steam Discord Cyberpunk "
        "GPU CPU volume áudio gráfica temperatura"
    )
    stt_cpu_threads: int = 6
    mic_calibration_cache_seconds: float = 180.0
    mic_cached_calibration_blocks: int = 1
    mic_preferred_device_name: str = "GENERAL WEBCAM"
    mic_preferred_handsfree: bool = False
    mic_preferred_samplerate: int = 48000
    mic_stream_retries: int = 2
    mic_stream_recovery_seconds: float = 0.8
    mic_no_signal_rms: float = 0.00015
    av_probe_min_signal_rms: float = 0.001
    av_verified_signal_ttl_seconds: float = 120.0
    speaker_lock_enabled: bool = True
    speaker_profile_name: str = "owner"
    speaker_profile_dir: str = "voice_profiles"
    speaker_model_source: str = "speechbrain/spkrec-ecapa-voxceleb"
    speaker_model_dir: str = "models/spkrec-ecapa-voxceleb"
    speaker_model_path: str = "models/voiceid/3d_speaker-speech_campplus_sv_en_voxceleb_16k.pt"
    speaker_model_sha256: str = "8ebcd0b04c1bb50d5fe77166f9a123206bf08ed14bcfd6a0b95fe8fcb2e25926"
    speaker_threshold: float = 0.45
    speaker_min_seconds: float = 0.7
    speaker_enrollment_samples: int = 5
    # Voice ID remains active, but 0.6 defaults to observation-only until
    # per-user permissions are implemented.
    speaker_enforcement_mode: str = "observe"  # observe | enforce

    # 0.27.8 hotfix: JARVIS/llama.cpp is the only AI reasoning route.
    # External AI is structurally blocked. Public-web research remains allowed
    # through direct HTTPS retrieval followed by local Qwen synthesis.
    external_ai_enabled: bool = False
    hybrid_mode: str = "local"  # compatibility field; runtime is local-first
    cloud_enabled: bool = False
    cloud_model: str = "gpt-5.6-terra"
    cloud_model_deep: str = "gpt-5.6-sol"
    cloud_reasoning: str = "low"
    cloud_reasoning_deep: str = "medium"
    cloud_verbosity: str = "low"
    cloud_web_search: bool = True
    cloud_history_turns: int = 4
    cloud_auto_min_chars: int = 180
    cloud_max_output_tokens: int = 1600
    cloud_max_tool_rounds: int = 4
    cloud_fallback_on_local_error: bool = False
    external_ai_complex_only: bool = True
    external_ai_complexity_threshold: int = 4
    external_ai_auto_escalate_complex: bool = False
    cloud_tool_allowlist: list[str] | None = None

    # Direct Internet research + JARVIS native local synthesis. Web retrieval does not
    # imply external-AI reasoning.
    local_research_enabled: bool = True
    local_research_max_results: int = 6
    local_research_max_sources: int = 4
    local_research_timeout_seconds: float = 8.0
    local_research_search_max_bytes: int = 262144
    local_research_fetch_max_bytes: int = 524288
    local_research_source_max_chars: int = 5000
    local_research_direct_max_pages: int = 4
    local_research_direct_source_max_chars: int = 4500
    local_research_max_output_tokens: int = 900

    # 0.27.8 Epistemic Learning: explicit local knowledge gaps can offer
    # one-shot public-web study. Learned material remains local and is
    # injected only on strong request-scoped matches. External AI is blocked.
    epistemic_learning_enabled: bool = True
    epistemic_learning_rag_enabled: bool = True
    epistemic_learning_stale_days: int = 120
    expert_escalation_enabled: bool = False
    expert_escalation_isolated_payload: bool = True

    # Always-listening wake word.
    wake_enabled: bool = True
    wake_auto_start: bool = True
    wake_keyword: str = "jarvis"
    wake_match_threshold: float = 0.72
    wake_calibration_seconds: float = 0.8
    wake_threshold_multiplier: float = 2.0
    wake_threshold_floor: float = 0.006
    wake_threshold_ceiling: float = 0.040
    wake_silence_seconds: float = 1.20
    wake_max_phrase_seconds: float = 12.0
    wake_pre_roll_seconds: float = 0.40
    wake_block_seconds: float = 0.10
    wake_no_signal_rms: float = 0.00015
    wake_speech_confirm_blocks: int = 2
    wake_min_candidate_seconds: float = 0.40
    wake_min_peak_ratio: float = 1.10
    wake_rejected_cooldown_seconds: float = 0.20
    wake_tts_tail_seconds: float = 0.35
    wake_rearm_seconds: float = 0.20
    wake_enrollment_samples: int = 5
    wake_template_path: str = "voice_profiles/wake_jarvis.npz"
    interrupt_template_path: str = "voice_profiles/interrupt_calate.npz"
    interrupt_enrollment_samples: int = 3
    interrupt_match_floor: float = 0.66
    wake_feature_sample_rate: int = 16000
    wake_feature_frame_ms: float = 25.0
    wake_feature_hop_ms: float = 10.0
    wake_feature_bands: int = 24
    wake_probe_min_seconds: float = 0.35
    wake_probe_max_seconds: float = 1.40
    wake_match_floor: float = 0.72
    wake_match_margin: float = 0.08
    wake_start_slack_seconds: float = 0.18
    wake_command_start_timeout_seconds: float = 5.0
    wake_command_silence_seconds: float = 1.00
    wake_command_max_seconds: float = 12.0
    wake_command_min_seconds: float = 0.25
    wake_command_preroll_seconds: float = 0.42
    wake_command_threshold_ratio: float = 0.65

    # Personal Operations Layer.
    security_watch_enabled: bool = True
    security_watch_interval_seconds: float = 120.0
    reminders_enabled: bool = True
    reminder_interval_seconds: float = 20.0
    persistent_context_enabled: bool = True
    persistent_context_turns: int = 4

    # Local book library. Source PDFs stay outside Git and are indexed into a
    # private SQLite database with page-level provenance.
    book_library_enabled: bool = True
    book_library_auto_sync: bool = True
    book_library_root: str = "library/books"
    book_library_db_path: str = "knowledge/library/library.sqlite3"
    book_library_startup_delay_seconds: float = 15.0
    book_library_sync_interval_seconds: float = 300.0
    book_library_chunk_chars: int = 1800
    book_library_chunk_overlap: int = 250

    cyber_knowledge_enabled: bool = True
    cyber_knowledge_auto_sync: bool = True
    cyber_knowledge_startup_delay_seconds: float = 120.0
    cyber_knowledge_sync_interval_hours: float = 24.0

    # Owner-controlled Cyber Range. Lab scope is explicit and local-only.
    cyber_range_enabled: bool = True
    cyber_range_state_path: str = "memory/cyber_range.json"
    cyber_range_probe_timeout_seconds: float = 0.45

    # Kali Execution Bridge. OWNER CLI configures the Kali host; the model can
    # only use fixed execution profiles and only against authorized LAB targets.
    kali_bridge_enabled: bool = True
    kali_bridge_state_path: str = "memory/kali_bridge.json"
    kali_bridge_ssh_executable: str = "ssh"
    kali_bridge_known_hosts_path: str = "memory/kali_known_hosts"
    kali_bridge_connect_timeout_seconds: float = 5.0
    kali_bridge_command_timeout_seconds: float = 120.0
    kali_bridge_output_max_chars: int = 30000
    kali_vm_provider: str = "auto"  # auto | virtualbox | vmware
    kali_vm_identifier: str = ""    # VirtualBox VM name/UUID or VMware .vmx path
    kali_vm_visible: bool = True
    kali_activity_log_path: str = "memory/kali_activity.jsonl"

    # Personal Cognition / Proactive Presence.
    personal_learning_enabled: bool = True
    proactive_enabled: bool = True
    proactive_speech_enabled: bool = True
    proactive_interval_seconds: float = 30.0
    proactive_startup_delay_seconds: float = 120.0
    proactive_min_interval_minutes: float = 20.0
    proactive_idle_seconds: float = 120.0
    proactive_quiet_start_hour: int = 23
    proactive_quiet_end_hour: int = 8
    proactive_max_per_hour: int = 2

    # Adaptive Companion Presence. Timing is gated, but the local model decides
    # whether to speak and writes the message; there are no phrase tables.
    companion_enabled: bool = True
    companion_flirt_enabled: bool = True
    companion_flirt_intensity: float = 0.60
    companion_temperature: float = 0.55
    companion_check_interval_seconds: float = 60.0
    companion_startup_delay_seconds: float = 180.0
    companion_decision_cooldown_seconds: float = 180.0
    companion_min_interval_minutes: float = 25.0
    companion_idle_seconds: float = 150.0
    companion_quiet_start_hour: int = 23
    companion_quiet_end_hour: int = 8
    companion_max_per_hour: int = 1
    companion_max_chars: int = 260
    companion_state_path: str = "memory/companion_presence.json"

    # Performance & Resource Intelligence.
    performance_enabled: bool = True
    performance_mode: str = "auto"  # auto | fast | balanced | deep | eco
    performance_monitor_interval_seconds: float = 2.0
    performance_gpu_sample_interval_seconds: float = 3.0
    performance_sustained_high_samples: int = 3

    performance_elevated_cpu_percent: float = 70.0
    performance_elevated_memory_percent: float = 80.0
    performance_elevated_gpu_percent: float = 65.0
    performance_elevated_vram_percent: float = 75.0

    performance_high_cpu_percent: float = 85.0
    performance_high_memory_percent: float = 88.0
    performance_high_gpu_percent: float = 82.0
    performance_high_vram_percent: float = 84.0

    performance_fast_ctx: int = 2048
    performance_balanced_ctx: int = 6144
    performance_deep_ctx: int = 8192
    performance_eco_ctx: int = 3072

    performance_fast_predict: int = 96
    performance_balanced_predict: int = 280
    performance_deep_predict: int = 480
    performance_eco_predict: int = 128

    performance_history_fast: int = 4
    performance_history_balanced: int = 10
    performance_history_deep: int = 16
    performance_history_eco: int = 4

    performance_tool_budget_fast: int = 8
    performance_tool_budget_balanced: int = 20
    performance_tool_budget_deep: int = 32
    performance_tool_budget_eco: int = 8

    performance_eco_keep_alive: str = "2m"
    performance_release_llm_on_pressure: bool = False
    performance_cloud_offload_under_pressure: bool = False
    performance_background_defer_under_pressure: bool = True
    performance_warmup_delay_seconds: float = 1.5

    # Owner Authority / Autonomous Learning.
    autonomy_enabled: bool = True
    autonomy_mode: str = "owner_strict"
    autonomy_pending_ttl_seconds: int = 600
    autonomy_grant_ttl_seconds: int = 600
    autonomy_denial_cooldown_hours: float = 24.0
    autonomy_expired_cooldown_minutes: float = 180.0
    autonomy_recurring_topic_cooldown_hours: float = 6.0
    autonomy_max_pending: int = 8
    autonomy_proactive_learning_enabled: bool = True
    autonomy_direct_user_orders_authorize_exact_action: bool = True
    autonomy_auto_execute_after_authorize: bool = True

    @classmethod
    def ensure_file_schema(
        cls,
        path: str | Path = "settings.json",
    ) -> dict[str, object]:
        """
        Add newly introduced settings with default values without overwriting
        existing user choices. Environment-variable overrides are not persisted.
        """
        p = Path(path)
        data: dict[str, object] = {}
        had_utf8_bom = False
        if p.exists():
            raw = p.read_bytes()
            had_utf8_bom = raw.startswith(b"\xef\xbb\xbf")
            loaded = json.loads(raw.decode("utf-8-sig"))
            if isinstance(loaded, dict):
                data = loaded

        defaults = cls()
        # External AI is a hard Core invariant in this hotfix. Legacy settings
        # are migrated to disabled even if an older release stored an opt-in.

        # 0.21 voice migration: the OWNER explicitly selected a feminine, warm
        # voice. Only migrate the untouched 0.20 defaults; preserve any custom
        # voice/rate/pitch the OWNER may already have chosen manually.
        voice_migrated: list[str] = []
        if "speech_persona_profile" not in data:
            legacy_voice_values = {
                "speech_voice": ("pt-PT-DuarteNeural", defaults.speech_voice),
                "speech_rate": ("-7%", defaults.speech_rate),
                "speech_pitch": ("-16Hz", defaults.speech_pitch),
            }
            for field_name, (legacy_value, new_value) in legacy_voice_values.items():
                if data.get(field_name) == legacy_value:
                    data[field_name] = new_value
                    voice_migrated.append(field_name)

        accuracy_migrated: list[str] = []
        # 0.23.4 webcam STT migration. Only exact shipped 0.23.3 defaults are
        # upgraded so OWNER-tuned values remain untouched.
        legacy_prompt = (
            "Português europeu. Assistente Jarvis. "
            "Comandos e perguntas naturais. "
            "Brave, Spotify, Steam, Discord, Cyberpunk 2077, "
            "volume, áudio, GPU, gráfica, CPU, temperatura."
        )
        if data.get("wake_stt_beam_size") == 3:
            data["wake_stt_beam_size"] = 5
            accuracy_migrated.append("wake_stt_beam_size")
        if data.get("wake_command_silence_seconds") == 0.8:
            data["wake_command_silence_seconds"] = 1.0
            accuracy_migrated.append("wake_command_silence_seconds")
        if data.get("wake_command_preroll_seconds") == 0.12:
            data["wake_command_preroll_seconds"] = 0.18
            accuracy_migrated.append("wake_command_preroll_seconds")
        if data.get("wake_stt_initial_prompt") == legacy_prompt:
            data["wake_stt_initial_prompt"] = defaults.wake_stt_initial_prompt
            accuracy_migrated.append("wake_stt_initial_prompt")

        speed_migrated: list[str] = []
        # 0.24.1 wake/STT latency and false-wake migration. Only the exact
        # values shipped by 0.24.0 are changed; OWNER-tuned values survive.
        speed_values = {
            "wake_stt_beam_size": (5, defaults.wake_stt_beam_size),
            "wake_stt_retry_beam_size": (8, defaults.wake_stt_retry_beam_size),
            "wake_stt_low_confidence_avg_logprob": (-0.85, defaults.wake_stt_low_confidence_avg_logprob),
            "wake_stt_low_confidence_no_speech": (0.45, defaults.wake_stt_low_confidence_no_speech),
            "wake_command_preroll_seconds": (0.18, defaults.wake_command_preroll_seconds),
            "wake_candidate_reject_cooldown_seconds": (0.45, defaults.wake_candidate_reject_cooldown_seconds),
            "performance_fast_ctx": (4096, defaults.performance_fast_ctx),
            "performance_fast_predict": (160, defaults.performance_fast_predict),
            "performance_history_fast": (6, defaults.performance_history_fast),
            "performance_tool_budget_fast": (12, defaults.performance_tool_budget_fast),
        }
        for field_name, (legacy_value, new_value) in speed_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                speed_migrated.append(field_name)

        wake_hardening_migrated: list[str] = []
        # 0.25.4 false-wake hardening. Only exact 0.25.3 shipped defaults are
        # upgraded; explicit OWNER tuning is preserved.
        wake_hardening_values = {
            "voice_v2_wake_threshold": (0.55, defaults.voice_v2_wake_threshold),
            "wake_match_floor": (0.62, defaults.wake_match_floor),
            "wake_candidate_min_avg_logprob": (-0.80, defaults.wake_candidate_min_avg_logprob),
            "wake_candidate_max_no_speech_prob": (0.35, defaults.wake_candidate_max_no_speech_prob),
        }
        for field_name, (legacy_value, new_value) in wake_hardening_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                wake_hardening_migrated.append(field_name)

        voice_v2_sensitivity_migrated: list[str] = []
        # 0.26.2: the openWakeWord model has its own Silero VAD and temporal
        # confirmation, so the 0.62 threshold inherited from the legacy
        # false-wake incident was unnecessarily strict. Only the exact shipped
        # 0.25.4-0.26.1 value is relaxed; OWNER tuning remains untouched.
        if data.get("voice_v2_wake_threshold") == 0.62:
            data["voice_v2_wake_threshold"] = defaults.voice_v2_wake_threshold
            voice_v2_sensitivity_migrated.append("voice_v2_wake_threshold")

        voice_latency_migrated: list[str] = []
        # 0.26.7 latency + hallucination hardening. These exact values were
        # shipped by 0.26.6; OWNER-tuned alternatives are preserved. On this
        # Windows build Faster Whisper CUDA is not usable, so CPU/small avoids
        # repeated CUDA fallback and keeps the local Qwen model resident.
        voice_latency_values = {
            "voice_v2_stt_model": ("medium", defaults.voice_v2_stt_model),
            "voice_v2_stt_device": ("auto", defaults.voice_v2_stt_device),
            "performance_fast_ctx": (3072, defaults.performance_fast_ctx),
            "performance_fast_predict": (128, defaults.performance_fast_predict),
        }
        for field_name, (legacy_value, new_value) in voice_latency_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                voice_latency_migrated.append(field_name)

        voice_turn_migrated: list[str] = []
        # 0.26.8 wake responsiveness. These exact values were shipped by
        # 0.26.7; OWNER-tuned alternatives are preserved.
        voice_turn_values = {
            "voice_v2_owner_fast_accept_threshold": (0.82, defaults.voice_v2_owner_fast_accept_threshold),
            "voice_v2_owner_max_phrase_seconds": (1.30, defaults.voice_v2_owner_max_phrase_seconds),
        }
        for field_name, (legacy_value, new_value) in voice_turn_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                voice_turn_migrated.append(field_name)

        storage_migrated: list[str] = []
        # 0.26.0 storage migration. The old shipped wallpaper path was tied to
        # C:. Empty means "sibling of the active Core root", so a Core moved to
        # G:\JARVIS automatically resolves to G:\JARVIS-Wallpaper. Explicit
        # OWNER custom paths are preserved.
        if str(data.get("desktop_wallpaper_root") or "").lower() == r"c:\jarvis-wallpaper":
            data["desktop_wallpaper_root"] = defaults.desktop_wallpaper_root
            storage_migrated.append("desktop_wallpaper_root")

        mic_binding_migrated: list[str] = []
        # 0.27.5 microphone binding migration. 0.27.3 accidentally
        # restored the legacy JBL/16 kHz preference even when the OWNER had
        # selected the GENERAL WEBCAM WASAPI endpoint. Only migrate the exact
        # shipped legacy triple; explicit OWNER microphone preferences remain.
        if (
            str(data.get("mic_preferred_device_name") or "").strip().upper() == "JBL WAVE BEAM"
            and bool(data.get("mic_preferred_handsfree", True))
            and int(data.get("mic_preferred_samplerate") or 0) == 16000
        ):
            data["mic_preferred_device_name"] = "GENERAL WEBCAM"
            data["mic_preferred_handsfree"] = False
            data["mic_preferred_samplerate"] = 48000
            mic_binding_migrated.extend([
                "mic_preferred_device_name",
                "mic_preferred_handsfree",
                "mic_preferred_samplerate",
            ])

        vision_migrated: list[str] = []
        # 0.27.8 acceptance hotfix v3 replaces the old Ollama-style visual
        # model tag with a JARVIS-owned native llama.cpp multimodal runtime.
        # Only the exact shipped legacy value is migrated; OWNER custom labels
        # remain untouched. The model files themselves are installed explicitly
        # by setup_vision.ps1 and are never silently downloaded by Core setup.
        if str(data.get("vision_model") or "").strip().lower() == "qwen2.5vl:7b":
            data["vision_model"] = defaults.vision_model
            vision_migrated.append("vision_model")

        resource_migrated: list[str] = []
        # 0.27.5 local-resource-first migration. Keep the local Qwen resident
        # longer for low latency. Only the exact previously shipped 5m value
        # is upgraded; explicit OWNER values remain untouched.
        if data.get("ollama_keep_alive") == "5m":
            data["ollama_keep_alive"] = defaults.ollama_keep_alive
            resource_migrated.append("ollama_keep_alive")

        added: list[str] = []
        for field_name in cls.__dataclass_fields__:
            if field_name in data:
                continue
            data[field_name] = getattr(defaults, field_name)
            added.append(field_name)

        # 0.27.8 hotfix invariant: local JARVIS reasoning is the only AI route.
        # The web may be read directly, but another AI can never be enabled.
        forced: list[str] = []
        local_first_values = {
            "local_llm_backend": "jarvis_local",
            "hybrid_mode": "local",
            "cloud_fallback_on_local_error": False,
            "external_ai_complex_only": True,
            "external_ai_complexity_threshold": 4,
            "external_ai_auto_escalate_complex": False,
            "performance_cloud_offload_under_pressure": False,
            "performance_release_llm_on_pressure": False,
            "voice_v2_preload_stt": True,
        }
        local_first_values.update({
            "external_ai_enabled": False,
            "cloud_enabled": False,
            "expert_escalation_enabled": False,
        })
        for field_name, value in local_first_values.items():
            if data.get(field_name) != value:
                data[field_name] = value
                forced.append(field_name)

        if had_utf8_bom or added or forced or voice_migrated or vision_migrated or resource_migrated or accuracy_migrated or speed_migrated or wake_hardening_migrated or voice_latency_migrated or voice_turn_migrated or storage_migrated or mic_binding_migrated or not p.exists():
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        return {
            "ok": True,
            "path": str(p),
            "added": added,
            "added_count": len(added),
            "forced_local_first": forced,
            "forced_local_first_count": len(forced),
            "voice_migrated": voice_migrated,
            "voice_migrated_count": len(voice_migrated),
            "vision_migrated": vision_migrated,
            "vision_migrated_count": len(vision_migrated),
            "resource_migrated": resource_migrated,
            "resource_migrated_count": len(resource_migrated),
            "accuracy_migrated": accuracy_migrated,
            "accuracy_migrated_count": len(accuracy_migrated),
            "speed_migrated": speed_migrated,
            "wake_hardening_migrated": wake_hardening_migrated,
            "wake_hardening_migrated_count": len(wake_hardening_migrated),
            "voice_v2_sensitivity_migrated": voice_v2_sensitivity_migrated,
            "voice_v2_sensitivity_migrated_count": len(voice_v2_sensitivity_migrated),
            "voice_latency_migrated": voice_latency_migrated,
            "voice_turn_migrated": voice_turn_migrated,
            "voice_turn_migrated_count": len(voice_turn_migrated),
            "voice_latency_migrated_count": len(voice_latency_migrated),
            "storage_migrated": storage_migrated,
            "storage_migrated_count": len(storage_migrated),
            "mic_binding_migrated": mic_binding_migrated,
            "mic_binding_migrated_count": len(mic_binding_migrated),
            "utf8_bom_normalized": had_utf8_bom,
            "speed_migrated_count": len(speed_migrated),
        }

    @classmethod
    def update_file_values(
        cls,
        values: dict[str, object],
        path: str | Path = "settings.json",
    ) -> dict[str, object]:
        """Persist a small set of already-validated settings from OWNER CLI."""
        p = Path(path)
        data: dict[str, object] = {}
        if p.exists():
            loaded = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                data = loaded
        allowed = set(cls.__dataclass_fields__)
        changed: dict[str, object] = {}
        for key, value in dict(values or {}).items():
            if key not in allowed:
                continue
            if data.get(key) != value:
                data[key] = value
                changed[key] = value
        if changed:
            p.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return {
            "ok": True,
            "path": str(p),
            "changed": changed,
            "changed_count": len(changed),
        }

    @classmethod
    def load(cls, path: str | Path = "settings.json") -> "Settings":
        p = Path(path)
        data = {}
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8-sig"))

        overrides = {
            "JARVIS_MODEL": "model",
            "JARVIS_OLLAMA_HOST": "ollama_host",
            "JARVIS_USER": "user_name",
            "JARVIS_HYBRID_MODE": "hybrid_mode",
            "JARVIS_CLOUD_MODEL": "cloud_model",
            "JARVIS_WALLPAPER_ROOT": "desktop_wallpaper_root",
        }
        for env_name, field_name in overrides.items():
            value = os.getenv(env_name)
            if value:
                data[field_name] = value

        allowed = set(cls.__dataclass_fields__)
        instance = cls(**{k: v for k, v in data.items() if k in allowed})

        # Hotfix safety invariant: another AI is never a runtime route.
        # Environment variables and legacy settings cannot re-enable it.
        instance.hybrid_mode = "local"
        instance.external_ai_enabled = False
        instance.cloud_enabled = False
        instance.cloud_fallback_on_local_error = False
        instance.external_ai_auto_escalate_complex = False
        instance.expert_escalation_enabled = False
        instance.performance_cloud_offload_under_pressure = False

        return instance
