import unittest
from pathlib import Path
class PersonalOpsCliTests(unittest.TestCase):
    def test_new_commands_exist(self):
        t=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        for c in ('/profile status','/watch status','/pc checkup','/routine list','/files index','/agenda today','/privacy status','/integrations','/dashboard data'): self.assertIn(c,t)
if __name__=='__main__': unittest.main()
