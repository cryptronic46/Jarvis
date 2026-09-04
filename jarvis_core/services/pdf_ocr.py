from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Iterable


_ENGINE = None
_ENGINE_LOCK = RLock()


def _ocr_engine():
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR

            _ENGINE = RapidOCR()
        return _ENGINE


def extract_pdf_pages_ocr(
    path: str | Path,
    page_numbers: Iterable[int],
    *,
    max_chars: int = 50000,
    scale: float = 2.0,
) -> dict[str, Any]:
    """Extract image-only PDF pages locally with ONNX OCR.

    Page numbers are zero-based. No document content leaves the machine.
    """
    try:
        import numpy as np
        import pypdfium2 as pdfium
    except ImportError as exc:
        return {
            "ok": False,
            "error": "PDF_OCR_NOT_INSTALLED",
            "message": f"Executa setup.ps1 para instalar o OCR local ({exc}).",
            "pages": [],
        }

    cap = max(1000, min(int(max_chars), 250000))
    extracted: list[tuple[int, str]] = []
    total = 0
    try:
        document = pdfium.PdfDocument(str(Path(path)))
        try:
            engine = _ocr_engine()
            for page_index in page_numbers:
                index = int(page_index)
                if index < 0 or index >= len(document) or total >= cap:
                    continue
                page = document[index]
                bitmap = None
                image = None
                try:
                    bitmap = page.render(scale=max(1.0, min(float(scale), 3.0)))
                    image = bitmap.to_pil()
                    with _ENGINE_LOCK:
                        result, _ = engine(np.asarray(image))
                    lines = [
                        str(item[1]).strip()
                        for item in (result or [])
                        if len(item) >= 3 and str(item[1]).strip() and float(item[2]) >= 0.35
                    ]
                    text = "\n".join(lines).strip()
                    if text:
                        remaining = cap - total
                        text = text[:remaining]
                        extracted.append((index + 1, text))
                        total += len(text)
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        finally:
            document.close()
        return {
            "ok": True,
            "pages": extracted,
            "text_chars": total,
            "engine": "rapidocr_onnxruntime",
            "local_only": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "pages": extracted,
        }
