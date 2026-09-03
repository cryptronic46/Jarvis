import ast
import unittest
from pathlib import Path

class WindowsBlockAuditContractTests(unittest.TestCase):
    def setUp(self):
        self.service=Path("jarvis_core/services/windows_block_audit.py").read_text(encoding="utf-8")

    def test_preflight_before_cli_import(self):
        launcher=Path("jarvis.py").read_text(encoding="utf-8")
        self.assertLess(launcher.index("startup_preflight()"),launcher.index("from jarvis_core.cli import main"))

    def test_service_stdlib_only(self):
        tree=ast.parse(self.service)
        roots=set()
        for node in tree.body:
            if isinstance(node,ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        allowed={"__future__","concurrent","datetime","pathlib","time","typing","json","os","platform","re","subprocess","sys","urllib"}
        self.assertTrue(roots<=allowed,roots-allowed)

    def test_read_only_collectors(self):
        self.assertIn("Get-WinEvent",self.service)
        for token in ("3077","8004","8007","3004","3033"):
            self.assertIn(token,self.service)
        for token in ("Unblock-File","Remove-Item","Set-AppLockerPolicy","Set-ItemProperty","New-CIPolicy","Set-RuleOption"):
            self.assertNotIn(token,self.service)

    def test_cli_commands(self):
        cli=Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        for cmd in ("/security blocked files","/security blocked files full","/security blocked files raw"):
            self.assertIn(f'lower == "{cmd}"',cli)

    def test_tool_read_only(self):
        reg=Path("jarvis_core/core/tool_registry.py").read_text(encoding="utf-8")
        pos=reg.index('"get_windows_block_audit"')
        self.assertIn("RiskLevel.READ_ONLY",reg[pos:pos+1600])

if __name__=="__main__":
    unittest.main()
