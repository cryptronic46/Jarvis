import unittest
from unittest.mock import patch
from jarvis_core.tools.location_tools import get_precise_location,get_configured_location

class FakeStore:
    def profile(self): return {'home':{'label':'Furadouro, Ovar','locality':'Furadouro','municipality':'Ovar','country':'Portugal','latitude':40.87306,'longitude':-8.67424}}
class LocationToolTests(unittest.TestCase):
    @patch('jarvis_core.tools.location_tools.store',return_value=FakeStore())
    def test_configured_location(self,mock_store):
        r=get_configured_location(); self.assertTrue(r['ok']); self.assertEqual(r['label'],'Furadouro, Ovar'); self.assertEqual(r['source'],'configured_coordinates')
    @patch('jarvis_core.tools.location_tools.get_configured_location')
    @patch('jarvis_core.tools.location_tools.get_windows_precise_location')
    def test_precise_fallback(self,win,conf):
        win.return_value={'ok':False,'error':'X'}; conf.return_value={'ok':True,'source':'configured_coordinates','label':'Furadouro, Ovar','latitude':40.87306,'longitude':-8.67424}
        r=get_precise_location(); self.assertTrue(r['ok']); self.assertEqual(r['source'],'configured_coordinates')
if __name__=='__main__': unittest.main()
