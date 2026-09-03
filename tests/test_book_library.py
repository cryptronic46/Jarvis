import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.book_library import BookLibrary


def _write_text_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{number} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")
    xref = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(body)


class BookLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.books = root / "books"
        self.database = root / "knowledge" / "library.sqlite3"
        self.library = BookLibrary(self.books, self.database)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_real_pdf_is_indexed_searched_and_cited_by_page(self):
        pdf = self.books / "Energia Solar.pdf"
        _write_text_pdf(
            pdf,
            "A fotossintese converte energia luminosa em energia quimica.",
        )

        result = self.library.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["indexed"], 1)

        search = self.library.search("energia luminosa")
        self.assertTrue(search["ok"])
        self.assertEqual(search["count"], 1)
        self.assertEqual(search["results"][0]["page"], 1)
        self.assertIn("Energia Solar", search["results"][0]["citation"])
        self.assertIn("energia luminosa", search["results"][0]["excerpt"])
        self.assertIn("untrusted reference", search["notice"])

    def test_sync_skips_unchanged_and_reindexes_changed_pdf(self):
        pdf = self.books / "Manual.pdf"
        _write_text_pdf(pdf, "Primeira versao sobre redes locais.")
        self.assertEqual(self.library.sync()["indexed"], 1)
        self.assertEqual(self.library.sync()["unchanged"], 1)

        _write_text_pdf(pdf, "Segunda versao sobre segmentacao defensiva.")
        result = self.library.sync()
        self.assertEqual(result["indexed"], 1)
        self.assertEqual(
            self.library.search("segmentacao defensiva")["count"],
            1,
        )
        self.assertEqual(self.library.search("redes locais")["count"], 0)

    def test_removed_pdf_is_removed_from_index(self):
        pdf = self.books / "Temporario.pdf"
        _write_text_pdf(pdf, "Conteudo temporario para remocao segura.")
        self.library.sync()
        pdf.unlink()

        result = self.library.sync()
        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["stats"]["books"], 0)
        self.assertEqual(self.library.search("temporario")["count"], 0)

    def test_image_only_pdf_is_reported_as_needing_ocr(self):
        from pypdf import PdfWriter

        pdf = self.books / "Digitalizacao.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf.open("wb") as handle:
            writer.write(handle)

        result = self.library.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["needs_ocr"], 1)
        self.assertEqual(result["stats"]["needs_ocr"], 1)
        self.assertEqual(result["stats"]["indexed"], 0)

    def test_empty_query_is_rejected(self):
        result = self.library.search("   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "EMPTY_QUERY")


if __name__ == "__main__":
    unittest.main()
