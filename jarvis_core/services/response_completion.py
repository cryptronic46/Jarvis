from __future__ import annotations

from typing import Any
import re

_LENGTH_REASONS = {
    "length",
    "max_tokens",
    "max_output_tokens",
    "max_completion_tokens",
    "num_predict",
    "token_limit",
}

_NATURAL_END = re.compile(r"[.!?…][\s\]\)\}\"']*$")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def response_done_reason(response: Any) -> str:
    reason = _field(response, "done_reason", "")
    if not reason:
        reason = _field(response, "finish_reason", "")
    return str(reason or "").strip().lower()


def response_eval_count(response: Any) -> int | None:
    raw = _field(response, "eval_count", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def looks_sentence_complete(text: str) -> bool:
    value = str(text or "").rstrip()
    if not value:
        return False
    return bool(_NATURAL_END.search(value))


def response_was_truncated(
    response: Any,
    *,
    requested_predict: int,
    content: str,
) -> bool:
    """Best-effort local completion truncation detector.

    Local runtime responses may expose done_reason=length. Compatibility responses may only
    expose eval_count, so reaching the exact num_predict budget while ending
    mid-sentence is treated as a likely truncation.
    """
    reason = response_done_reason(response)
    if reason in _LENGTH_REASONS:
        return True
    if reason in {"stop", "eos", "end_turn"}:
        return False
    if reason:
        return False

    eval_count = response_eval_count(response)
    budget = max(1, int(requested_predict or 0))
    if eval_count is None or budget <= 0:
        return False

    near_limit = eval_count >= max(1, budget - 1)
    return bool(near_limit and not looks_sentence_complete(content))


_META_CONTINUATION_MARKERS = (
    "entendo. estou aqui",
    "vou continuar",
    "resposta foi interrompida",
    "onde parei",
    "onde ela foi interrompida",
    "se houver algo especifico",
    "se precisar de ajuda",
    "estou a disposicao",
    "estou à disposicao",
    "vamos prosseguir",
    "basta me dizer",
    "do ponto onde parou",
    "sem comentar este pedido",
    "pedido de continuação",
    "pedido de continuacao",
    "conclui a resposta naturalmente",
)

def _norm_simple(value: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))

def continuation_is_meta(text: str) -> bool:
    """Detect a model answering the hidden continuation instruction instead of continuing content."""
    normalized = _norm_simple(text)
    return any(_norm_simple(marker) in normalized for marker in _META_CONTINUATION_MARKERS)

def strip_internal_continuation(text: str) -> str:
    """Remove a leaked hidden continuation instruction and its partial lead-in."""
    value = str(text or "").strip()
    normalized = _norm_simple(value)
    positions = [
        normalized.find(_norm_simple(marker))
        for marker in (
            "CONTINUAÇÃO TÉCNICA",
            "do ponto onde parou, sem reiniciar",
            "sem comentar este pedido de continuação",
            "conclui a resposta naturalmente",
        )
    ]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return value
    prefix = value[:min(positions)].rstrip(" ,;:-")
    return trim_to_last_complete_sentence(prefix) or prefix

def trim_to_last_complete_sentence(text: str) -> str:
    """Return the longest natural-sentence prefix, useful when a retry still hits a hard token limit."""
    value = str(text or "").strip()
    if not value:
        return ""
    matches = list(re.finditer(r"[.!?…](?=\s|$)", value))
    if not matches:
        return value
    return value[:matches[-1].end()].rstrip()

def merge_continuation(base: str, continuation: str) -> str:
    """Join a continuation while removing a small repeated overlap."""
    left = str(base or "").rstrip()
    right = str(continuation or "").lstrip()
    if not left:
        return right
    if not right:
        return left

    max_overlap = min(240, len(left), len(right))
    overlap = 0
    left_lower = left.lower()
    right_lower = right.lower()
    for size in range(max_overlap, 7, -1):
        if left_lower[-size:] == right_lower[:size]:
            overlap = size
            break

    right = right[overlap:].lstrip()
    if not right:
        return left

    separator = "" if left.endswith((" ", "\n", "-", "/")) else " "
    return left + separator + right
