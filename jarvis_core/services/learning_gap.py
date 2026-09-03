from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import math
import re
import unicodedata


_STOPWORDS = {
    "a", "ao", "aos", "as", "de", "da", "das", "do", "dos", "e", "em",
    "eu", "isto", "isso", "me", "meu", "minha", "na", "nas", "no", "nos",
    "o", "os", "para", "por", "que", "se", "sobre", "um", "uma", "uns", "umas",
    "como", "qual", "quais", "porque", "porquê", "podes", "pode", "consegues",
    "explica", "explicar", "diz", "dizer", "sabes", "sabe", "conheces", "conhece",
    "what", "how", "why", "the", "and", "for", "with", "from", "this", "that",
}

_GAP_MARKERS = (
    "nao sei",
    "não sei",
    "nao conheco",
    "não conheço",
    "desconheco",
    "desconheço",
    "nao tenho conhecimento suficiente",
    "não tenho conhecimento suficiente",
    "nao tenho informacao suficiente",
    "não tenho informação suficiente",
    "informacao insuficiente",
    "informação insuficiente",
    "dados insuficientes",
    "nao disponho de informacao",
    "não disponho de informação",
    "nao consigo determinar",
    "não consigo determinar",
    "nao consigo concluir",
    "não consigo concluir",
    "nao consigo responder com confianca",
    "não consigo responder com confiança",
    "nao estou suficientemente confiante",
    "não estou suficientemente confiante",
    "unable to determine",
    "insufficient information",
    "i don't know",
    "i do not know",
)

_POLICY_REFUSAL_MARKERS = (
    "nao posso ajudar com",
    "não posso ajudar com",
    "nao posso fornecer instrucoes",
    "não posso fornecer instruções",
    "nao e permitido",
    "não é permitido",
    "por motivos de seguranca",
    "por motivos de segurança",
    "nao posso auxiliar",
    "não posso auxiliar",
)

_DIRECT_EXTERNAL_MARKERS = (
    "pesquisa na internet",
    "pesquisa na web",
    "procura na internet",
    "procura na web",
    "consulta a internet",
    "consulta a web",
    "usa a internet",
    "usa a web",
    "/research",
    "/web",
    "/cloud",
    "/sol",
)

_OPERATIONAL_PREFIXES = (
    "abre ", "abrir ", "fecha ", "fechar ", "liga ", "desliga ", "executa ",
    "corre ", "apaga ", "elimina ", "move ", "copia ", "instala ", "desinstala ",
    "reinicia ", "bloqueia ", "desbloqueia ", "aumenta ", "baixa ", "define ",
)

_SECRET_HINTS = (
    "api key", "apikey", "password", "palavra-passe", "senha", "token=", "secret=",
    "private key", "chave privada", "recovery code", "codigo de recuperacao",
    "código de recuperação",
)


@dataclass(slots=True)
class LearningGapAssessment:
    needs_learning: bool
    topic: str
    reason: str
    local_confidence: float
    studied: bool = False
    stale: bool = False
    matched_topic: str | None = None
    match_score: float = 0.0


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _terms(value: str) -> set[str]:
    out: set[str] = set()
    for raw in re.findall(r"[a-z0-9_+#.-]+", _norm(value)):
        token = raw.strip("._-+#")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        out.add(token)
    return out


def extract_learning_topic(user_text: str) -> str:
    """Extract a bounded human-readable topic without pretending to understand more than the text says."""
    raw = re.sub(r"^\s*jarvis[\s,;:!?.-]*", "", str(user_text or ""), flags=re.IGNORECASE).strip()
    raw = re.sub(r"\s+", " ", raw)
    patterns = (
        r"(?i)^o que (?:e|é)\s+(.+?)[?!.]*$",
        r"(?i)^como funciona\s+(.+?)[?!.]*$",
        r"(?i)^explica(?:-me)?\s+(?:o que (?:e|é)\s+)?(.+?)[?!.]*$",
        r"(?i)^fala(?:-me)?\s+sobre\s+(.+?)[?!.]*$",
        r"(?i)^o que sabes sobre\s+(.+?)[?!.]*$",
        r"(?i)^conheces\s+(.+?)[?!.]*$",
        r"(?i)^sabes\s+(?:o que (?:e|é)\s+)?(.+?)[?!.]*$",
        r"(?i)^porque\s+(.+?)[?!.]*$",
        r"(?i)^por que\s+(.+?)[?!.]*$",
        r"(?i)^qual (?:e|é)\s+(.+?)[?!.]*$",
    )
    for pattern in patterns:
        match = re.match(pattern, raw)
        if match:
            topic = match.group(1).strip(" \t\r\n,;:!?\"'")
            if topic:
                return topic[:220]
    return raw.strip(" \t\r\n,;:!?\"'")[:220]


def contains_secret_hints(text: str) -> bool:
    normalized = _norm(text)
    if any(marker in normalized for marker in _SECRET_HINTS):
        return True
    # Common key/token shapes. This is intentionally conservative and only blocks
    # automatic external-AI offers; it does not inspect or retain the secret.
    if re.search(r"\bsk-[a-z0-9_-]{12,}\b", normalized):
        return True
    if re.search(r"\b(?:bearer\s+)?[a-z0-9_-]{32,}\b", normalized):
        return True
    return False


def is_learning_candidate(user_text: str, local_answer: str) -> tuple[bool, str, float]:
    query = str(user_text or "").strip()
    answer = str(local_answer or "").strip()
    normalized_query = _norm(query)
    normalized_answer = _norm(answer)

    if not query or query.startswith("/"):
        return False, "not_natural_language_query", 1.0
    if any(marker in normalized_query for marker in _DIRECT_EXTERNAL_MARKERS):
        return False, "external_research_already_requested", 1.0
    if any(normalized_query.startswith(prefix) for prefix in _OPERATIONAL_PREFIXES):
        return False, "operational_request", 1.0
    if any(marker in normalized_answer for marker in _POLICY_REFUSAL_MARKERS):
        return False, "policy_refusal_not_knowledge_gap", 1.0

    explicit_gap = any(marker in normalized_answer for marker in _GAP_MARKERS)
    empty = not answer
    if not (explicit_gap or empty):
        return False, "local_answer_substantive", 0.82

    topic = extract_learning_topic(query)
    topic_terms = _terms(topic)
    if not topic or len(topic_terms) == 0:
        return False, "topic_not_resolved", 0.35

    # The local model explicitly reported a gap. Keep the estimate conservative:
    # this is an orchestration signal, not a calibrated probability.
    return True, "explicit_local_knowledge_gap" if explicit_gap else "empty_local_answer", 0.22


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except Exception:
        return None


def assess_studied_coverage(store: Any, topic: str, *, stale_days: int = 120) -> dict[str, Any]:
    query_terms = _terms(topic)
    if not query_terms:
        return {"studied": False, "stale": False, "score": 0.0, "row": None}

    best_row = None
    best_score = 0.0
    best_overlap = 0
    try:
        rows = list(store.rows())
    except Exception:
        rows = []

    normalized_topic = _norm(topic)
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_topic = str(row.get("topic") or "")
        row_terms = _terms(row_topic)
        if not row_terms:
            continue
        overlap = len(query_terms.intersection(row_terms))
        phrase_match = bool(row_topic) and (
            _norm(row_topic) in normalized_topic or normalized_topic in _norm(row_topic)
        )
        denominator = max(1, min(len(query_terms), len(row_terms)))
        score = overlap / denominator
        if phrase_match:
            score = max(score, 0.95)
        if (score, overlap) > (best_score, best_overlap):
            best_score = score
            best_overlap = overlap
            best_row = row

    needed_overlap = 1 if len(query_terms) == 1 else min(2, len(query_terms))
    studied = bool(best_row) and best_overlap >= needed_overlap and best_score >= 0.60
    stale = False
    if studied and stale_days > 0:
        ts = _parse_timestamp(str(best_row.get("learned_at") or best_row.get("timestamp") or ""))
        if ts is not None:
            now = datetime.now().astimezone()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=now.tzinfo)
            stale = (now - ts).days >= int(stale_days)

    return {
        "studied": studied,
        "stale": stale,
        "score": round(best_score, 3),
        "row": best_row,
    }


def assess_learning_gap(
    user_text: str,
    local_answer: str,
    store: Any,
    *,
    stale_days: int = 120,
) -> LearningGapAssessment:
    candidate, reason, local_confidence = is_learning_candidate(user_text, local_answer)
    topic = extract_learning_topic(user_text)
    if not candidate:
        return LearningGapAssessment(False, topic, reason, local_confidence)

    coverage = assess_studied_coverage(store, topic, stale_days=stale_days)
    row = coverage.get("row") or {}
    studied = bool(coverage.get("studied"))
    stale = bool(coverage.get("stale"))
    if studied and not stale:
        return LearningGapAssessment(
            False,
            topic,
            "relevant_authorized_learning_already_present",
            local_confidence,
            studied=True,
            stale=False,
            matched_topic=str(row.get("topic") or "") or None,
            match_score=float(coverage.get("score") or 0.0),
        )

    return LearningGapAssessment(
        True,
        topic,
        "stored_learning_stale" if stale else reason,
        local_confidence,
        studied=studied,
        stale=stale,
        matched_topic=str(row.get("topic") or "") or None,
        match_score=float(coverage.get("score") or 0.0),
    )



def knowledge_state(store: Any, topic: str, *, stale_days: int = 120) -> dict[str, Any]:
    """Return an inspectable KNOWN/STALE/UNKNOWN state for a learned topic."""
    coverage = assess_studied_coverage(store, topic, stale_days=stale_days)
    row = coverage.get("row") or {}
    studied = bool(coverage.get("studied"))
    stale = bool(coverage.get("stale"))
    state = "UNKNOWN"
    if studied:
        state = "STALE" if stale else "KNOWN"
    return {
        "ok": True,
        "topic": str(topic or "")[:220],
        "state": state,
        "studied": studied,
        "stale": stale,
        "match_score": float(coverage.get("score") or 0.0),
        "matched_topic": str(row.get("topic") or "") or None,
        "learned_at": str(row.get("learned_at") or row.get("timestamp") or "") or None,
        "confidence": row.get("confidence"),
        "source_confidence": row.get("source_confidence", row.get("confidence")),
        "confidence_semantics": row.get("confidence_semantics", "source_diversity_score" if row.get("confidence") is not None else None),
        "claim_confidence": row.get("claim_confidence"),
        "source_count": row.get("source_count", len(row.get("sources") or []) if isinstance(row, dict) else 0),
        "source_type": str(row.get("source_type") or "") or None,
    }

def deterministic_confidence_from_sources(sources: list[dict[str, Any]] | None) -> float:
    unique_urls = {
        str(item.get("url") or "").strip()
        for item in (sources or [])
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    }
    count = len(unique_urls)
    if count >= 4:
        return 0.94
    if count == 3:
        return 0.90
    if count == 2:
        return 0.82
    if count == 1:
        return 0.70
    return 0.55


def freshness_days_for_topic(topic: str, default_days: int = 120) -> int:
    normalized = _norm(topic)
    fast_moving = (
        "preco", "preço", "cotacao", "cotação", "noticias", "notícias", "versao",
        "versão", "release", "emprego", "vaga", "mercado", "politica", "política",
        "seguranca", "segurança", "cve", "vulnerabilidade", "driver", "firmware",
    )
    return 14 if any(marker in normalized for marker in fast_moving) else max(1, int(default_days))


def minimum_overlap_for_terms(term_count: int) -> int:
    return max(1, min(term_count, int(math.ceil(term_count * 0.5))))
