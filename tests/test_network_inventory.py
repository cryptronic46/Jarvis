import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.services.network_inventory import NetworkInventory
class NetworkInventoryTests(unittest.TestCase):
    def test_refresh_and_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            inv=NetworkInventory(Path(tmp)/'n.json'); snap={'ok':True,'filtered':{'active_lan_devices':[{'ip':'192.168.1.10','mac':'AA-BB-CC-DD-EE-FF','interface':'Wi-Fi','state':'Reachable'}],'lan_devices':[{'ip':'192.168.1.10','mac':'AA-BB-CC-DD-EE-FF','interface':'Wi-Fi','state':'Reachable'}]}}
            with patch('jarvis_core.services.network_inventory.get_network_security_snapshot',return_value=snap): r=inv.refresh()
            self.assertEqual(r['active_count'],1); self.assertEqual(inv.label('192.168.1.10','TV')['device']['label'],'TV')
if __name__=='__main__': unittest.main()
