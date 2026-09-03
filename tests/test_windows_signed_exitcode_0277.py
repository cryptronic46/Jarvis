import unittest
from pathlib import Path


class WindowsSignedExitCode0277Tests(unittest.TestCase):
    def setUp(self):
        self.text = Path("repair_security_baseline.ps1").read_text(encoding="utf-8-sig")

    def test_negative_windows_exit_code_is_reinterpreted_not_cast_directly(self):
        self.assertIn("function Format-WindowsExitCode", self.text)
        self.assertIn("[System.BitConverter]::GetBytes([int]$Code)", self.text)
        self.assertIn("[System.BitConverter]::ToUInt32($Bytes, 0)", self.text)
        self.assertNotIn("[uint32]$LlamaCode", self.text)

    def test_llama_probe_failure_waits_for_compatibility_probe(self):
        self.assertIn("NATIVE_UNAVAILABLE_PENDING_COMPAT_CHECK", self.text)
        self.assertIn("O passo 6 vai verificar o executor local alternativo", self.text)
        self.assertNotIn('Fail "llama-server atual nao carrega', self.text)
        step5 = self.text.index('Write-Host "5/6 A validar o executavel')
        step6 = self.text.index('Write-Host "6/6 A repetir Windows Block Audit')
        compat = self.text.index('COMPAT_OK', step6)
        self.assertLess(step5, step6)
        self.assertGreater(compat, step6)

    def test_reported_signed_code_matches_windows_status_bits(self):
        signed = -1058471934
        self.assertEqual(f"0x{signed & 0xFFFFFFFF:08X}", "0xC0E90002")


if __name__ == "__main__":
    unittest.main()
