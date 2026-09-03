import tempfile, unittest
from pathlib import Path
from jarvis_core.services.agenda import AgendaStore
class AgendaTests(unittest.TestCase):
    def test_add_list_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=AgendaStore(Path(tmp)/'agenda.json'); a=s.add('Entrevista','2030-01-02 10:30','event'); self.assertTrue(a['ok']); item=a['item']['id']; self.assertEqual(len(s.list_items('all')['items']),1); self.assertTrue(s.complete(item)['ok']); self.assertEqual(len(s.list_items('all')['items']),0)
if __name__=='__main__': unittest.main()
