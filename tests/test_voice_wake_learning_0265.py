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
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config
from jarvis_core.services.wakeword import acoustic_features


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
    def test_saved_owner_threshold_is_not_overridden_by_global_floor(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wake.npz"
            cfg = VoiceV2Config(wake_template_path=str(path), wake_match_floor=0.80)
            sig = speech_like()
            feat = acoustic_features(sig, 16000, cfg, trim=False)
            payload = {"count": np.asarray(3, dtype=np.int32), "threshold": np.asarray(0.62, dtype=np.float32)}
            for i in range(3):
                payload[f"template_{i}"] = feat
                payload[f"duration_{i}"] = np.asarray(0.72, dtype=np.float32)
            np.savez_compressed(path, **payload)
            engine = VoiceEngineV2(Events(), cfg, lambda _c: None, lambda _p: {})
            self.assertAlmostEqual(engine._wake_template_threshold, 0.62, places=3)

    def test_owner_wake_tolerates_one_low_vad_frame(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wake.npz"
            cfg = VoiceV2Config(
                wake_template_path=str(path),
                wake_match_floor=0.58,
                wake_confirm_frames=2,
                wake_strong_threshold=0.99,
                frame_ms=80,
            )
            sig = speech_like(seconds=0.88)
            feat = acoustic_features(sig, 16000, cfg, trim=False)
            payload = {"count": np.asarray(3, dtype=np.int32), "threshold": np.asarray(0.58, dtype=np.float32)}
            for i in range(3):
                payload[f"template_{i}"] = feat
                payload[f"duration_{i}"] = np.asarray(0.72, dtype=np.float32)
            np.savez_compressed(path, **payload)
            engine = VoiceEngineV2(Events(), cfg, lambda _c: None, lambda _p: {})
            pcm = np.clip(sig * 32767, -32768, 32767).astype(np.int16)
            fired = False
            frame = 1280
            for idx, start in enumerate(range(0, len(pcm), frame)):
                chunk = pcm[start:start+frame]
                if len(chunk) < frame:
                    chunk = np.pad(chunk, (0, frame-len(chunk)))
                vad = 0.05 if idx == 3 else 0.90
                ready, _ = engine._process_owner_wake_frame(chunk, vad)
                fired = fired or ready
            # Medium-confidence template wakes intentionally finalize only when
            # the short utterance ends; feed the VAD hangover/silence frames.
            for _ in range(3):
                ready, _ = engine._process_owner_wake_frame(np.zeros(frame, dtype=np.int16), 0.0)
                fired = fired or ready
            self.assertTrue(fired)

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
