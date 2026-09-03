import json
import unittest
from pathlib import Path


class VoicePolicyTests(unittest.TestCase):
    def test_voice_id_remains_enabled_but_observe_only(self):
        data = json.loads(Path("settings.json").read_text(encoding="utf-8"))
        self.assertTrue(data["speaker_lock_enabled"])
        self.assertEqual(data["speaker_enforcement_mode"], "observe")

    def test_observe_mode_still_calls_verification(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("speaker.verify(", text)
        self.assertIn('"SPEAKER_OBSERVE"', text)
        self.assertIn('if mode == "enforce":', text)

    def test_audio_not_sent_to_cloud_contract(self):
        text = Path("jarvis_core/core/cloud_brain.py").read_text(encoding="utf-8")
        self.assertIn('"audio_sent_to_cloud": False', text)
        self.assertNotIn("wav_path", text)
        self.assertNotIn("transcribe_file", text)
        self.assertNotIn("capture_phrase", text)


if __name__ == "__main__":
    unittest.main()
