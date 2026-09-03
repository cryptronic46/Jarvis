import unittest
from pathlib import Path


class NativeRuntimeSecurity0277Tests(unittest.TestCase):
    def test_setup_probes_runtime_before_declaring_ready(self):
        text = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('Invoke-NativeRuntimeProbe', text)
        self.assertIn("--version", text)
        self.assertIn('if (-not $probe.ok)', text)
        self.assertIn('Runtime probe OK', text)

    def test_verified_archives_are_unblocked_only_after_sha256(self):
        text = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        main_hash = text.index('Assert-Sha256 $mainZip $LlamaMainSha256')
        main_unblock = text.index('Unblock-File -LiteralPath $mainZip')
        cuda_hash = text.index('Assert-Sha256 $cudaZip $LlamaCudaSha256')
        cuda_unblock = text.index('Unblock-File -LiteralPath $cudaZip')
        self.assertLess(main_hash, main_unblock)
        self.assertLess(cuda_hash, cuda_unblock)
        self.assertIn("security = 'sha256_verified_then_unblocked'", text)

    def test_bad_image_exit_is_detected_and_repaired(self):
        text = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('0xC0E90002', text)
        self.assertIn('Bad Image / Code Integrity', text)
        self.assertIn('Install-PinnedNativeRuntime', text)
        self.assertIn('[switch]$RepairRuntime', text)

    def test_runtime_reinstall_replaces_untrusted_existing_payload(self):
        text = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        verify_main = text.index('Assert-Sha256 $mainZip $LlamaMainSha256')
        verify_cuda = text.index('Assert-Sha256 $cudaZip $LlamaCudaSha256')
        remove_runtime = text.index('Get-ChildItem -LiteralPath $RuntimeDir -Force -ErrorAction SilentlyContinue | Remove-Item')
        self.assertLess(verify_main, remove_runtime)
        self.assertLess(verify_cuda, remove_runtime)

    def test_runtime_error_reports_hex_and_repair_command(self):
        text = Path('jarvis_core/core/local_llm.py').read_text(encoding='utf-8')
        self.assertIn('0xC0E90002', text)
        self.assertIn('Bad Image / Code Integrity', text)
        self.assertIn('setup_native_brain.ps1 -RepairRuntime', text)
        self.assertIn('code_hex', text)
        self.assertIn('log tail', text)


if __name__ == '__main__':
    unittest.main()
