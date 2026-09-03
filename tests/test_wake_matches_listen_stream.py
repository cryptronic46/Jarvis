import unittest
from pathlib import Path


class WakeMatchesListenStreamTests(unittest.TestCase):
    def test_both_paths_use_raw_callback_int16(self):
        listening = Path(
            "jarvis_core/services/listening.py"
        ).read_text(encoding="utf-8")
        wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")

        for source in (listening, wake):
            self.assertIn("sd.RawInputStream(", source)
            self.assertIn('dtype="int16"', source)
            self.assertIn("callback=callback", source)

    def test_wake_does_not_use_portaudio_blocking_api(self):
        wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("stream.read(", wake)


if __name__ == "__main__":
    unittest.main()
