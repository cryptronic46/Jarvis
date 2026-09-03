from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.core.events import EventBus
from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2, VoiceV2Config
from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class DummyEvents:
    def __init__(self):
        self.rows = []

    def emit(self, name, **data):
        self.rows.append((name, data))


class FakeWhisperModel:
    def transcribe(
        self,
        audio,
        *,
        language=None,
        beam_size=1,
        vad_filter=False,
        vad_parameters=None,
        condition_on_previous_text=False,
        temperature=0.0,
        without_timestamps=True,
    ):
        raise AssertionError("decode not expected in kwargs test")


class FalseWakeHardening0254Tests(unittest.TestCase):
    def test_legacy_saved_threshold_cannot_weaken_runtime_floor(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "wake.npz"
            template = np.zeros((12, 27), dtype=np.float32)
            np.savez_compressed(
                profile,
                count=np.asarray(3, dtype=np.int32),
                threshold=np.asarray(0.62, dtype=np.float32),
                template_0=template,
                template_1=template,
                template_2=template,
                duration_0=np.asarray(0.7, dtype=np.float32),
                duration_1=np.asarray(0.7, dtype=np.float32),
                duration_2=np.asarray(0.7, dtype=np.float32),
            )
            events = DummyEvents()
            svc = WakeWordService(
                events,
                WakeWordConfig(template_path=str(profile), wake_match_floor=0.72),
                on_wake=lambda command: None,
                transcribe_callback=lambda path: {"ok": False},
            )
            self.assertAlmostEqual(0.72, svc._template_threshold)
            self.assertTrue(any(name == "WAKE_THRESHOLD_HARDENED" for name, _ in events.rows))

    def test_wake_and_command_decode_use_vad(self):
        with tempfile.TemporaryDirectory() as td:
            mic = MicrophoneService(EventBus(log_dir=td), ListeningConfig())
            model = FakeWhisperModel()
            wake = mic._transcribe_kwargs(model, "wake")
            command = mic._transcribe_kwargs(model, "command")
            self.assertTrue(wake["vad_filter"])
            self.assertIn("vad_parameters", wake)
            self.assertTrue(command["vad_filter"])
            self.assertIn("vad_parameters", command)

    def test_v2_vad_vetoes_even_high_keyword_score(self):
        svc = VoiceEngineV2(
            DummyEvents(),
            VoiceV2Config(wake_threshold=0.62, wake_vad_threshold=0.50),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": False},
        )
        accepted, reason = svc._wake_gate(0.95, 0.20, now=10.0)
        self.assertFalse(accepted)
        self.assertEqual("vad_rejected", reason)

    def test_v2_keyword_score_wakes_immediately_when_vad_agrees(self):
        svc = VoiceEngineV2(
            DummyEvents(),
            VoiceV2Config(wake_threshold=0.45, wake_vad_threshold=0.35),
            on_wake=lambda _cmd: None,
            transcribe_callback=lambda _path: {"ok": True, "text": ""},
        )
        accepted, reason = svc._wake_gate(0.61, 0.8)
        self.assertTrue(accepted)
        self.assertEqual("vad+kws", reason)

    def test_v2_strong_score_can_wake_immediately_when_vad_agrees(self):
        svc = VoiceEngineV2(
            DummyEvents(),
            VoiceV2Config(
                wake_threshold=0.62,
                wake_vad_threshold=0.50,
                wake_strong_threshold=0.82,
            ),
            on_wake=lambda command: None,
            transcribe_callback=lambda path: {"ok": False},
        )
        accepted, reason = svc._wake_gate(0.90, 0.90, now=10.0)
        self.assertTrue(accepted)
        self.assertEqual("vad+kws", reason)


if __name__ == "__main__":
    unittest.main()
