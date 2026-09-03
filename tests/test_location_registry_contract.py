import unittest
from pathlib import Path

class LocationRegistryContractTests(unittest.TestCase):
    def test_precise_location_registered_read_only(self):
        text=Path('jarvis_core/core/tool_registry.py').read_text(encoding='utf-8')
        self.assertIn('"get_precise_location"',text); self.assertIn('get_precise_location,',text); self.assertIn('RiskLevel.READ_ONLY',text)
    def test_no_ip_provider(self):
        text=Path('jarvis_core/tools/location_tools.py').read_text(encoding='utf-8').lower()
        self.assertNotIn('ipapi.co',text); self.assertNotIn('public_ip_geolocation',text); self.assertIn('windows_location_service',text)
    def test_fixed_windows_location_script_no_user_interpolation(self):
        text=Path('jarvis_core/tools/location_tools.py').read_text(encoding='utf-8')
        self.assertIn('_WINDOWS_LOCATION_SCRIPT',text); self.assertIn('GeoCoordinateWatcher',text); self.assertIn('powershell.exe',text)
if __name__=='__main__': unittest.main()
