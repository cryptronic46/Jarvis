import json
import unittest
from unittest.mock import patch
from jarvis_core.tools.location_tools import get_windows_precise_location,get_precise_location
class Completed:
    returncode=0; stderr=''; stdout=json.dumps({'ok':True,'source':'windows_location_service','latitude':40.8731,'longitude':-8.6742,'accuracy_m':15.0})
class PreciseLocationTests(unittest.TestCase):
    @patch('jarvis_core.tools.location_tools.subprocess.run',return_value=Completed())
    def test_windows_location_fixed_script(self,mocked):
        r=get_windows_precise_location(); self.assertTrue(r['ok']); self.assertEqual(mocked.call_args.args[0][0],'powershell.exe')
    @patch('jarvis_core.tools.location_tools.get_configured_location')
    @patch('jarvis_core.tools.location_tools.get_windows_precise_location')
    def test_fallback_not_ip(self,win,conf):
        win.return_value={'ok':False,'error':'WINDOWS_LOCATION_UNAVAILABLE'}; conf.return_value={'ok':True,'source':'configured_coordinates','label':'Furadouro, Ovar','latitude':40.87306,'longitude':-8.67424}
        r=get_precise_location(); self.assertEqual(r['source'],'configured_coordinates'); self.assertNotIn('public_ip',json.dumps(r).lower())
if __name__=='__main__': unittest.main()
