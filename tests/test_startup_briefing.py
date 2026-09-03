import unittest
from datetime import datetime
from unittest.mock import patch
from jarvis_core.services.startup_briefing import build_startup_briefing
class FakeMemory:
    def profile(self): return {'name':'Tiago','address_as':'Senhor','home':{'label':'Furadouro, Ovar'}}
class StartupBriefingTests(unittest.TestCase):
    @patch('jarvis_core.services.startup_briefing.store')
    @patch('jarvis_core.services.startup_briefing.get_home_environment')
    @patch('jarvis_core.services.startup_briefing.format_environment_summary')
    def test_briefing(self,fmt,env,mem):
        mem.return_value=FakeMemory(); env.return_value={'ok':True}; fmt.return_value='Em Furadouro, está encoberto com 21 graus e 70 por cento de humidade. O mar está agitado.'
        text=build_startup_briefing(datetime(2026,8,28,12,28))['text']; self.assertIn('Boa tarde, Senhor.',text); self.assertIn('12 horas e 28 minutos',text); self.assertIn('humidade',text)
if __name__=='__main__': unittest.main()
