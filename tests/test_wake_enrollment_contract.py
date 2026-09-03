import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from jarvis_core.services.wakeword import WakeWordConfig, WakeWordService


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class WakeEnrollmentContractTests(unittest.TestCase):
    def make_service(self, path):
        return WakeWordService(
            DummyEvents(),
            WakeWordConfig(template_path=str(path)),
            on_wake=lambda command: None,
            transcribe_callback=lambda p: {"ok": True, "text": "abre o Brave"},
        )

    def make_wav(self, path, frequency, phase=0.0):
        sr = 16000
        t = np.arange(int(sr * 0.65), dtype=np.float32) / sr
        samples = (
            0.5 * np.sin(2 * np.pi * frequency * t + phase)
            + 0.22 * np.sin(2 * np.pi * (frequency * 2.2) * t)
        )
        pcm = np.clip(samples, -1, 1)
        pcm = (pcm * 32767).astype("<i2")

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())

    def test_enrollment_saves_and_reloads_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "wake.npz"
            wavs = []
            for i in range(5):
                p = Path(tmp) / f"{i}.wav"
                self.make_wav(p, 420, phase=i * 0.015)
                wavs.append(p)

            service = self.make_service(profile)
            result = service.enroll(wavs)
            self.assertTrue(result["ok"], result)
            self.assertTrue(profile.exists())
            self.assertTrue(service.enrolled())

            reloaded = self.make_service(profile)
            self.assertTrue(reloaded.enrolled())
            self.assertEqual(len(reloaded._templates), 5)

    def test_start_requires_enrollment(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp) / "missing.npz")
            result = service.start()
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"], "WAKE_NOT_ENROLLED")


if __name__ == "__main__":
    unittest.main()
