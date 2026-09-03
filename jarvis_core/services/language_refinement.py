from __future__ import annotations

"""Final response refinement for JARVIS.

This module is deliberately deterministic and local.  It does not call an LLM,
Web service or external AI.  The local model remains responsible for meaning and
persona; this layer only performs conservative pt-PT and presentation repairs
before a response is shown or spoken.
"""

import json
import re
from typing import Callable

_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_TOOL_CALL_RE = re.compile(r"<tool_call>.*?</tool_call>", re.IGNORECASE | re.DOTALL)


# Conservative replacements observed during real-machine acceptance.  Keep this
# list narrow: semantic rewriting belongs to the local brain, not to this guard.
_PTPT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\balgo else\b", "mais alguma coisa"),
    (r"\bsistema operacional\b", "sistema operativo"),
    (r"\busuários\b", "utilizadores"),
    (r"\busuário\b", "utilizador"),
    (r"\bregistros\b", "registos"),
    (r"\bregistro\b", "registo"),
    (r"\baprendizados\b", "aprendizagens"),
    (r"\baprendizado\b", "aprendizagem"),
    (r"\ba tela\b", "o ecrã"),
    (r"\btela\b", "ecrã"),
    (r"\brevisar\b", "rever"),
    (r"\bbuscar\b", "procurar"),
    (r"\bcompartilhar\b", "partilhar"),
    (r"\bdiretrizes\b", "orientações"),
    (r"\baplicativos\b", "aplicações"),
    (r"\baplicativo\b", "aplicação"),
    (r"\bcelular\b", "telemóvel"),
    (r"\bsenha\b", "palavra-passe"),
    (r"\bdeletar\b", "eliminar"),
    (r"\bsalvar\b", "guardar"),
    (r"\bcom você\b", "consigo"),
    (r"\bpara você\b", "para si"),
    (r"\bvocê\b", "o Senhor"),
    (r"\bminha função\b", "a minha função"),
    (r"\bminha capacidade\b", "a minha capacidade"),
    (r"\bpor sua sintaxe\b", "pela sua sintaxe"),
    (r"\bpressionar teclas\b", "premir teclas"),
)

# Portuguese contractions.  These are grammatical transformations, not style
# guesses, and fix outputs such as "focada em a nossa conversa" -> "focada na
# nossa conversa".
_CONTRACTIONS: tuple[tuple[str, str], ...] = (
    (r"\bem\s+a\b", "na"),
    (r"\bem\s+o\b", "no"),
    (r"\bem\s+as\b", "nas"),
    (r"\bem\s+os\b", "nos"),
    (r"\bde\s+a\b", "da"),
    (r"\bde\s+o\b", "do"),
    (r"\bde\s+as\b", "das"),
    (r"\bde\s+os\b", "dos"),
    (r"\bpor\s+a\b", "pela"),
    (r"\bpor\s+o\b", "pelo"),
    (r"\bpor\s+as\b", "pelas"),
    (r"\bpor\s+os\b", "pelos"),
)

# Grammar around the most common pt-BR verb that escaped the local model.
_GRAMMAR_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bpreciso compartilhar\b", "preciso de partilhar"),
    (r"\bprecisa compartilhar\b", "precisa de partilhar"),
    (r"\bprecisar compartilhar\b", "precisar de partilhar"),
    (r"\bposso compartilhar\b", "posso partilhar"),
    (r"\bpode compartilhar\b", "pode partilhar"),
)


def _looks_machine_readable(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if "<tool_call>" in stripped.lower():
        return True
    if stripped[0] not in "[{":
        return False
    try:
        parsed = json.loads(stripped)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _case_aware_replacement(replacement: str) -> Callable[[re.Match[str]], str]:
    def repl(match: re.Match[str]) -> str:
        value = replacement
        original = match.group(0)
        if original and original[0].isupper() and value:
            value = value[0].upper() + value[1:]
        return value
    return repl


def _protect_code(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def stash(match: re.Match[str]) -> str:
        token = f"\x00JARVIS_PROTECTED_{len(protected)}\x00"
        protected[token] = match.group(0)
        return token

    value = _CODE_BLOCK_RE.sub(stash, text)
    value = _INLINE_CODE_RE.sub(stash, value)
    value = _TOOL_CALL_RE.sub(stash, value)
    return value, protected


def _restore_code(text: str, protected: dict[str, str]) -> str:
    value = text
    for token, original in protected.items():
        value = value.replace(token, original)
    return value


def _dedupe_immediate_sentences(text: str) -> str:
    # Small local models can occasionally repeat one complete sentence twice.
    # Keep paragraph boundaries; only remove adjacent exact repetitions.
    sentence_re = re.compile(r"(?s)([^.!?\n]{8,}[.!?])(?:\s+\1)+")
    previous = None
    value = text
    while previous != value:
        previous = value
        value = sentence_re.sub(r"\1", value)
    return value


def refine_assistant_text(text: str, *, user_text: str = "") -> str:
    """Refine final prose without changing factual/tool semantics.

    `user_text` is accepted for future owner-style policies and keeps the API
    compatible with the final response sanitizer.  No user data leaves the PC.
    """
    value = str(text or "")
    if not value or _looks_machine_readable(value):
        return value

    value, protected = _protect_code(value)

    for pattern, replacement in _PTPT_REPLACEMENTS:
        value = re.sub(
            pattern,
            _case_aware_replacement(replacement),
            value,
            flags=re.IGNORECASE,
        )

    for pattern, replacement in _GRAMMAR_REPLACEMENTS:
        value = re.sub(
            pattern,
            _case_aware_replacement(replacement),
            value,
            flags=re.IGNORECASE,
        )

    for pattern, replacement in _CONTRACTIONS:
        value = re.sub(
            pattern,
            _case_aware_replacement(replacement),
            value,
            flags=re.IGNORECASE,
        )

    value = _dedupe_immediate_sentences(value)
    value = re.sub(r"[ \t]+([,.;:!?])", r"\1", value)
    value = re.sub(r" {2,}", " ", value)
    value = _restore_code(value, protected)
    return value.strip()


def refinement_status() -> dict[str, object]:
    """Read-only status used by diagnostics/tests."""
    return {
        "ok": True,
        "enabled": True,
        "locale": "pt-PT",
        "mode": "deterministic_local_final_pass",
        "external_ai": False,
        "applies_to": ["written_response", "speech_input"],
    }
