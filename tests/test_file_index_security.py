import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.services.file_index import LocalFileIndex
class FileIndexSecurityTests(unittest.TestCase):
    def test_read_rejects_outside_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx=LocalFileIndex(Path(tmp)/'index.json')
            with patch.object(idx,'roots',return_value=[Path(tmp)/'safe']): result=idx.read_document(str(Path(tmp)/'outside.txt'))
            self.assertFalse(result['ok']); self.assertEqual(result['error'],'PATH_NOT_ALLOWED')
    def test_search_uses_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'index.json'; p.write_text('{"files":[{"name":"contrato.pdf","path":"C:/Docs/contrato.pdf","modified":"2030-01-01"}]}',encoding='utf-8'); idx=LocalFileIndex(p); self.assertEqual(idx.search('contrato')['results'][0]['name'],'contrato.pdf')
if __name__=='__main__': unittest.main()
