from __future__ import annotations

from typing import Any
import ctypes
import locale
import os


def _windows_code_page(kind: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        value = int(kernel32.GetOEMCP() if kind == "oem" else kernel32.GetACP())
        return f"cp{value}" if value > 0 else None
    except Exception:
        return None


def subprocess_decode_candidates() -> tuple[str, ...]:
    """Return safe decoding candidates for captured child-process bytes.

    Python UTF-8 mode changes the implicit decoder used by text=True, while
    classic Windows programs (notably Windows PowerShell 5.1) can still emit
    the active OEM/ANSI code page. Capturing bytes first avoids exceptions in
    subprocess._readerthread; decoding then happens deterministically here.
    """
    candidates: list[str] = ["utf-8-sig", "utf-8"]
    if os.name == "nt":
        for enc in (_windows_code_page("oem"), _windows_code_page("ansi"), "mbcs"):
            if enc and enc.lower() not in {item.lower() for item in candidates}:
                candidates.append(enc)
    preferred = locale.getpreferredencoding(False) or ""
    if preferred and preferred.lower() not in {item.lower() for item in candidates}:
        candidates.append(preferred)
    for enc in ("cp850", "cp1252", "latin-1"):
        if enc.lower() not in {item.lower() for item in candidates}:
            candidates.append(enc)
    return tuple(candidates)


def decode_subprocess_stream(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return str(value)
    raw = bytes(value)
    if not raw:
        return ""
    for encoding in subprocess_decode_candidates():
        try:
            return raw.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")
