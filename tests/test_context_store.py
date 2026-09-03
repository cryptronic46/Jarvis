import tempfile, unittest
from pathlib import Path
from jarvis_core.services.context_store import ContextStore
class ContextStoreTests(unittest.TestCase):
    def test_persistent_recent_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=ContextStore(Path(tmp)/'c.jsonl'); s.record('Pergunta','Resposta','LOCAL'); self.assertEqual(s.recent(1)[0]['user'],'Pergunta'); self.assertIn('Pergunta',s.prompt_block(1))
if __name__=='__main__': unittest.main()
