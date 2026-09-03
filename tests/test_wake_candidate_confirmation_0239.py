import unittest
from pathlib import Path

from jarvis_core.services.wakeword import WakeWordService


class WakeCandidateConfirmation0239Tests(unittest.TestCase):
    def test_keyword_confirmation_accepts_jarvis_near_start(self):
        self.assertTrue(WakeWordService._wake_transcript_confirmed("Jarvis, abre o Brave."))
        self.assertTrue(WakeWordService._wake_transcript_confirmed("Ei Jarvis abre o Brave"))
        self.assertTrue(WakeWordService._wake_transcript_confirmed("Jervis, verifica a GPU"))

    def test_keyword_confirmation_rejects_normal_conversation(self):
        self.assertFalse(WakeWordService._wake_transcript_confirmed("Um abraço e até à próxima."))
        self.assertFalse(WakeWordService._wake_transcript_confirmed("Obrigado."))
        self.assertFalse(WakeWordService._wake_transcript_confirmed("Hoje falei com o Jarvis depois."))

    def test_runtime_requires_whisper_confirmation_before_detection(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        candidate = text.index('"WAKE_CANDIDATE"')
        confirm = text.index("_wake_candidate_result_confirmed", candidate)
        detected = text.index('"WAKE_WORD_DETECTED"', confirm)
        self.assertLess(candidate, confirm)
        self.assertLess(confirm, detected)

class IdleInterrupt0239Tests(unittest.TestCase):
    def test_idle_interrupt_is_two_stage_before_wake_match(self):
        text = Path("jarvis_core/services/wakeword.py").read_text(encoding="utf-8")
        idle_comment = text.index('"Cala-te" is an OWNER-priority interrupt even while')
        interrupt_match = text.index("_match_interrupt_probe", idle_comment)
        whisper_confirm = text.index("_interrupt_transcript_confirmed", interrupt_match)
        wake_match = text.index("matched, score, keyword_end = self._match_probe", whisper_confirm)
        self.assertLess(interrupt_match, whisper_confirm)
        self.assertLess(whisper_confirm, wake_match)
