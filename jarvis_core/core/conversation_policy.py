from __future__ import annotations

import re
import unicodedata


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def authorized_learning_requested(user_text: str) -> bool:
    """True only when stored web-learning is part of the current intent.

    Stored research is evidence, not ambient conversation memory. A weak lexical
    overlap must not drag an old research topic into ordinary dialogue.
    """
    value = _normalize(user_text)
    if not value:
        return False
    patterns = (
        r"\bo que aprendeste(?: sobre)?\b",
        r"\bo que pesquisaste(?: sobre)?\b",
        r"\bo que estudaste(?: sobre)?\b",
        r"\b(?:consulta|usa|mostra|resume) (?:a |as )?(?:pesquisa|pesquisas|aprendizagem|aprendizagens)(?: autorizada| autorizadas)?\b",
        r"\b(?:na|da|sobre a) pesquisa que (?:fizeste|fizemos|autorizei|autorizamos)\b",
        r"\b(?:fontes guardadas|resumo guardado|conhecimento (?:guardado|aprendido))\b",
        r"\baprendizagem autorizada\b",
        r"\bpesquisa autorizada\b",
    )
    return any(re.search(pattern, value) for pattern in patterns)
