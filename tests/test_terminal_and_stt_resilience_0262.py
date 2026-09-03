from __future__ import annotations

import unittest
from pathlib import Path

from jarvis_core.services.listening import ListeningConfig, MicrophoneService


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class VadAwareModel:
    def transcribe(
        self,
        audio,
        language=None,
        beam_size=None,
        vad_filter=None,
        vad_parameters=None,
        condition_on_previous_text=None,
        temperature=None,
        without_timestamps=None,
        initial_prompt=None,
        hotwords=None,
    ):
        return [], type("Info", (), {"language": "pt", "language_probability": 1.0})()


class TerminalAndSttResilience0262Tests(unittest.TestCase):
    def test_terminal_input_releases_silence_latch(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('source="explicit_terminal_input"', text)
        self.assertIn('source="explicit_terminal_wake"', text)
        self.assertIn(r'jarvis(?=$|[\s,;:!?.-])', text)

    def test_stt_test_really_prints_listening_prompt(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('JARVIS > A ouvir... fala agora.', text)
        self.assertIn('STT_DIAGNOSTIC_AUDIO_SAVED', text)
        self.assertIn('audio_diagnostics', text)

    def test_punctuation_only_whisper_output_is_not_speech(self):
        service = MicrophoneService(DummyEvents(), ListeningConfig())
        self.assertFalse(service._meaningful_transcript(". . . . ."))
        self.assertFalse(service._meaningful_transcript("...!?"))
        self.assertTrue(service._meaningful_transcript("Olá Jarvis"))
        self.assertTrue(service._meaningful_transcript("GPU 5070"))

    def test_command_profile_uses_vad(self):
        service = MicrophoneService(DummyEvents(), ListeningConfig())
        kwargs = service._transcribe_kwargs(VadAwareModel(), "command")
        self.assertTrue(kwargs["vad_filter"])
        self.assertIn("vad_parameters", kwargs)
        self.assertGreaterEqual(kwargs["vad_parameters"]["min_silence_duration_ms"], 250)

    def test_voice_v2_default_uses_openwakeword_reference_threshold_with_extra_gates(self):
        from jarvis_core.services.voice_engine_v2 import VoiceV2Config
        cfg = VoiceV2Config()
        self.assertAlmostEqual(0.45, cfg.wake_threshold)
        self.assertAlmostEqual(0.35, cfg.wake_vad_threshold)
        self.assertEqual(1, cfg.wake_confirm_frames)

    def test_exact_0261_v2_threshold_is_migrated_but_owner_tuning_is_preserved(self):
        import json
        import tempfile
        from jarvis_core.core.config import Settings
        with tempfile.TemporaryDirectory() as td:
            shipped = Path(td) / "shipped.json"
            shipped.write_text(json.dumps({"voice_v2_wake_threshold": 0.62}), encoding="utf-8")
            Settings.ensure_file_schema(shipped)
            self.assertGreaterEqual(json.loads(shipped.read_text(encoding="utf-8"))["voice_v2_wake_threshold"], 0.40)
            tuned = Path(td) / "tuned.json"
            tuned.write_text(json.dumps({"voice_v2_wake_threshold": 0.70}), encoding="utf-8")
            Settings.ensure_file_schema(tuned)
            self.assertAlmostEqual(0.70, json.loads(tuned.read_text(encoding="utf-8"))["voice_v2_wake_threshold"])


if __name__ == "__main__":
    unittest.main()
