import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.core.config import Settings
from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.idle_mind import IdleMindService
from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class _Events:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class _Apps:
    def list_apps(self):
        return [
            {
                "id": "brave",
                "name": "Brave",
                "aliases": ["browser", "breive"],
            }
        ]


class _Tools:
    def __init__(self):
        self.calls = []
        self.request_started_at = None

    def execute(self, name, args=None):
        self.calls.append((name, args or {}))
        return json.dumps({"ok": True, "app": "brave"})


class WakeReliability0241Tests(unittest.TestCase):
    def _service(self):
        return WakeWordService(
            _Events(),
            WakeWordConfig(),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": True, "text": "abre o Brave"},
            wake_transcribe_callback=lambda path: {"ok": True, "text": "Jarvis"},
        )

    def test_wake_whisper_confirmation_is_unbiased(self):
        cfg = ListeningConfig()
        self.assertEqual(cfg.wake_candidate_beam_size, 1)
        self.assertEqual(cfg.wake_candidate_initial_prompt, "")
        self.assertEqual(cfg.wake_candidate_hotwords, "")

    def test_strict_runtime_wake_confirmation_rejects_normal_speech(self):
        service = self._service()
        ok, reason = service._wake_candidate_result_confirmed(
            {
                "ok": True,
                "text": "Obrigado",
                "avg_logprob": -0.2,
                "max_no_speech_prob": 0.01,
            },
            "Jarvis",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "keyword_not_exact")

    def test_strict_runtime_wake_confirmation_accepts_clean_keyword(self):
        service = self._service()
        ok, reason = service._wake_candidate_result_confirmed(
            {
                "ok": True,
                "text": "Jarvis",
                "avg_logprob": -0.25,
                "max_no_speech_prob": 0.02,
            },
            "Jarvis",
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "confirmed")

    def test_strict_runtime_wake_confirmation_rejects_prompt_like_phrase(self):
        service = self._service()
        ok, reason = service._wake_candidate_result_confirmed(
            {
                "ok": True,
                "text": "Jarvis obrigado",
                "avg_logprob": -0.2,
                "max_no_speech_prob": 0.01,
            },
            "Jarvis",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "keyword_not_exact")

    def test_low_confidence_keyword_is_rejected(self):
        service = self._service()
        ok, reason = service._wake_candidate_result_confirmed(
            {
                "ok": True,
                "text": "Jarvis",
                "avg_logprob": -1.2,
                "max_no_speech_prob": 0.02,
            },
            "Jarvis",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "low_confidence")

    def test_candidate_audio_is_isolated_around_match(self):
        cfg = WakeWordConfig(candidate_window_seconds=0.5, candidate_tail_seconds=0.05)
        service = WakeWordService(
            _Events(), cfg, on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": True, "text": "x"},
        )
        audio = np.arange(32000, dtype=np.float32)
        out = service._isolate_wake_candidate(audio, 16000, keyword_end=16000)
        # 0.5 s before + 0.05 s after = 8800 samples.
        self.assertEqual(out.size, 8800)
        self.assertEqual(out[0], audio[8000])
        self.assertEqual(out[-1], audio[16799])

    def test_runtime_loop_uses_isolated_structured_confirmation(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        runtime = text.index('"WAKE_CANDIDATE"')
        isolate = text.index("_isolate_wake_candidate", runtime)
        confirm = text.index("_wake_candidate_result_confirmed", isolate)
        detected = text.index('"WAKE_WORD_DETECTED"', confirm)
        self.assertLess(runtime, isolate)
        self.assertLess(isolate, confirm)
        self.assertLess(confirm, detected)


class FastVoiceRecovery0241Tests(unittest.TestCase):
    def test_voice_only_app_fragment_recovers_clipped_open_verb(self):
        tools = _Tools()
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("O Brave", voice_origin=True)
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "voice_app_fragment_open")
        self.assertEqual(tools.calls, [("open_application", {"app_name": "brave"})])

    def test_terminal_app_fragment_does_not_guess_an_action(self):
        tools = _Tools()
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("O Brave", voice_origin=False)
        self.assertFalse(result.handled)
        self.assertEqual(tools.calls, [])

    def test_thanks_and_goodbye_use_conversational_ai(self):
        tools = _Tools()
        router = FastCommandRouter(_Events(), tools, _Apps())
        thanks = router.dispatch("Obrigado e até mais!", voice_origin=True)
        bye = router.dispatch("Tchau!", voice_origin=True)
        self.assertFalse(thanks.handled)
        self.assertFalse(bye.handled)
        self.assertEqual(tools.calls, [])

    def test_cli_marks_wake_requests_as_voice_origin(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('process_request(transcript, source="wake")', text)
        self.assertIn("voice_origin=voice_origin", text)


class STTLatency0241Tests(unittest.TestCase):
    def test_command_profile_is_greedy_first_retry_only_if_needed(self):
        cfg = ListeningConfig()
        self.assertEqual(cfg.command_beam_size, 1)
        self.assertEqual(cfg.command_retry_beam_size, 5)
        self.assertGreater(cfg.command_low_confidence_avg_logprob, -0.85)

    def test_command_preroll_is_long_enough_to_recover_first_verb(self):
        self.assertGreaterEqual(WakeWordConfig().command_preroll_seconds, 0.40)

    def test_command_energy_trim_removes_silence_but_keeps_speech(self):
        cfg = ListeningConfig(command_trim_silence=True)
        mic = MicrophoneService(_Events(), cfg)
        silence = np.zeros(16000, dtype=np.float32)
        t = np.linspace(0, 1, 16000, endpoint=False)
        speech = (0.08 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        audio = np.concatenate([silence[:8000], speech, silence[:12000]])
        conditioned, meta = mic._condition_audio(audio, profile="command")
        self.assertTrue(meta["trimmed"])
        self.assertGreater(meta["trimmed_seconds"], 0.5)
        self.assertGreater(conditioned.size, 12000)
        self.assertLess(conditioned.size, audio.size)


class _Cognition:
    def status(self):
        return {
            "last_interaction_at": "2026-08-30T20:00:00+01:00",
            "recent_topics": ["jarvis", "performance"],
            "pending_insights": 0,
            "proactive_speech_enabled": True,
        }

    def profile(self):
        return {"model": {
            "goals": [{"statement": "otimizar o JARVIS"}],
            "projects": [{"statement": "JARVIS"}],
        }}

    def proactive_candidate(self, **kwargs):
        return None


class _Trace:
    def status(self):
        return {"current": {"stage": "IDLE", "detail": "Núcleo disponível"}}


class _Companion:
    def idle_status(self):
        return {"ok": True, "eligible": False, "gate_reason": "cooldown", "enabled": True, "flirt_enabled": True}


class _Latch:
    def active(self):
        return False


class _Wake:
    def status(self):
        return {"running": True, "device": 23, "last_command": "abre o Brave"}


class _IdleSettings:
    proactive_min_interval_minutes = 20
    proactive_idle_seconds = 120
    proactive_quiet_start_hour = 23
    proactive_quiet_end_hour = 8
    proactive_max_per_hour = 2


class _Planner:
    def status(self):
        return {"ok": True, "active": 0, "plan_count": 0}


class IdleMind0241Tests(unittest.TestCase):
    def test_idle_snapshot_exposes_possible_next_action(self):
        service = IdleMindService(
            settings=_IdleSettings(), cognition=_Cognition(), activity_trace=_Trace(),
            companion_service=_Companion(), silence_latch=_Latch(), wake=_Wake(),
            planner_provider=lambda: _Planner(),
        )
        result = service.snapshot()
        self.assertEqual(result["possible_next_action"]["kind"], "continue_project")
        self.assertEqual(result["possible_next_action"]["summary"], "JARVIS")
        self.assertTrue(result["possible_next_action"]["permission_required"])

    def test_idle_reflect_uses_high_level_provider(self):
        calls = []
        def reflect(payload):
            calls.append(payload)
            return {
                "ok": True,
                "focus": "JARVIS",
                "possible_next_action": "medir latência",
                "permission_required": False,
            }
        service = IdleMindService(
            settings=_IdleSettings(), cognition=_Cognition(), activity_trace=_Trace(),
            companion_service=_Companion(), silence_latch=_Latch(), wake=_Wake(),
            planner_provider=lambda: _Planner(), reflection_provider=reflect,
        )
        result = service.reflect()
        self.assertTrue(result["ok"])
        self.assertEqual(result["reflection"]["focus"], "JARVIS")
        self.assertEqual(len(calls), 1)
        self.assertIn("não contém chain-of-thought", result["note"])

    def test_cli_exposes_idle_reflect_command(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('"/mind idle reflect"', text)
        self.assertIn("brain.plan_idle_reflection", text)


class SettingsMigration0241Tests(unittest.TestCase):
    def test_shipped_0240_values_migrate_to_latency_profile(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(json.dumps({
                "wake_stt_beam_size": 5,
                "wake_stt_retry_beam_size": 8,
                "wake_stt_low_confidence_avg_logprob": -0.85,
                "wake_stt_low_confidence_no_speech": 0.45,
                "wake_command_preroll_seconds": 0.18,
                "wake_candidate_reject_cooldown_seconds": 0.45,
                "performance_fast_ctx": 4096,
                "performance_fast_predict": 160,
                "performance_history_fast": 6,
                "performance_tool_budget_fast": 12,
            }), encoding="utf-8")
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(result["speed_migrated_count"], 10)
            self.assertEqual(data["wake_stt_beam_size"], 1)
            self.assertEqual(data["wake_stt_retry_beam_size"], 5)
            self.assertEqual(data["wake_command_preroll_seconds"], 0.42)
            self.assertEqual(data["performance_fast_ctx"], 2048)
            self.assertEqual(data["performance_tool_budget_fast"], 8)


if __name__ == "__main__":
    unittest.main()


class ActionTruthGuard0241Tests(unittest.TestCase):
    def test_unverified_pc_action_success_claim_is_blocked(self):
        from jarvis_core.services.action_truth import guard_unverified_local_action_claim
        text, blocked = guard_unverified_local_action_claim(
            "Abre o Brave",
            "Brave aberto.",
            successful_tool_calls=0,
        )
        self.assertTrue(blocked)
        self.assertIn("nenhuma ferramenta local", text)

    def test_verified_pc_action_success_claim_is_preserved(self):
        from jarvis_core.services.action_truth import guard_unverified_local_action_claim
        text, blocked = guard_unverified_local_action_claim(
            "Abre o Brave",
            "Brave aberto.",
            successful_tool_calls=1,
        )
        self.assertFalse(blocked)
        self.assertEqual(text, "Brave aberto.")

    def test_non_action_conversation_is_not_rewritten(self):
        from jarvis_core.services.action_truth import guard_unverified_local_action_claim
        text, blocked = guard_unverified_local_action_claim(
            "O Brave é bom?",
            "É um navegador aberto a extensões Chromium.",
            successful_tool_calls=0,
        )
        self.assertFalse(blocked)
        self.assertEqual(text, "É um navegador aberto a extensões Chromium.")


class ObservedOwnerTraceRegression0241Tests(unittest.TestCase):
    def test_false_wake_then_clipped_brave_command_executes_once(self):
        wake = WakeWordService(
            _Events(), WakeWordConfig(), on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": True, "text": "O Brave"},
        )
        normal_ok, _ = wake._wake_candidate_result_confirmed(
            {"ok": True, "text": "Obrigado", "avg_logprob": -0.2, "max_no_speech_prob": 0.01},
            "Jarvis",
        )
        real_ok, _ = wake._wake_candidate_result_confirmed(
            {"ok": True, "text": "Jarvis", "avg_logprob": -0.2, "max_no_speech_prob": 0.01},
            "Jarvis",
        )
        self.assertFalse(normal_ok)
        self.assertTrue(real_ok)

        tools = _Tools()
        routed = FastCommandRouter(_Events(), tools, _Apps()).dispatch(
            "O Brave", voice_origin=True,
        )
        self.assertTrue(routed.handled)
        self.assertEqual(routed.route, "voice_app_fragment_open")
        self.assertEqual(tools.calls, [("open_application", {"app_name": "brave"})])
        self.assertEqual(routed.response, "Brave aberto.")
