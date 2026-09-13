import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.core.config import Settings
from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.idle_mind import IdleMindService


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




class FastVoiceRecovery0241Tests(unittest.TestCase):

    def test_terminal_app_fragment_does_not_guess_an_action(self):
        tools = _Tools()
        router = FastCommandRouter(_Events(), tools, _Apps())
        result = router.dispatch("O Brave")
        self.assertFalse(result.handled)
        self.assertEqual(tools.calls, [])

    def test_thanks_and_goodbye_use_conversational_ai(self):
        tools = _Tools()
        router = FastCommandRouter(_Events(), tools, _Apps())
        thanks = router.dispatch("Obrigado e até mais!")
        bye = router.dispatch("Tchau!")
        self.assertFalse(thanks.handled)
        self.assertFalse(bye.handled)
        self.assertEqual(tools.calls, [])





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
