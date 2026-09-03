import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.core.config import Settings
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config


class Events:
    def emit(self, *args, **kwargs):
        return None


class VoiceResponsiveness0268Tests(unittest.TestCase):
    def test_defaults_prioritize_fast_owner_wake(self):
        s = Settings()
        self.assertAlmostEqual(0.45, s.voice_v2_inline_command_grace_seconds, places=3)
        self.assertAlmostEqual(0.70, s.voice_v2_owner_fast_accept_threshold, places=3)
        self.assertAlmostEqual(1.15, s.voice_v2_owner_max_phrase_seconds, places=3)

    def test_0267_voice_defaults_migrate_without_overwriting_custom_values(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'settings.json'
            path.write_text(json.dumps({
                'voice_v2_owner_fast_accept_threshold': 0.82,
                'voice_v2_owner_max_phrase_seconds': 1.30,
            }), encoding='utf-8')
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertAlmostEqual(0.70, data['voice_v2_owner_fast_accept_threshold'])
            self.assertAlmostEqual(1.15, data['voice_v2_owner_max_phrase_seconds'])
            self.assertIn('voice_v2_owner_fast_accept_threshold', result['voice_turn_migrated'])

    def test_short_temporally_confirmed_owner_wake_skips_whisper_round_trip(self):
        calls = []
        svc = VoiceEngineV2(
            Events(),
            VoiceV2Config(owner_wake_fast_accept_threshold=0.70),
            lambda _c: None,
            lambda _p: {},
            wake_transcribe_callback=lambda _p: calls.append('called') or {
                'ok': False, 'text': 'wrong'
            },
        )
        svc._wake_template_threshold = 0.62
        svc._wake_profile_candidate_audio = np.ones(3200, dtype=np.int16)
        svc._wake_profile_candidate_hits = 2
        svc._wake_profile_candidate_duration = 0.72
        self.assertTrue(svc._confirm_owner_wake_semantically(0.635))
        self.assertEqual([], calls)

    def test_borderline_single_hit_still_uses_semantic_veto(self):
        calls = []
        svc = VoiceEngineV2(
            Events(),
            VoiceV2Config(owner_wake_fast_accept_threshold=0.70),
            lambda _c: None,
            lambda _p: {},
            wake_transcribe_callback=lambda _p: calls.append('called') or {
                'ok': True,
                'text': 'O link está na descrição do vídeo.',
            },
        )
        svc._wake_template_threshold = 0.62
        svc._wake_profile_candidate_audio = np.ones(3200, dtype=np.int16)
        svc._wake_profile_candidate_hits = 1
        svc._wake_profile_candidate_duration = 0.72
        self.assertFalse(svc._confirm_owner_wake_semantically(0.635))
        self.assertEqual(['called'], calls)

    def test_inline_command_grace_override_returns_quickly_without_speech(self):
        svc = VoiceEngineV2(
            Events(), VoiceV2Config(frame_ms=80), lambda _c: None, lambda _p: {}
        )
        svc._read_frame16 = lambda *args, **kwargs: np.zeros(1280, dtype=np.int16)
        svc._vad_score = lambda _frame: 0.0
        started = time.monotonic()
        result = svc._capture_command(
            object(),
            source_rate=16000,
            channels=1,
            frames_per_buffer=1280,
            start_timeout_seconds=0.15,
        )
        elapsed = time.monotonic() - started
        self.assertIsNone(result)
        self.assertLess(elapsed, 0.8)

    def test_followup_capture_preserves_startup_speech_contract(self):
        text = Path('jarvis_core/services/listening.py').read_text(encoding='utf-8')
        self.assertIn('MIC_STARTUP_SPEECH_RECOVERED', text)
        self.assertIn('startup_blocks', text)
        self.assertIn('calibration_audio', text)


if __name__ == '__main__':
    unittest.main()
