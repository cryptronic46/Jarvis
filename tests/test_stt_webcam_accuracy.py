
import tempfile
import json
import unittest
import wave
from pathlib import Path

import numpy as np

from jarvis_core.services.listening import ListeningConfig, MicrophoneService
from jarvis_core.services.wakeword import WakeWordConfig
from jarvis_core.core.config import Settings


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class Segment:
    def __init__(self, text, avg_logprob=-0.4, no_speech_prob=0.05):
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


class RetryModel:
    def __init__(self):
        self.calls = []

    def transcribe(
        self,
        audio,
        language=None,
        beam_size=None,
        vad_filter=None,
        condition_on_previous_text=None,
        temperature=None,
        without_timestamps=None,
        initial_prompt=None,
        hotwords=None,
    ):
        self.calls.append(beam_size)
        if len(self.calls) == 1:
            segments = [Segment("abre o brabo", avg_logprob=-1.2, no_speech_prob=0.1)]
        else:
            segments = [Segment("abre o Brave", avg_logprob=-0.35, no_speech_prob=0.05)]
        info = type("Info", (), {"language": "pt", "language_probability": 1.0})()
        return segments, info


def make_wav(path: Path, amplitude=0.01, seconds=0.5, rate=16000):
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    sig = amplitude * np.sin(2 * np.pi * 220.0 * t)
    pcm = np.clip(sig * 32767.0, -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


class WebcamSttAccuracyTests(unittest.TestCase):
    def test_quiet_command_audio_is_normalized_without_clipping(self):
        service = MicrophoneService(DummyEvents(), ListeningConfig())
        audio = np.ones(16000, dtype=np.float32) * 0.01
        conditioned, meta = service._condition_audio(audio, profile="command")
        self.assertTrue(meta["conditioned"])
        self.assertGreaterEqual(meta["gain"], 1.0)
        self.assertLessEqual(float(np.max(np.abs(conditioned))), 0.98 + 1e-6)

    def test_command_decode_is_single_pass_beam_one(self):
        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "voice.wav"
            make_wav(wav, amplitude=0.08)
            service = MicrophoneService(DummyEvents(), ListeningConfig())
            model = RetryModel()
            service._model = model
            service._model_backend = "cpu/int8"
            result = service._transcribe(wav, profile="command")
            self.assertTrue(result["ok"])
            self.assertEqual(model.calls, [1])
            self.assertFalse(result["accuracy_retry_used"])

    def test_wake_command_defaults_are_webcam_tolerant(self):
        cfg = WakeWordConfig()
        self.assertGreaterEqual(cfg.command_preroll_seconds, 0.18)
        self.assertGreaterEqual(cfg.command_silence_seconds, 1.0)
        self.assertLess(cfg.command_threshold_ratio, 1.0)

    def test_wake_preroll_is_actually_applied(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        self.assertIn("command_start = max(0, int(keyword_end) - command_preroll)", text)
        self.assertIn("command_threshold_ratio", text)

    def test_manual_listen_uses_command_accuracy_profile(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("result = microphone.transcribe_command_file(wav_path)", text)
        self.assertIn('if lower == "/stt test":', text)

    def test_exact_0233_stt_defaults_are_migrated(self):
        legacy_prompt = (
            "Português europeu. Assistente Jarvis. "
            "Comandos e perguntas naturais. "
            "Brave, Spotify, Steam, Discord, Cyberpunk 2077, "
            "volume, áudio, GPU, gráfica, CPU, temperatura."
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "wake_stt_beam_size": 3,
                "wake_command_silence_seconds": 0.8,
                "wake_command_preroll_seconds": 0.12,
                "wake_stt_initial_prompt": legacy_prompt,
            }), encoding="utf-8")
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["wake_stt_beam_size"], 1)
        self.assertEqual(data["wake_command_silence_seconds"], 1.0)
        self.assertEqual(data["wake_command_preroll_seconds"], 0.42)
        self.assertIn("Transcrição fiel", data["wake_stt_initial_prompt"])
        self.assertEqual(result["accuracy_migrated_count"], 4)



if __name__ == "__main__":
    unittest.main()
