from pathlib import Path
import unittest


class WakeFollowup0266ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = Path('jarvis_core/cli.py').read_text(encoding='utf-8')

    def test_wake_only_acknowledges_naturally(self):
        self.assertIn('print("JARVIS > Sim, Senhor?")', self.cli)
        self.assertIn('speech.say("Sim, Senhor?")', self.cli)
        self.assertNotIn("Ouvi 'Jarvis', mas não veio um comando na mesma frase.", self.cli)

    def test_wake_only_starts_followup_listener(self):
        self.assertIn('def _listen_after_wake_only()', self.cli)
        self.assertIn('handle_voice_command(source="wake_followup")', self.cli)
        self.assertIn('name="jarvis-wake-followup"', self.cli)
        self.assertIn('followup_listening=True', self.cli)

    def test_duplicate_wake_only_is_suppressed_while_pending(self):
        self.assertIn('wake_followup_state = {"pending": False}', self.cli)
        self.assertIn('WAKE_ONLY_DUPLICATE_SUPPRESSED', self.cli)
        self.assertIn('wake_followup_state["pending"] = False', self.cli)


if __name__ == '__main__':
    unittest.main()
