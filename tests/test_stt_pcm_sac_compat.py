import importlib
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from jarvis_core.services.listening import ListeningConfig, MicrophoneService
import jarvis_core.services.stt_compat as stt_compat
from jarvis_core.services.stt_compat import (
    PyAVDecodeUnavailable,
    _build_pyav_stub,
    load_wav_pcm_float32,
)


class _Events:
    def emit(self, *_args, **_kwargs):
        return None


class _Segment:
    def __init__(self, text):
        self.text = text


class _Info:
    language = "pt"
    language_probability = 1.0


class _Model:
    def __init__(self):
        self.received = None

    def transcribe(
        self,
        audio,
        language=None,
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
        temperature=0.0,
        without_timestamps=True,
        initial_prompt=None,
        hotwords=None,
    ):
        self.received = audio
        return iter([_Segment(" teste PCM ")]), _Info()


class SttPcmSmartAppControlCompatibilityTests(unittest.TestCase):
    def _write_wav(self, path: Path, rate: int = 16000):
        samples = (
            np.sin(np.linspace(0, 4 * np.pi, rate // 20)) * 12000
        ).astype("<i2")
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(rate)
            stream.writeframes(samples.tobytes())
        return samples

    def test_pcm_loader_returns_float32_16khz(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.wav"
            original = self._write_wav(path, rate=48000)
            audio, meta = load_wav_pcm_float32(path)
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)
        self.assertEqual(meta["source_rate"], 48000)
        self.assertEqual(meta["target_rate"], 16000)
        self.assertTrue(meta["resampled"])
        self.assertAlmostEqual(len(audio), round(len(original) / 3), delta=1)

    def test_microphone_transcription_passes_numpy_not_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "capture.wav"
            self._write_wav(path)
            service = MicrophoneService(_Events(), ListeningConfig())
            model = _Model()
            text, info, kwargs, meta, quality = service._run_transcription(model, path)
        self.assertEqual(text, "teste PCM")
        self.assertIsInstance(model.received, np.ndarray)
        self.assertEqual(model.received.dtype, np.float32)
        self.assertEqual(meta["target_rate"], 16000)
        self.assertEqual(info.language, "pt")
        self.assertIn("beam_size", kwargs)

    def test_pyav_stub_fails_closed_for_media_decode(self):
        stub = _build_pyav_stub()
        self.assertTrue(getattr(stub, "__jarvis_pcm_only_pyav_stub__"))
        with self.assertRaises(PyAVDecodeUnavailable):
            stub.open("example.mp3")
        with self.assertRaises(PyAVDecodeUnavailable):
            stub.audio.resampler.AudioResampler(rate=16000)

    def test_loader_uses_temporary_pyav_stub_and_restores_sys_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp) / "faster_whisper"
            pkg.mkdir()
            (pkg / "__init__.py").write_text(
                "import av\n"
                "SAW_JARVIS_STUB = bool(getattr(av, '__jarvis_pcm_only_pyav_stub__', False))\n"
                "class WhisperModel: pass\n",
                encoding="utf-8",
            )
            saved = {
                name: module
                for name, module in list(sys.modules.items())
                if name == "faster_whisper" or name.startswith("faster_whisper.")
            }
            saved_av = sys.modules.pop("av", None)
            for name in list(saved):
                sys.modules.pop(name, None)
            old_cache = stt_compat._CACHED_WHISPER_MODEL
            stt_compat._CACHED_WHISPER_MODEL = None
            sys.path.insert(0, tmp)
            try:
                model_class = stt_compat.load_whisper_model_class()
                module = importlib.import_module("faster_whisper")
                self.assertEqual(model_class.__name__, "WhisperModel")
                self.assertTrue(module.SAW_JARVIS_STUB)
                self.assertNotIn("av", sys.modules)
            finally:
                sys.path.remove(tmp)
                stt_compat._CACHED_WHISPER_MODEL = old_cache
                for name in list(sys.modules):
                    if name == "faster_whisper" or name.startswith("faster_whisper."):
                        sys.modules.pop(name, None)
                sys.modules.update(saved)
                if saved_av is not None:
                    sys.modules["av"] = saved_av

    def test_listening_has_no_direct_faster_whisper_import(self):
        text = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        self.assertNotIn("from faster_whisper import WhisperModel", text)
        self.assertIn("load_whisper_model_class()", text)
        self.assertIn("model.transcribe(audio, **kwargs)", text)
        self.assertNotIn("model.transcribe(str(wav_path)", text)


if __name__ == "__main__":
    unittest.main()
