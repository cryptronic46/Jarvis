import unittest
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.services.voice_engine_v2 import VoiceV2Config, VoiceEngineV2


class DummyEvents:
    def emit(self, *args, **kwargs):
        return None


class VoiceEngineV2ContractTests(unittest.TestCase):
    def test_settings_expose_backend_and_v2_tuning(self):
        s = Settings()
        self.assertEqual("v2", s.voice_input_backend)
        self.assertEqual("small", s.voice_v2_stt_model)
        self.assertEqual("cpu", s.voice_v2_stt_device)
        self.assertTrue(s.voice_v2_preload_stt)
        self.assertTrue(s.voice_v2_vram_handoff_enabled)

    def test_v2_architecture_is_minimal_vad_kws_stt(self):
        text = Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn("Silero VAD", text)
        self.assertIn("openWakeWord", text)
        self.assertIn("self._oww_model.predict(kws_frame)", text)
        self.assertIn("wake_preroll", text)
        self.assertIn("kws_hangover", text)
        self.assertIn("vad_score", text)
        self.assertNotIn("VOICE_V2_WAKE_VERIFIER_REJECTED", text)

    def test_only_wasapi_inputs_are_selected(self):
        text = Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn("get_host_api_info_by_type(pa.paWASAPI)", text)
        self.assertIn('"Windows WASAPI"', text)

    def test_legacy_sounddevice_index_requires_name_agreement(self):
        text = Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn("legacy sounddevice indices", text)
        self.assertIn("expected_name", text)

    def test_stt_has_explicit_release_contract(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn("def release_stt", text)
        self.assertIn("STT_MODEL_RELEASED", text)

    def test_cli_has_v2_doctor_benchmark_and_backend_switch(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('if lower == "/voice doctor":', text)
        self.assertIn('/voice benchmark', text)
        self.assertIn('/voice latency', text)
        self.assertIn('if lower.startswith("/voice backend "):', text)
        self.assertIn("VOICE_V2_UNAVAILABLE_NO_LEGACY_FALLBACK", text)

    def test_openwakeword_score_picks_jarvis_key_only(self):
        svc = VoiceEngineV2(
            DummyEvents(),
            VoiceV2Config(),
            on_wake=lambda command: None,
            transcribe_callback=lambda p: {"ok": True, "text": ""},
        )
        score, key = svc._jarvis_score({"alexa": 0.99, "hey_jarvis": 0.61})
        self.assertAlmostEqual(0.61, score)
        self.assertEqual("hey_jarvis", key)

    def test_vram_handoff_exists_in_both_directions(self):
        cli = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        voice = Path("jarvis_core/services/voice_engine_v2.py").read_text(encoding="utf-8")
        self.assertIn("voice_v2_stt_handoff", cli)
        self.assertIn("VOICE_V2_VRAM_TO_REASONING", cli)
        self.assertIn("before_stt_callback", voice)
        self.assertIn("VOICE_V2_VRAM_TO_STT", voice)


if __name__ == "__main__":
    unittest.main()
