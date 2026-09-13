from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os


def _repair_utf8_mojibake(value: object) -> str | None:
    """Repair common UTF-8-as-Latin-1 settings corruption safely."""
    text = value if isinstance(value, str) else None
    if not text or not any(marker in text for marker in ("Ã", "Â")):
        return None
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return None
    return repaired if repaired != text else None


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
    native_llama_model_path: str = "models/llm/Qwen3-14B-Q4_K_M.gguf"
    native_llama_host: str = "127.0.0.1"
    native_llama_port: int = 11435
    native_llama_gpu_layers: int = 99
    native_llama_threads: int = 6
    native_llama_flash_attention: bool = True
    native_llama_cache_type_k: str = "q8_0"
    native_llama_cache_type_v: str = "q8_0"
    native_llama_start_timeout_seconds: float = 90.0
    native_llama_request_timeout_seconds: float = 180.0
    native_llama_state_path: str = "memory/native_llama_runtime.json"
    ollama_host: str = "http://localhost:11434"  # loopback compatibility executor / legacy model cache
    model: str = "qwen3:14b"
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

    # Long-term relational memory + generic live Core state contract.
    memory_graph_path: str = "memory/memory_graph.json"
    core_state_path: str = "memory/live_hud.json"
    core_state_interval_seconds: float = 2.0

    # PC-local audio is retired from the active runtime.
    # A future authenticated client such as iPhone/Siri may provide speech transport.
    local_voice_enabled: bool = False
    # 0.25 Voice Engine v2. ``auto`` prefers the mature Windows-native
    # WASAPI/openWakeWord pipeline when its optional dependencies are ready,
    # while retaining the legacy acoustic engine as an explicit fallback.
    # Optional owner-specific wake verifier. Training may run in WSL when
    # Windows App Control blocks SciPy/scikit-learn native extensions; runtime
    # scoring uses NumPy only.
    # Separate from the legacy acoustic floor. Voice v2 uses the OWNER's
    # calibrated wake profile plus VAD/energy and temporal confirmation.

    # Listening resilience. The watchdog only repairs the local wake/audio
    # stream and never executes commands or changes security permissions.

    # 0.24.0 conversational silence + safe activity observability.
    silence_latch_enabled: bool = True
    activity_trace_enabled: bool = True
    activity_trace_path: str = "memory/activity_trace.json"

    # Keep Faster Whisper model snapshots inside the JARVIS installation so a
    # dedicated drive does not spill multi-GB caches into the Windows profile.
    av_probe_min_signal_rms: float = 0.001
    av_verified_signal_ttl_seconds: float = 120.0
    # Voice ID remains active, but 0.6 defaults to observation-only until
    # per-user permissions are implemented.

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
            try:
                loaded = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {
                    "ok": False,
                    "path": str(p),
                    "error": "SETTINGS_JSON_INVALID",
                }
            if isinstance(loaded, dict):
                data = loaded

        defaults = cls()
        # External AI is a hard Core invariant in this hotfix. Legacy settings
        # are migrated to disabled even if an older release stored an opt-in.

        # PC-local audio was retired from Core. Historical settings are
        # removed instead of migrated or reintroduced.
        retired_local_audio_settings_removed: list[str] = []

        retired_local_audio_prefixes = (
            "voice_v2_",
            "listening_watchdog_",
            "wake_",
            "stt_",
            "mic_",
            "speech_",
            "speaker_",
            "interrupt_",
        )

        for field_name in list(data):
            if field_name in {
                "local_voice_enabled",
                "proactive_speech_enabled",
            }:
                continue

            if (
                field_name == "voice_input_backend"
                or field_name.startswith(
                    retired_local_audio_prefixes
                )
            ):
                data.pop(field_name, None)
                retired_local_audio_settings_removed.append(
                    field_name
                )

        # Historical performance migrations remain independent of Voice.
        speed_migrated: list[str] = []
        speed_values = {
            "performance_fast_ctx": (
                4096,
                defaults.performance_fast_ctx,
            ),
            "performance_fast_predict": (
                160,
                defaults.performance_fast_predict,
            ),
            "performance_history_fast": (
                6,
                defaults.performance_history_fast,
            ),
            "performance_tool_budget_fast": (
                12,
                defaults.performance_tool_budget_fast,
            ),
        }

        for field_name, (legacy_value, new_value) in speed_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                speed_migrated.append(field_name)

        latency_performance_migrated: list[str] = []
        latency_performance_values = {
            "performance_fast_ctx": (
                3072,
                defaults.performance_fast_ctx,
            ),
            "performance_fast_predict": (
                128,
                defaults.performance_fast_predict,
            ),
        }

        for (
            field_name,
            (legacy_value, new_value),
        ) in latency_performance_values.items():
            if data.get(field_name) == legacy_value:
                data[field_name] = new_value
                latency_performance_migrated.append(
                    field_name
                )

        retired_desktop_settings_removed: list[str] = []
        # M-08: Core no longer owns Wallpaper, its bridge, or Wallpaper Engine.
        # Purge only the six retired lifecycle keys. Arbitrary OWNER extension
        # keys remain untouched.
        retired_desktop_settings = (
            "desktop_integration_enabled",
            "desktop_wallpaper_root",
            "desktop_bridge_auto_start",
            "desktop_bridge_port",
            "desktop_wallpaper_engine_auto_start",
            "desktop_wallpaper_engine_path",
        )
        for field_name in retired_desktop_settings:
            if field_name in data:
                data.pop(field_name, None)
                retired_desktop_settings_removed.append(field_name)

        retired_companion_settings_removed: list[str] = []

        retired_companion_settings = (
            "companion_flirt_enabled",
            "companion_flirt_intensity",
        )

        for field_name in retired_companion_settings:
            if field_name in data:
                data.pop(field_name, None)
                retired_companion_settings_removed.append(
                    field_name
                )

        core_state_migrated: list[str] = []
        # M-07: the presentation-state publisher is a Core capability, not a
        # Wallpaper-owned service. Preserve explicit OWNER values while
        # renaming the old settings keys and remove the legacy aliases.
        legacy_core_state_fields = {
            "wallpaper_live_state_path": "core_state_path",
            "wallpaper_live_interval_seconds": "core_state_interval_seconds",
        }
        for legacy_field, current_field in legacy_core_state_fields.items():
            if legacy_field not in data:
                continue
            if current_field not in data:
                data[current_field] = data[legacy_field]
            data.pop(legacy_field, None)
            core_state_migrated.append(legacy_field)

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
            # PC-local speech is retired. Schema normalization must never
            # resurrect any historical audio subsystem on startup.
            "local_voice_enabled": False,
            "proactive_speech_enabled": False,
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

        if (had_utf8_bom or added or forced or vision_migrated or resource_migrated or speed_migrated or latency_performance_migrated or retired_local_audio_settings_removed or retired_desktop_settings_removed or retired_companion_settings_removed or core_state_migrated or not p.exists()):
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
            "retired_local_audio_settings_removed": (
                retired_local_audio_settings_removed
            ),
            "retired_local_audio_settings_removed_count": len(
                retired_local_audio_settings_removed
            ),
            "latency_performance_migrated": (
                latency_performance_migrated
            ),
            "latency_performance_migrated_count": len(
                latency_performance_migrated
            ),
            "vision_migrated": vision_migrated,
            "vision_migrated_count": len(vision_migrated),
            "resource_migrated": resource_migrated,
            "resource_migrated_count": len(resource_migrated),
            "speed_migrated": speed_migrated,
            "retired_desktop_settings_removed": retired_desktop_settings_removed,
            "retired_desktop_settings_removed_count": len(retired_desktop_settings_removed),
            "retired_companion_settings_removed": retired_companion_settings_removed,
            "retired_companion_settings_removed_count": len(retired_companion_settings_removed),
            "core_state_migrated": core_state_migrated,
            "core_state_migrated_count": len(core_state_migrated),
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
            try:
                loaded = json.loads(p.read_text(encoding="utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {
                    "ok": False,
                    "path": str(p),
                    "error": "SETTINGS_JSON_INVALID",
                }
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
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}

        # Read-only compatibility for callers that load an old settings file
        # without first running ensure_file_schema(). Current names always win.
        legacy_core_state_fields = {
            "wallpaper_live_state_path": "core_state_path",
            "wallpaper_live_interval_seconds": "core_state_interval_seconds",
        }
        for legacy_field, current_field in legacy_core_state_fields.items():
            if current_field not in data and legacy_field in data:
                data[current_field] = data[legacy_field]

        overrides = {
            "JARVIS_MODEL": "model",
            "JARVIS_OLLAMA_HOST": "ollama_host",
            "JARVIS_USER": "user_name",
            "JARVIS_HYBRID_MODE": "hybrid_mode",
            "JARVIS_CLOUD_MODEL": "cloud_model",
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

        # PC-local audio is structurally retired.
        # Keep only the master policy tombstone.
        instance.local_voice_enabled = False

        return instance
