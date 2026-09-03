import json
import unittest
from jarvis_core.core.fast_router import FastCommandRouter

class DummyEvents:
    def emit(self,*args,**kwargs): pass
class DummyTools:
    request_started_at=None
    def __init__(self): self.calls=[]
    def execute(self,name,arguments):
        self.calls.append((name,arguments))
        if name=='get_precise_location': return json.dumps({'ok':True,'source':'configured_coordinates','label':'Furadouro, Ovar','latitude':40.87306,'longitude':-8.67424})
        return json.dumps({'ok':False})
class DummyApps:
    def list_apps(self): return []
class LocationRoutingTests(unittest.TestCase):
    def make(self): self.tools=DummyTools(); return FastCommandRouter(DummyEvents(),self.tools,DummyApps())
    def test_onde_estou_precise_tool(self):
        r=self.make().dispatch('Onde estou?'); self.assertTrue(r.handled); self.assertEqual(r.tool,'get_precise_location'); self.assertIn('Furadouro',r.response); self.assertIn('não estou a usar geolocalização por ip',r.response.lower())
    def test_localizacao_atual(self):
        r=self.make().dispatch('Jarvis, qual é a minha localização atual?'); self.assertTrue(r.handled); self.assertEqual(r.route,'location')
if __name__=='__main__': unittest.main()
