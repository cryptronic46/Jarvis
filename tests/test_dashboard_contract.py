import unittest
from pathlib import Path
class DashboardContractTests(unittest.TestCase):
    def test_dashboard_has_sections(self):
        t=Path('jarvis_core/tools/dashboard_tools.py').read_text(encoding='utf-8')
        for key in ('"profile"','"privacy"','"environment"','"pc_health"','"agenda"','"security_watch"','"network"','"integrations"','"ui_contract_version"'): self.assertIn(key,t)
if __name__=='__main__': unittest.main()
