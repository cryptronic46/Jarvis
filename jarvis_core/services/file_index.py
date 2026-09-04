from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any
import json
import os
import unicodedata

from jarvis_core.services.pdf_ocr import extract_pdf_pages_ocr


ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".csv", ".json", ".log",
    ".docx", ".xlsx", ".pptx", ".py",
}


def _search_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class LocalFileIndex:
    def __init__(
        self,
        path: str | Path = "memory/file_index.json",
        *,
        extra_roots: list[str | Path] | tuple[str | Path, ...] = (),
    ):
        self.path = Path(path)
        self.extra_roots = tuple(Path(root) for root in extra_roots)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def roots(self) -> list[Path]:
        home = Path.home()
        candidates = [home / "Desktop", home / "Documents", home / "Downloads"]
        one_drive = os.environ.get("OneDrive")
        if one_drive:
            candidates.append(Path(one_drive))
        candidates.extend(self.extra_roots)
        result = []
        seen = set()
        for root in candidates:
            try:
                resolved = root.resolve()
            except Exception:
                resolved = root
            key = str(resolved).lower()
            if root.exists() and key not in seen:
                seen.add(key)
                result.append(root)
        return result

    def _allowed_path(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except Exception:
            return False
        for root in self.roots():
            try:
                resolved.relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    def build(self, max_files: int = 20000) -> dict[str, Any]:
        rows = []
        skipped = 0
        for root in self.roots():
            try:
                iterator = root.rglob("*")
            except Exception:
                continue
            for path in iterator:
                if len(rows) >= max_files:
                    break
                try:
                    if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                        continue
                    stat = path.stat()
                    rows.append({
                        "name": path.name,
                        "path": str(path),
                        "extension": path.suffix.lower(),
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                    })
                except (PermissionError, OSError):
                    skipped += 1
        data = {
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "roots": [str(x) for x in self.roots()],
            "files": rows,
            "skipped": skipped,
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "indexed": len(rows), "skipped": skipped, "roots": data["roots"]}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.build()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"files": []}
        except Exception:
            return {"files": []}

    def search(self, query: str, limit: int = 20) -> dict[str, Any]:
        query = str(query).strip()
        if not query:
            return {"ok": False, "error": "EMPTY_QUERY"}
        tokens = [x for x in _search_key(query).split() if x]
        indexed_rows = list(self._load().get("files", []))
        known_paths = {str(row.get("path") or "").casefold() for row in indexed_rows}
        # The private JARVIS library is intentionally checked live. It is small
        # and owner-managed, so newly copied PDFs become searchable immediately
        # without rebuilding the much larger Desktop/Documents index.
        for root in self.extra_roots:
            if not root.exists():
                continue
            try:
                candidates = root.rglob("*")
            except Exception:
                continue
            for path in candidates:
                try:
                    if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
                        continue
                    key = str(path).casefold()
                    if key in known_paths:
                        continue
                    stat = path.stat()
                    indexed_rows.append({
                        "name": path.name,
                        "path": str(path),
                        "extension": path.suffix.lower(),
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
                    })
                    known_paths.add(key)
                except (PermissionError, OSError):
                    continue
        scored = []
        for row in indexed_rows:
            hay = _search_key(str(row.get("name") or "") + " " + str(row.get("path") or ""))
            score = sum(1 for token in tokens if token in hay)
            minimum_score = 1 if len(tokens) == 1 else max(2, (len(tokens) * 7 + 9) // 10)
            if score >= minimum_score:
                scored.append((score, row))
        scored.sort(key=lambda item: (item[0], item[1].get("modified") or ""), reverse=True)
        return {
            "ok": True,
            "query": query,
            "results": [row for _, row in scored[:max(1, min(int(limit), 50))]],
        }

    def recent(self, limit: int = 20) -> dict[str, Any]:
        rows = list(self._load().get("files", []))
        rows.sort(key=lambda row: row.get("modified") or "", reverse=True)
        return {"ok": True, "results": rows[:max(1, min(int(limit), 50))]}

    def read_document(self, path: str, max_chars: int = 20000) -> dict[str, Any]:
        target = Path(path)
        if not self._allowed_path(target):
            return {
                "ok": False,
                "error": "PATH_NOT_ALLOWED",
                "message": "Só posso ler ficheiros em Desktop, Documents, Downloads ou OneDrive.",
            }
        if not target.exists() or not target.is_file():
            return {"ok": False, "error": "FILE_NOT_FOUND"}

        ext = target.suffix.lower()
        if ext not in {".txt", ".md", ".csv", ".json", ".log", ".py", ".pdf"}:
            return {"ok": False, "error": "CONTENT_EXTRACTION_NOT_SUPPORTED", "extension": ext}

        try:
            if ext == ".pdf":
                try:
                    from pypdf import PdfReader
                except Exception:
                    return {"ok": False, "error": "PYPDF_NOT_INSTALLED", "message": "Executa setup.ps1."}
                chunks = []
                total = 0
                reader = PdfReader(str(target))
                missing_pages = []
                for page_index, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    chunks.append(text)
                    total += len(text)
                    if not text.strip():
                        missing_pages.append(page_index)
                    if total >= max_chars:
                        break
                content = "\n".join(chunks)
                extraction = "text"
                if len(content.strip()) < 50 and missing_pages:
                    ocr = extract_pdf_pages_ocr(target, missing_pages, max_chars=max_chars)
                    if not ocr.get("ok"):
                        return {
                            "ok": False,
                            "error": ocr.get("error") or "PDF_OCR_FAILED",
                            "message": ocr.get("message") or "Não consegui executar OCR local neste PDF.",
                        }
                    content = "\n\n".join(text for _, text in ocr.get("pages") or [])
                    extraction = "ocr"
                    if not content.strip():
                        return {
                            "ok": False,
                            "error": "PDF_TEXT_NOT_EXTRACTABLE",
                            "message": "O PDF não contém texto extraível e o OCR local não reconheceu conteúdo.",
                        }
            else:
                content = target.read_text(encoding="utf-8", errors="replace")
                extraction = "text"
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

        cap = max(1000, min(int(max_chars), 50000))
        return {
            "ok": True,
            "path": str(target),
            "name": target.name,
            "text": content[:cap],
            "truncated": len(content) > cap,
            "local_only": True,
            "extraction": extraction,
        }


_INDEX: LocalFileIndex | None = None


def configure_file_index(
    path: str | Path = "memory/file_index.json",
    *,
    extra_roots: list[str | Path] | tuple[str | Path, ...] = (),
) -> LocalFileIndex:
    global _INDEX
    _INDEX = LocalFileIndex(path, extra_roots=extra_roots)
    return _INDEX


def file_index() -> LocalFileIndex:
    global _INDEX
    if _INDEX is None:
        _INDEX = LocalFileIndex()
    return _INDEX


def build_local_file_index() -> dict[str, Any]:
    return file_index().build()


def search_local_files(query: str, limit: int = 20) -> dict[str, Any]:
    return file_index().search(query, limit)


def list_recent_local_files(limit: int = 20) -> dict[str, Any]:
    return file_index().recent(limit)


def read_local_document(path: str, max_chars: int = 20000) -> dict[str, Any]:
    return file_index().read_document(path, max_chars)
