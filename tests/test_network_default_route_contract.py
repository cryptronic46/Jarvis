import unittest
from pathlib import Path
class NetworkDefaultRouteContractTests(unittest.TestCase):
    def test_default_route_and_clean_status_contract(self):
        text=Path('jarvis_core/tools/security_audit.py').read_text(encoding='utf-8')
        self.assertIn('Get-NetRoute',text)
        self.assertIn('-DestinationPrefix "0.0.0.0/0"',text)
        self.assertIn('"default_routes": default_routes[:10]',text)
        start=text.index('def format_network_overview(')
        end=text.index('def format_network_devices(',start)
        block=text[start:end]
        self.assertNotIn('non_loopback_listeners',block)
        self.assertNotIn('mac',block.lower())
        self.assertNotIn('portas',block.lower())
if __name__ == '__main__': unittest.main()
