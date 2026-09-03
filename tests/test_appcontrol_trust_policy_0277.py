import unittest
from pathlib import Path


class AppControlTrustPolicy0277Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path('.')
        self.trust = (self.root / 'setup_appcontrol_trust.ps1').read_text(encoding='utf-8-sig')
        self.native = (self.root / 'setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        self.setup = (self.root / 'setup.ps1').read_text(encoding='utf-8-sig')

    def test_trust_script_is_sac_derived_and_hash_only_for_jarvis_runtime(self):
        self.assertIn('SmartAppControl.xml', self.trust)
        self.assertIn('Enabled:Conditional Windows Lockdown Policy', self.trust)
        self.assertIn("New-CIPolicyRule -Level Hash", self.trust)
        self.assertNotIn('New-CIPolicyRule -Level FilePath', self.trust)
        self.assertIn("broad_path_rules_added = $false", self.trust)
        self.assertIn("jarvis_rule_level = 'Hash'", self.trust)
        self.assertIn('llama-server-impl.dll', self.trust)
        self.assertIn('llama-server.exe', self.trust)

    def test_release_is_observe_only_and_has_no_enforce_mode(self):
        for mode in ('Prepare','Plan','Audit','Status','Disarm','Rollback'):
            self.assertIn(mode, self.trust)
        self.assertNotIn("if ($Mode -eq 'Enforce')", self.trust)
        self.assertNotIn("'Enforce'", self.trust.split('$ErrorActionPreference', 1)[0])
        self.assertNotIn('-ConfirmMigration', self.trust)
        self.assertNotIn('$EnforcedXml', self.trust)
        self.assertNotIn('$EnforcedCip', self.trust)
        self.assertNotIn('Set-RuleOption -FilePath $EnforcedXml -Option 3 -Delete', self.trust)
        self.assertIn("Set-RuleOption -FilePath $AuditXml -Option 3", self.trust)
        self.assertIn("Set-RuleOption -FilePath $AuditXml -Option 16", self.trust)
        self.assertIn("enforcement_available = $false", self.trust)

    def test_jarvis_never_changes_windows_sac_state(self):
        self.assertIn('VerifiedAndReputablePolicyState', self.trust)  # read-only status is retained
        self.assertNotIn('function Set-SacState', self.trust)
        self.assertNotIn('Set-SacState ', self.trust)
        self.assertNotIn('Set-SacState 0', self.trust)

    def test_disarm_removes_only_jarvis_non_system_policies(self):
        self.assertIn('function Disarm-JarvisAppControl', self.trust)
        self.assertIn('if ([bool]$Policy.IsSystemPolicy) { return $false }', self.trust)
        self.assertIn('JARVIS Smart App Control Derived*', self.trust)
        self.assertIn('JARVIS ASUS Compatibility*', self.trust)
        self.assertIn('JARVIS App Control Observe-Only*', self.trust)
        self.assertIn("'{3923ff78-eba0-4270-a28d-e82a66c531d4}'", self.trust)
        self.assertIn("'{3ac0a4b7-9a65-41df-8751-8cbd46949270}'", self.trust)
        self.assertIn("Invoke-CiTool -Arguments @('-rp',$id)", self.trust)
        self.assertIn('Supplemental policies must be removed before their base policies.', self.trust)

    def test_audit_checks_that_audit_mode_is_present(self):
        self.assertIn("if ($options -notcontains 'Enabled:Audit Mode')", self.trust)
        self.assertIn("Save-State 'audit_observe_only'", self.trust)
        self.assertIn('Esta release nao possui caminho Enforce.', self.trust)

    def test_prepare_runtime_records_per_file_hashes_from_verified_archive(self):
        self.assertIn('$PrepareTrustedCudaRuntime', self.native)
        self.assertIn("Install-PinnedNativeRuntime 'cuda12'", self.native)
        self.assertIn('runtime_file_hashes = $runtimeHashes', self.native)
        self.assertIn('Get-FileHash -Algorithm SHA256', self.native)
        self.assertIn("security = 'sha256_verified_then_unblocked'", self.native)
        self.assertIn('runtime_file_hashes', self.trust)
        self.assertIn('Binario alterado depois da instalacao verificada', self.trust)

    def test_legacy_enforcement_state_cannot_disable_local_compat(self):
        self.assertNotIn("enforced_native_verified", self.native)
        self.assertNotIn("enforced_native_verified", self.setup)
        self.assertIn("$AllowCompatPython = 'True'", self.native)
        self.assertIn("$AllowCompatPython = 'True'", self.setup)

    def test_policy_management_uses_supported_configci_and_citool_primitives(self):
        for token in (
            'New-CIPolicyRule', 'Merge-CIPolicy', 'Set-CIPolicyIdInfo',
            'Set-CIPolicyVersion', 'Set-RuleOption', 'ConvertFrom-CIPolicy',
            'CiTool.exe', "'-up'", "'-rp'", "'-r'"
        ):
            self.assertIn(token, self.trust)

    def test_no_security_product_disable_commands_are_added(self):
        lowered = self.trust.lower()
        for forbidden in (
            'set-mppreference -disablerealtimemonitoring',
            'bcdedit /set testsigning',
            'bcdedit /set nointegritychecks',
            'set-executionpolicy unrestricted',
            'set-executionpolicy bypass',
            'disable-windowsoptionalfeature',
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == '__main__':
    unittest.main()
