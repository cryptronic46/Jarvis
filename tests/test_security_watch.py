import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.services.security_watch import SecurityWatchStore

def audit(admins=None,remote=None,defender=True,firewall=True,macs=None):
    return {'ok':True,'accounts':{'other_enabled_or_unknown_admin_principals':[{'sid':x} for x in (admins or [])]},'sessions':{'remote_sessions':[{'domain':'PC','username':x,'client_name':'REMOTE'} for x in (remote or [])]},'network':{'remote_access_software_running':[],'filtered':{'active_lan_devices':[{'mac':x} for x in (macs or [])]}},'windows_security':{'firewall':[{'enabled':firewall}],'defender':{'real_time_protection_enabled':defender},'rdp_enabled':False,'remote_assistance_enabled':False}}

class SecurityWatchTests(unittest.TestCase):
    def test_detects_new_admin_and_remote_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=SecurityWatchStore(Path(tmp)/'b.json',Path(tmp)/'s.json')
            with patch('jarvis_core.services.security_watch.run_security_audit',return_value=audit(macs=['AA'])): self.assertTrue(s.baseline()['ok'])
            with patch('jarvis_core.services.security_watch.run_security_audit',return_value=audit(admins=['S-1-X'],remote=['other'],macs=['AA'])): r=s.check()
            codes={x['code'] for x in r['alerts']}; self.assertIn('NEW_ADMIN',codes); self.assertIn('REMOTE_SESSION',codes)
if __name__=='__main__': unittest.main()
