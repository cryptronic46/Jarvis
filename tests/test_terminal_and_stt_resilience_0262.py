from __future__ import annotations

import unittest
from pathlib import Path



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
        self.assertIn('source="explicit_terminal_address"', text)
        self.assertIn(r'jarvis(?=$|[\s,;:!?.-])', text)







if __name__ == "__main__":
    unittest.main()
