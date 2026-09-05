import json
import unittest
from pathlib import Path

import numpy as np

from jarvis_core.services.speaker_verification import SpeakerVerifier, CAMPLUS_SHA256


class SpeakerLockContractTests(unittest.TestCase):
    def test_normalize_embedding(self):
        x = np.array([3.0, 4.0], dtype=np.float32)
        y = SpeakerVerifier._normalize_embedding(x)
        self.assertAlmostEqual(float(np.linalg.norm(y)), 1.0, places=5)

    def test_camplus_contract_is_preserved_but_disabled_by_default(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertFalse(data["local_voice_enabled"])
        self.assertFalse(data["speaker_lock_enabled"])
        self.assertIn("campplus", data["speaker_model_path"].lower())
        self.assertEqual(data["speaker_model_sha256"], CAMPLUS_SHA256)
        self.assertGreaterEqual(data["speaker_threshold"], 0.40)

    def test_no_speechbrain_dependency_in_voiceid_backend(self):
        text = Path("jarvis_core/services/speaker_verification.py").read_text(encoding="utf-8")
        self.assertNotIn("speechbrain", text.lower())
        self.assertNotIn("scipy", text.lower())
        self.assertIn("torch.jit.load", text)
        self.assertIn("torchaudio.compliance.kaldi", text)

    def test_cli_verifies_before_transcription(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        verify_pos = text.find("verification = speaker.verify(")
        transcribe_pos = text.find("result = microphone.transcribe_command_file(wav_path)")
        self.assertGreaterEqual(verify_pos, 0)
        self.assertGreater(transcribe_pos, verify_pos)

    def test_enrollment_preflights_model(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        enroll_pos = text.find('if lower == "/voiceid enroll":')
        ready_pos = text.find("readiness = speaker.ensure_ready()", enroll_pos)
        captures_pos = text.find("captures = []", enroll_pos)
        self.assertGreater(ready_pos, enroll_pos)
        self.assertGreater(captures_pos, ready_pos)

    def test_enrollment_recordings_are_cleaned(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("microphone.cleanup_capture(wav)", text)


if __name__ == "__main__":
    unittest.main()
