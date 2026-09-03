import json
import tempfile
import time
import unittest
from pathlib import Path

from jarvis_core.core.events import EventBus
from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.activity_trace import ActivityTraceService
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
        return [{"id": "brave", "name": "Brave", "aliases": ["browser"]}]


class _Tools:
    def __init__(self):
        self.calls = []
    def execute(self, name, args=None):
        self.calls.append((name, args or {}))
        return json.dumps({"ok": True})


class FastInteraction0240Tests(unittest.TestCase):
    def test_ptpt_polite_imperative_uses_fast_path(self):
        events = _Events(); tools = _Tools()
        router = FastCommandRouter(events, tools, _Apps())
        result = router.dispatch("Abra o Brave!")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "app_open")
        self.assertEqual(tools.calls, [("open_application", {"app_name": "brave"})])

    def test_activity_trace_surfaces_fast_path(self):
        with tempfile.TemporaryDirectory() as td:
            bus = EventBus(log_dir=str(Path(td) / "logs"))
            trace = ActivityTraceService(bus, path=str(Path(td) / "activity.json"))
            trace.start()
            bus.emit("FAST_PATH_HIT", route="app_open", tool="open_application")
            time.sleep(0.1)
            rows = trace.last()["entries"]
            trace.stop()
            self.assertTrue(any(r["stage"] == "ROTA" and "FAST/app_open" in r["detail"] for r in rows))

    def test_wake_candidate_has_lightweight_profile(self):
        cfg = ListeningConfig()
        self.assertEqual(cfg.wake_candidate_beam_size, 1)
        self.assertEqual(cfg.wake_candidate_hotwords, "")
        self.assertEqual(cfg.wake_candidate_initial_prompt, "")
        self.assertTrue(hasattr(MicrophoneService, "transcribe_wake_file"))
        self.assertTrue(hasattr(WakeWordConfig(), "candidate_reject_cooldown_seconds"))


    def test_wake_service_uses_separate_candidate_transcriber(self):
        import numpy as np
        called = {"wake": 0, "command": 0}
        service = WakeWordService(
            _Events(),
            WakeWordConfig(),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: called.__setitem__("command", called["command"] + 1) or {"ok": True, "text": "abre o Brave"},
            wake_transcribe_callback=lambda path: called.__setitem__("wake", called["wake"] + 1) or {"ok": True, "text": "Jarvis"},
        )
        text = service._transcribe_wake_candidate(np.zeros(1600, dtype=np.float32), 16000)
        self.assertEqual(text, "Jarvis")
        self.assertEqual(called["wake"], 1)
        self.assertEqual(called["command"], 0)

    def test_cli_wires_separate_wake_transcriber_and_idle_command(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("wake_transcribe_callback=microphone.transcribe_wake_file", text)
        self.assertIn('"/mind idle"', text)

    def test_brain_has_successful_action_repeat_guard(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("TOOL_REPEAT_SUPPRESSED", text)
        self.assertIn("successful_action_calls", text)
        self.assertIn('"open_application"', text)


class _Cognition:
    def status(self):
        return {
            "last_interaction_at": "2026-08-30T20:00:00+01:00",
            "recent_topics": ["Jarvis", "webcam"],
            "pending_insights": 1,
            "proactive_speech_enabled": True,
        }
    def profile(self):
        return {"model": {
            "goals": [{"statement": "reduzir latência"}],
            "projects": [{"statement": "JARVIS"}],
        }}
    def proactive_candidate(self, **kwargs):
        return {"reason": "personal_project", "priority": "reflective", "text": "Posso continuar a otimizar o JARVIS."}


class _Trace:
    def status(self):
        return {"current": {"stage": "IDLE", "detail": "Núcleo disponível"}}


class _Companion:
    def idle_status(self):
        return {"ok": True, "eligible": False, "gate_reason": "not_idle_enough", "enabled": True, "flirt_enabled": True}


class _Latch:
    def active(self): return False


class _Wake:
    def status(self): return {"running": True, "device": 23, "last_command": "abre o Brave"}


class _Settings:
    proactive_min_interval_minutes = 20
    proactive_idle_seconds = 120
    proactive_quiet_start_hour = 23
    proactive_quiet_end_hour = 8
    proactive_max_per_hour = 2


class _Planner:
    def status(self): return {"ok": True, "active": 0, "plan_count": 1}


class IdleMind0240Tests(unittest.TestCase):
    def test_idle_mind_is_observable_not_private_chain(self):
        service = IdleMindService(
            settings=_Settings(), cognition=_Cognition(), activity_trace=_Trace(),
            companion_service=_Companion(), silence_latch=_Latch(), wake=_Wake(),
            planner_provider=lambda: _Planner(),
        )
        result = service.snapshot()
        self.assertTrue(result["ok"])
        self.assertFalse(result["model_actively_reasoning"])
        self.assertEqual(result["attention"]["projects"], ["JARVIS"])
        self.assertEqual(result["considering"]["reason"], "personal_project")
        self.assertIn("não expõe chain-of-thought", result["note"])


if __name__ == "__main__":
    unittest.main()
