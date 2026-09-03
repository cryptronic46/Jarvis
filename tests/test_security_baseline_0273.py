from pathlib import Path
import unittest

class SecurityBaseline0273Tests(unittest.TestCase):
    def test_repair_script_is_manifest_verified_and_preserves_history(self):
        text=Path('repair_security_baseline.ps1').read_text(encoding='utf-8')
        self.assertIn('Get-FileHash -Algorithm SHA256', text)
        self.assertIn('Unblock-File', text)
        self.assertIn("'sherpa-onnx'", text)
        self.assertIn("'scipy'", text)
        self.assertIn("'av'", text)
        self.assertIn('active -ne 0', text)
        self.assertIn('nenhum Event Log foi apagado', text)
    def test_audit_distinguishes_resolved_history(self):
        text=Path('jarvis_core/services/windows_block_audit.py').read_text(encoding='utf-8')
        self.assertIn('resolved_historical_block_events', text)
        self.assertIn('blocked_artifact_no_longer_present', text)
        self.assertIn('referenced_paths_existing', text)

if __name__=='__main__': unittest.main()
