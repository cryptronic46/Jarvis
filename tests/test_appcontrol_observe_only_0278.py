import unittest
from pathlib import Path


class AppControlObserveOnly0278Tests(unittest.TestCase):
    def test_enforcement_artifacts_and_sac_writes_are_absent(self):
        trust = Path('setup_appcontrol_trust.ps1').read_text(encoding='utf-8-sig')
        self.assertNotIn('JARVIS_SAC_Derived_Enforced', trust)
        self.assertNotIn("-Mode Enforce", trust)
        self.assertNotIn('ConfirmMigration', trust)
        self.assertNotIn('function Set-SacState', trust)
        self.assertNotIn("Save-State 'enforced_native_verified'", trust)

    def test_disarm_knows_live_machine_legacy_policy_ids(self):
        trust = Path('setup_appcontrol_trust.ps1').read_text(encoding='utf-8-sig').lower()
        self.assertIn('3923ff78-eba0-4270-a28d-e82a66c531d4', trust)
        self.assertIn('3ac0a4b7-9a65-41df-8751-8cbd46949270', trust)
        self.assertIn('policyissystempolicy', trust.replace('.', ''))

    def test_setup_and_native_brain_ignore_legacy_enforcement_state(self):
        setup = Path('setup.ps1').read_text(encoding='utf-8-sig')
        native = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        for text in (setup, native):
            self.assertNotIn('enforced_native_verified', text)
            self.assertIn("$AllowCompatPython = 'True'", text)


if __name__ == '__main__':
    unittest.main()
