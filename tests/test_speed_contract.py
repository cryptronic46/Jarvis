import json
import unittest
from pathlib import Path


class SpeedContractTests(unittest.TestCase):
    def test_optimized_defaults(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertEqual(data["think_mode"], "adaptive")
        self.assertEqual(data["stt_device"], "cpu")
        self.assertEqual(data["stt_beam_size"], 1)
        self.assertEqual(data["stt_cpu_threads"], 6)
        self.assertLessEqual(data["mic_silence_seconds"], 0.7)
        self.assertGreaterEqual(data["mic_calibration_cache_seconds"], 120)
        self.assertEqual(data["mic_preferred_samplerate"], 48000)

    def test_whisper_fast_options(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertIn('"vad_filter": bool(wake_profile or command_profile)', text)
        self.assertIn('wake_profile = profile_name == "wake"', text)
        self.assertIn('"temperature": 0.0', text)
        self.assertIn('"without_timestamps": True', text)
        self.assertIn('kwargs["cpu_threads"]', text)
        self.assertIn("MIC_CALIBRATION_CACHED", text)

    def test_llm_keep_alive_and_adaptive_thinking(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        perf = Path("jarvis_core/services/performance.py").read_text(encoding="utf-8")
        self.assertIn("ollama_keep_alive", text)
        self.assertIn("PerformancePlan", text)
        self.assertIn('"think": bool(plan.think)', text)
        self.assertIn("def plan(", perf)
        self.assertIn('profile="fast"', perf)
        self.assertIn('profile="deep"', perf)

    def test_background_warmup(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("microphone.preload_stt()", text)
        self.assertIn("brain.warmup()", text)
        self.assertIn('name="jarvis-warmup"', text)

    def test_tts_cache(self):
        text = Path("jarvis_core/services/speech.py").read_text(encoding="utf-8")
        self.assertIn("TTS_CACHE_HIT", text)
        self.assertIn("hashlib.sha256", text)


if __name__ == "__main__":
    unittest.main()
