import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config
from jarvis_core.services.wakeword import acoustic_features


class _Events:
    def __init__(self):
        self.rows = []
    def emit(self, name, **data):
        self.rows.append((name, data))


def _sample(rate=16000, seconds=0.72):
    n = int(rate * seconds)
    t = np.arange(n, dtype=np.float32) / rate
    # Speech-like, nonstationary synthetic signal. Exact reproducibility makes
    # this a deterministic contract test for the enrolled-template path.
    env = np.minimum(1.0, np.arange(n, dtype=np.float32) / (rate * 0.06))
    env *= np.minimum(1.0, (n - np.arange(n, dtype=np.float32)) / (rate * 0.08))
    sig = (
        0.46 * np.sin(2*np.pi*(230 + 90*t)*t)
        + 0.24 * np.sin(2*np.pi*690*t)
        + 0.11 * np.sin(2*np.pi*1320*t)
    ) * env
    return np.clip(sig, -0.95, 0.95).astype(np.float32)


class OwnerWakeProfile0264Tests(unittest.TestCase):
    def test_v2_loads_and_matches_owner_wake_profile(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'wake_jarvis.npz'
            cfg = VoiceV2Config(wake_template_path=str(path), wake_match_floor=0.72)
            sig = _sample()
            feat = acoustic_features(sig, 16000, cfg, trim=False)
            np.savez_compressed(
                path,
                count=np.asarray(3, dtype=np.int32),
                threshold=np.asarray(0.72, dtype=np.float32),
                template_0=feat,
                template_1=feat,
                template_2=feat,
                duration_0=np.asarray(0.72, dtype=np.float32),
                duration_1=np.asarray(0.72, dtype=np.float32),
                duration_2=np.asarray(0.72, dtype=np.float32),
            )
            engine = VoiceEngineV2(_Events(), cfg, lambda _cmd: None, lambda _p: {})
            self.assertTrue(engine.owner_wake_enrolled())
            pcm = np.clip(sig * 32767.0, -32768, 32767).astype(np.int16)
            matched, score = engine._owner_wake_match(pcm)
            self.assertTrue(matched)
            self.assertGreaterEqual(score, 0.72)

    def test_owner_wake_requires_temporal_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'wake_jarvis.npz'
            cfg = VoiceV2Config(
                wake_template_path=str(path),
                wake_match_floor=0.72,
                wake_confirm_frames=2,
                wake_strong_threshold=0.95,
                frame_ms=80,
            )
            sig = _sample(seconds=0.88)
            feat = acoustic_features(sig, 16000, cfg, trim=False)
            payload = {'count': np.asarray(3,dtype=np.int32), 'threshold': np.asarray(0.72,dtype=np.float32)}
            for i in range(3):
                payload[f'template_{i}'] = feat
                payload[f'duration_{i}'] = np.asarray(0.72,dtype=np.float32)
            np.savez_compressed(path, **payload)
            engine = VoiceEngineV2(_Events(), cfg, lambda _cmd: None, lambda _p: {})
            pcm = np.clip(sig * 32767.0, -32768, 32767).astype(np.int16)
            frame = 1280
            fired = False
            for start in range(0, len(pcm), frame):
                chunk = pcm[start:start+frame]
                if len(chunk) < frame:
                    chunk = np.pad(chunk, (0, frame-len(chunk)))
                ready, _ = engine._process_owner_wake_frame(chunk, 0.90)
                fired = fired or ready
            self.assertTrue(fired)

    def test_status_exposes_owner_profile(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = VoiceV2Config(wake_template_path=str(Path(td)/'missing.npz'))
            engine = VoiceEngineV2(_Events(), cfg, lambda _cmd: None, lambda _p: {})
            status = engine.status()
            self.assertIn('owner_wake_profile', status)
            self.assertFalse(status['owner_wake_profile']['configured'])

if __name__ == '__main__':
    unittest.main()
