from __future__ import annotations

import re

from jarvis_core.services.language_refinement import refine_assistant_text

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_BOLD = re.compile(r"(\*\*|__)(.*?)\1")
_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{2,}")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _normalize_for_speech(text: str) -> str:
    if not text:
        return ""

    # Apply the same final pt-PT refinement used by written replies so text
    # and speech never diverge in grammar/localisation.
    text = refine_assistant_text(text)
    value = _CODE_BLOCK.sub(" ", text)
    value = _MARKDOWN_LINK.sub(r"\1", value)
    value = _URL.sub(" ", value)
    value = _BOLD.sub(r"\2", value)
    value = _INLINE_CODE.sub(r"\1", value)
    value = _BULLET.sub("", value)
    value = _NUMBERED.sub("", value)

    replacements = {
        "°C": " graus Celsius",
        "GB": " gigabytes",
        "MB": " megabytes",
        "GHz": " gigahertz",
        "MHz": " megahertz",
        "RTX 5070": "R T X 5070",
        "%": " por cento",
        "VRAM": "V RAM",
        "CPU": "C P U",
        "GPU": "G P U",
        "RAM": "RAM",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    value = value.replace("#", " ")
    value = value.replace("|", ", ")
    value = value.replace("\\", " ")
    value = value.replace("/", " ")

    value = _MULTI_SPACE.sub(" ", value)
    value = _MULTI_NEWLINE.sub(". ", value)
    return value.strip(" \n\t.-")


def _split_long_piece(piece: str, max_chars: int) -> list[str]:
    result: list[str] = []
    remaining = piece.strip()
    while len(remaining) > max_chars:
        window = remaining[: max_chars + 1]
        cut = max(
            window.rfind(". "),
            window.rfind("? "),
            window.rfind("! "),
            window.rfind("; "),
            window.rfind(", "),
            window.rfind(" "),
        )
        if cut < int(max_chars * 0.45):
            cut = max_chars
        else:
            cut += 1
        chunk = remaining[:cut].strip()
        if chunk:
            result.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        result.append(remaining)
    return result


def prepare_for_speech_chunks(text: str, max_chars: int = 1600) -> list[str]:
    """Normalize a response and split it into complete TTS queue segments.

    max_chars is a per-segment limit, not a total-response truncation limit.
    """
    value = _normalize_for_speech(text)
    if not value:
        return []

    limit = max(120, int(max_chars or 1600))
    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(value) if part.strip()]
    chunks: list[str] = []
    current = ""

    for sentence in sentences or [value]:
        pieces = _split_long_piece(sentence, limit)
        for piece in pieces:
            candidate = f"{current} {piece}".strip() if current else piece
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = piece

    if current:
        chunks.append(current)

    return chunks


def prepare_for_speech(text: str, max_chars: int = 1600) -> str:
    """Backward-compatible single-segment helper.

    SpeechService uses prepare_for_speech_chunks so long responses are spoken
    completely. Callers that explicitly need one segment retain the old cap.
    """
    chunks = prepare_for_speech_chunks(text, max_chars=max_chars)
    return chunks[0] if chunks else ""
