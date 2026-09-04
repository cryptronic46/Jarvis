import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from jarvis_core.services.file_index import LocalFileIndex
class FileIndexSecurityTests(unittest.TestCase):
    def test_extra_library_root_is_searched_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            library = base / "library" / "books"
            library.mkdir(parents=True)
            index_path = base / "index.json"
            index_path.write_text('{"files":[]}', encoding="utf-8")
            idx = LocalFileIndex(index_path, extra_roots=[library])
            pdf = library / "Python Essencial.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            result = idx.search("python")
            self.assertTrue(result["ok"])
            self.assertEqual(result["results"][0]["path"], str(pdf))
            self.assertTrue(idx._allowed_path(pdf))

    def test_search_is_accent_insensitive_and_rejects_partial_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            library = base / "library" / "books"
            library.mkdir(parents=True)
            index_path = base / "index.json"
            index_path.write_text('{"files":[]}', encoding="utf-8")
            exact = library / "Acordo Ortográfico Português.pdf"
            noise = library / "Acordo de Representação.pdf"
            exact.write_bytes(b"%PDF-1.4")
            noise.write_bytes(b"%PDF-1.4")
            idx = LocalFileIndex(index_path, extra_roots=[library])

            result = idx.search("acordo ortografico")
            self.assertEqual([row["path"] for row in result["results"]], [str(exact)])

    def test_read_rejects_outside_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx=LocalFileIndex(Path(tmp)/'index.json')
            with patch.object(idx,'roots',return_value=[Path(tmp)/'safe']): result=idx.read_document(str(Path(tmp)/'outside.txt'))
            self.assertFalse(result['ok']); self.assertEqual(result['error'],'PATH_NOT_ALLOWED')
    def test_search_uses_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'index.json'; p.write_text('{"files":[{"name":"contrato.pdf","path":"C:/Docs/contrato.pdf","modified":"2030-01-01"}]}',encoding='utf-8'); idx=LocalFileIndex(p); self.assertEqual(idx.search('contrato')['results'][0]['name'],'contrato.pdf')
if __name__=='__main__': unittest.main()
