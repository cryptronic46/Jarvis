import unittest
from unittest.mock import patch
from jarvis_core.tools.environment_tools import _sea_state,_weather_description,get_home_environment

class FakeMemory:
    def profile(self):
        return {'home':{'label':'Furadouro, Ovar','latitude':40.87306,'longitude':-8.67424,'marine_latitude':40.87057,'marine_longitude':-8.67875}}

class EnvironmentToolsTests(unittest.TestCase):
    def test_mappings(self):
        self.assertIn('sol',_weather_description(0)); self.assertEqual(_weather_description(3),'encoberto'); self.assertEqual(_weather_description(63),'chuva')
        self.assertEqual(_sea_state(0.3,5),'calmo'); self.assertEqual(_sea_state(1.4,8),'agitado'); self.assertIn('bravo',_sea_state(2.4,9))

    @patch('jarvis_core.tools.environment_tools._read_cache',return_value=None)
    @patch('jarvis_core.tools.environment_tools.store',return_value=FakeMemory())
    @patch('jarvis_core.tools.environment_tools._fetch_json')
    def test_combines_weather_marine(self,fetch,memory,cache):
        fetch.side_effect=[{'current':{'weather_code':3,'temperature_2m':21.0,'relative_humidity_2m':73,'cloud_cover':85,'rain':0.0,'time':'x'}},{'current':{'wave_height':1.6,'wave_period':9.0,'swell_wave_height':1.4,'swell_wave_period':10.0,'time':'x'}}]
        with patch('jarvis_core.tools.environment_tools._write_cache'):
            r=get_home_environment(force_refresh=True)
        self.assertTrue(r['ok']); self.assertEqual(r['weather']['relative_humidity_percent'],73); self.assertEqual(r['marine']['state'],'agitado')

if __name__=='__main__': unittest.main()
