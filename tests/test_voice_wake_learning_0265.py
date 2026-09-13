import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.core.config import Settings
from jarvis_core.services.autonomy import (
    AutonomyGuardian,
    explicit_standing_public_web_grant,
    parse_learning_goal,
)


class Events:
    def emit(self, *args, **kwargs):
        pass


def speech_like(rate=16000, seconds=0.72):
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float32) / rate
    env = np.minimum(1.0, np.arange(n, dtype=np.float32) / (rate * 0.05))
    env *= np.minimum(1.0, (n - np.arange(n, dtype=np.float32)) / (rate * 0.08))
    x = (0.5*np.sin(2*np.pi*240*t) + 0.2*np.sin(2*np.pi*720*t)) * env
    return x.astype(np.float32)


class VoiceWakeLearning0265Tests(unittest.TestCase):


    def test_learning_goal_supports_programming_c(self):
        result = parse_learning_goal("Aprende a programar em C")
        self.assertIsNotNone(result)
        self.assertEqual(result["topic"], "programar em C")

    def test_explicit_general_web_grant_is_detected(self):
        self.assertTrue(explicit_standing_public_web_grant(
            "Tens a minha autorização para acederes à internet e aprender Python"
        ))
        self.assertTrue(explicit_standing_public_web_grant(
            "Tens a minha autorização para usar a internet e aprender C"
        ))

    def test_standing_web_grant_persists_and_revoke_clears_it(self):
        with tempfile.TemporaryDirectory() as td:
            guard = AutonomyGuardian(
                Settings(), Events(),
                state_path=Path(td)/"state.json",
                audit_path=Path(td)/"audit.jsonl",
            )
            out = guard.grant_standing_public_web_learning(
                "Tens a minha autorização para acederes à internet e aprender Python"
            )
            self.assertTrue(out["ok"])
            self.assertTrue(guard.has_standing_public_web_learning())
            self.assertTrue(guard.status()["standing_public_web_read_only_learning"])
            revoked = guard.revoke_all()
            self.assertEqual(revoked["revoked_standing_permissions"], 2)
            self.assertFalse(guard.has_standing_public_web_learning())

    def test_existing_audit_grant_is_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            audit = Path(td)/"audit.jsonl"
            audit.write_text(json.dumps({
                "timestamp": "2026-08-31T12:00:00+01:00",
                "event": "direct_authorized_by_owner",
                "source_text": "Jarvis tens a minha autorização para acederes a internet e aprendas a programar em python",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            state = Path(td)/"state.json"
            state.write_text(json.dumps({
                "mode": "owner_strict", "owner_authority": "absolute",
                "pending": [], "grants": [], "denied": [],
            }), encoding="utf-8")
            guard = AutonomyGuardian(Settings(), Events(), state_path=state, audit_path=audit)
            self.assertTrue(guard.has_standing_public_web_learning())


if __name__ == "__main__":
    unittest.main()
