import unittest
from jarvis_core.tools.security_audit import (
    _usable_lan_neighbor,
    _active_lan_neighbor,
    _meaningful_connection,
    _primary_interfaces,
    format_network_overview,
    format_network_devices,
)

class SecurityFilteredOutputTests(unittest.TestCase):
    def test_stale_is_known_but_not_active(self):
        stale={"ip":"192.168.1.121","mac":"F4-30-8B-3B-E3-F2","state":"Stale"}
        reachable={"ip":"192.168.1.65","mac":"54-7E-1A-0C-20-8F","state":"Reachable"}
        self.assertTrue(_usable_lan_neighbor(stale))
        self.assertFalse(_active_lan_neighbor(stale))
        self.assertTrue(_active_lan_neighbor(reachable))

    def test_default_route_selects_wifi(self):
        interfaces=[
            {"name":"Ethernet 2","is_up":True,"speed_mbps":1000,"addresses":[{"family":"IPv4","address":"192.168.56.1","scope":"private"}]},
            {"name":"Wi-Fi","is_up":True,"speed_mbps":866,"addresses":[{"family":"IPv4","address":"192.168.1.70","scope":"private"}]},
        ]
        result=_primary_interfaces(interfaces,["Wi-Fi"])
        self.assertEqual(result[0]["name"],"Wi-Fi")

    def test_network_status_is_six_lines_and_clean(self):
        data={"ok":True,"counts":{"lan_devices_active":3,"public_established":8},"filtered":{"active_interfaces":[{"name":"Wi-Fi","ipv4":["192.168.1.70"],"speed_mbps":866,"is_default_route":True}]},"remote_access_software_running":[]}
        text=format_network_overview(data)
        self.assertLessEqual(len(text.splitlines()),6)
        self.assertIn("Wi-Fi · 192.168.1.70 · 866 Mbps",text)
        self.assertIn("Dispositivos ativos na rede: 3",text)
        self.assertIn("Ligações à Internet: 8",text)
        self.assertIn("Acesso remoto: não detetado.",text)
        self.assertNotIn("Stale",text)
        self.assertNotIn("Portas",text)
        self.assertNotIn("MAC",text)

    def test_devices_separate_stale(self):
        data={"ok":True,"filtered":{"active_lan_devices":[{"ip":"192.168.1.65","mac":"54-7E-1A-0C-20-8F","state":"Reachable"}],"lan_devices":[{"ip":"192.168.1.65","mac":"54-7E-1A-0C-20-8F","state":"Reachable"},{"ip":"192.168.1.121","mac":"F4-30-8B-3B-E3-F2","state":"Stale"}]}}
        self.assertNotIn("192.168.1.121",format_network_devices(data))
        self.assertIn("192.168.1.121",format_network_devices(data,include_stale=True))

if __name__ == '__main__': unittest.main()
