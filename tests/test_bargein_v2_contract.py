import unittest
from pathlib import Path


class BargeInV2ContractTests(unittest.TestCase):
    def test_candidate_sources_are_independent(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertIn("acoustic_match", text)
        self.assertIn("strong_voice_spike", text)
        self.assertIn(
            "acoustic_match\n                            or strong_voice_spike",
            text,
        )

    def test_edge_mci_pause_resume_commands_exist(self):
        text = Path(
            "jarvis_core/services/speech.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'self._mci(f"pause {alias}")',
            text,
        )
        self.assertIn(
            'self._mci(f"resume {alias}")',
            text,
        )

    def test_whisper_is_final_authority(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        block = text[
            text.index("VOICE_INTERRUPT_CANDIDATE"):
            text.index(
                "VOICE_INTERRUPT_REJECTED_SELF_AUDIO"
            )
        ]
        self.assertIn(
            "_transcribe_interrupt_candidate",
            block,
        )
        self.assertIn(
            "_interrupt_transcript_confirmed",
            block,
        )


if __name__ == "__main__":
    unittest.main()
