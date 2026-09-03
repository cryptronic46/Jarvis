from pathlib import Path
import unittest
import json
from tempfile import TemporaryDirectory

from jarvis_core.core.config import Settings
from jarvis_core.services.listening import ListeningConfig
from jarvis_core.services.wakeword import WakeWordConfig


class MicWebcam48kStereo0274Tests(unittest.TestCase):
    def test_defaults_prefer_general_webcam_48k(self):
        s = Settings()
        self.assertEqual(s.mic_preferred_device_name, "GENERAL WEBCAM")
        self.assertFalse(s.mic_preferred_handsfree)
        self.assertEqual(s.mic_preferred_samplerate, 48000)
        self.assertEqual(ListeningConfig().preferred_samplerate, 48000)
        self.assertEqual(WakeWordConfig().preferred_samplerate, 48000)

    def test_cli_distinguishes_selected_from_windows_default(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('d.get("is_selected")', text)
        self.assertIn('* = microfone selecionado pelo JARVIS', text)
        self.assertIn('D = predefinido do Windows', text)
        self.assertIn('"persisted"', text)

    def test_candidate_ranking_prefers_stereo(self):
        listening = Path("jarvis_core/services/listening.py").read_text(encoding="utf-8")
        wake = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        self.assertIn("channels >= 2", listening)
        self.assertIn("channels >= 2", wake)

    def test_legacy_jbl_binding_is_persistently_migrated(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({
                "mic_preferred_device_name": "JBL WAVE BEAM",
                "mic_preferred_handsfree": True,
                "mic_preferred_samplerate": 16000,
            }), encoding="utf-8")
            result = Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["mic_preferred_device_name"], "GENERAL WEBCAM")
            self.assertFalse(data["mic_preferred_handsfree"])
            self.assertEqual(data["mic_preferred_samplerate"], 48000)
            self.assertEqual(result["mic_binding_migrated_count"], 3)


if __name__ == "__main__":
    unittest.main()
