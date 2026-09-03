import unittest
from pathlib import Path

from jarvis_core.services.wakeword import WakeWordService


class SelfAudioInterruptGuardTests(unittest.TestCase):
    def test_interrupt_phrase_normalization_accepts_natural_variants(self):
        for phrase in (
            "Cala-te",
            "cala te!",
            "Jarvis, cala-te.",
            "cala-te por favor",
        ):
            self.assertTrue(
                WakeWordService._interrupt_transcript_confirmed(
                    phrase
                ),
                phrase,
            )

        for phrase in (
            "",
            "A segurança do sistema está normal.",
            "Jarvis continua a falar.",
        ):
            self.assertFalse(
                WakeWordService._interrupt_transcript_confirmed(
                    phrase
                ),
                phrase,
            )

    def test_tts_stop_requires_whisper_confirmation(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        start = text.index(
            "                    if self._audio_is_suppressed():"
        )
        end = text.index(
            "                    if not pending:",
            start,
        )
        block = text[start:end]

        transcribe = block.index(
            "_transcribe_interrupt_candidate"
        )
        confirm = block.index(
            "_interrupt_transcript_confirmed",
            transcribe,
        )
        callback = block.index(
            "self.on_interrupt()",
            confirm,
        )

        self.assertLess(transcribe, confirm)
        self.assertLess(confirm, callback)

    def test_candidate_can_be_acoustic_or_voice_spike(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "_match_interrupt_probe_sensitive",
            text,
        )
        self.assertIn("strong_voice_spike", text)
        self.assertIn(
            "VOICE_INTERRUPT_CANDIDATE",
            text,
        )

    def test_false_candidate_has_short_cooldown_and_resume_path(self):
        wake = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "monotonic() + 0.8",
            wake,
        )
        self.assertIn(
            "speech.resume_after_bargein()",
            cli,
        )

    def test_post_tts_tail_rejects_interrupt_candidates(self):
        text = Path(
            "jarvis_core/services/wakeword.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "or self._suppression_tail_active()",
            text,
        )


if __name__ == "__main__":
    unittest.main()
