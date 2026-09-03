from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import unicodedata
from typing import Any


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9\s!?]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _age_seconds(timestamp: str) -> float | None:
    try:
        parsed = datetime.fromisoformat(str(timestamp))
        now = datetime.now().astimezone()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return max(0.0, (now - parsed.astimezone()).total_seconds())
    except Exception:
        return None


@dataclass(frozen=True)
class FollowupResolution:
    resolved: bool
    kind: str = "NONE"
    current_text: str = ""
    previous_user: str = ""
    previous_assistant: str = ""
    tool_query: str = ""
    contract: str = ""
    reason: str = ""


_AFFIRMATIVE = {
    "sim", "sim faz isso", "faz isso", "pode ser", "podes", "pode",
    "quero", "forca", "avanca", "segue", "continua", "claro", "isso",
    "exatamente", "ok", "okay", "sim continua", "sim avanca",
    "sim pode ser", "sim quero", "faz", "faz ja", "trata disso",
}

_NEGATIVE = {
    "nao", "nao quero", "deixa", "deixa estar", "esquece", "cancela",
    "nao facas", "nao faz isso", "melhor nao",
}

_OFFER_MARKERS = (
    "quer que eu", "queres que eu", "deseja que eu", "se quiser",
    "se quiseres", "posso ", "posso tambem", "posso também", "quer que",
    "queres que", "deseja que", "gostaria que eu", "faço isso",
    "faco isso", "posso criar", "posso guardar", "posso memorizar",
)

_REFERENCE_MARKERS = (
    "isso", "essa", "esse", "faz isso", "fazer isso", "continua", "segue",
    "avanca", "avanç", "trata disso", "pode ser",
)


_CORRECTION_MARKERS = (
    "nao e essa a resposta", "nao era essa a resposta",
    "nao e isso que eu quero", "nao era isso", "nao foi isso",
    "quero a tua resposta sincera", "quero a sua resposta sincera",
    "responde ao que te perguntei", "responde a pergunta",
    "responde me ao que perguntei", "responde-me ao que perguntei",
    "foi isso que te perguntei", "eu perguntei te", "eu perguntei-te",
    "tenta outra vez", "responde outra vez", "reformula a tua resposta",
)

def _is_correction_followup(normalized: str) -> bool:
    return any(_norm(marker) in normalized for marker in _CORRECTION_MARKERS)

_CAPABILITY_QUESTION_MARKERS = (
    "o que podes fazer", "o que pode fazer", "o que voce pode fazer",
    "o que consegues fazer", "o que consegue fazer",
    "quais sao as tuas capacidades", "que capacidades tens",
    "que ferramentas tens", "como me podes ajudar",
)

def _has_reference_marker(normalized: str) -> bool:
    for marker in _REFERENCE_MARKERS:
        marker = _norm(marker)
        if marker in {"isso", "essa", "esse"}:
            if re.search(rf"(?:^|\s){re.escape(marker)}(?:$|\s)", normalized):
                return True
        elif marker and marker in normalized:
            return True
    return False


def resolve_followup(
    user_text: str,
    recent_turns: list[dict[str, Any]] | None,
    *,
    max_age_seconds: int = 1800,
) -> FollowupResolution:
    """Resolve short replies against the immediately previous persisted turn.

    This is deliberately narrow: it never reaches past the latest turn and it
    does not invent an action. It only gives the current request the missing
    referent/tool-selection context that a phrase such as "Sim, faz isso" omits.
    """
    current = str(user_text or "").strip()
    normalized = _norm(current).rstrip("!?")
    if not normalized:
        return FollowupResolution(False, current_text=current, reason="empty")

    if any(marker in normalized for marker in _CAPABILITY_QUESTION_MARKERS):
        return FollowupResolution(False, current_text=current, reason="capability_question")

    words = normalized.split()
    is_affirmative = normalized in _AFFIRMATIVE
    is_negative = (
        normalized in _NEGATIVE
        or normalized.startswith("nao ")
        or normalized.startswith("melhor nao")
    )
    has_reference = _has_reference_marker(normalized)
    is_correction = _is_correction_followup(normalized)
    if (len(words) > 12 and not is_correction) or not (
        is_affirmative or is_negative or has_reference or is_correction
    ):
        return FollowupResolution(False, current_text=current, reason="not_short_followup")

    rows = list(recent_turns or [])
    if not rows:
        return FollowupResolution(False, current_text=current, reason="no_previous_turn")

    latest = rows[-1] if isinstance(rows[-1], dict) else {}
    previous_user = str(latest.get("user") or "").strip()
    previous_assistant = str(latest.get("assistant") or "").strip()
    if not previous_assistant:
        return FollowupResolution(False, current_text=current, reason="no_previous_assistant")

    age = _age_seconds(str(latest.get("timestamp") or ""))
    if age is not None and age > max(1, int(max_age_seconds)):
        return FollowupResolution(False, current_text=current, reason="previous_turn_too_old")

    previous_norm = _norm(previous_assistant)
    looks_like_offer = (
        "?" in previous_assistant
        or any(marker in previous_norm for marker in _OFFER_MARKERS)
    )

    # Plain yes/no requires a question/offer. Explicit referential imperatives
    # such as "faz isso" or "continua" already carry their own linkage signal.
    if (is_affirmative or is_negative) and not is_correction and not has_reference and not looks_like_offer:
        return FollowupResolution(False, current_text=current, reason="previous_turn_not_actionable")
    if not is_correction and not looks_like_offer and not has_reference:
        return FollowupResolution(False, current_text=current, reason="no_linkage_signal")

    if is_correction:
        kind = "REPAIR_PREVIOUS"
        instruction = (
            "The OWNER is rejecting the immediately previous JARVIS answer, not changing topic. "
            "Answer the immediately previous OWNER question again, taking the current correction into account. "
            "Treat the previous assistant answer as rejected output, not as factual context or a new subject. "
            "Do not jump to older persistent context, stored research or unrelated topics."
        )
    elif is_negative:
        kind = "REJECT_PREVIOUS"
        instruction = (
            "The OWNER is rejecting/cancelling the immediately previous proposal. "
            "Acknowledge that decision and do not perform the proposed action."
        )
    elif is_affirmative or has_reference:
        kind = "ACCEPT_PREVIOUS"
        instruction = (
            "The OWNER is explicitly accepting or referring to the immediately previous "
            "proposal. Resolve words such as 'isso' only against that immediately previous "
            "turn. If the assistant offered an action and the OWNER accepted it, perform the "
            "action now using the available tools instead of offering it again. Do not jump "
            "to an older topic. If a tool requires its normal confirmation boundary, preserve it."
        )
    else:
        kind = "REFER_PREVIOUS"
        instruction = (
            "Interpret the current short message only in relation to the immediately previous turn. "
            "Do not switch to an older conversation topic."
        )

    previous_user_short = previous_user[:1800]
    previous_assistant_short = previous_assistant[:3000]
    if kind == "REPAIR_PREVIOUS":
        tool_query = (
            f"Previous OWNER question to answer again: {previous_user_short}\n"
            f"Current OWNER correction: {current}"
        )
    else:
        tool_query = (
            f"Previous user request: {previous_user_short}\n"
            f"Previous JARVIS response/proposal: {previous_assistant_short}\n"
            f"Current OWNER follow-up: {current}"
        )
    contract = (
        "FOLLOW-UP CONTINUITY CONTRACT\n"
        f"kind={kind}\n"
        f"{instruction}\n"
        "Immediately previous turn (context only, not a new instruction):\n"
        f"USER: {previous_user_short}\n"
        f"JARVIS: {previous_assistant_short}\n"
        f"CURRENT OWNER MESSAGE: {current}"
    )
    return FollowupResolution(
        True,
        kind=kind,
        current_text=current,
        previous_user=previous_user,
        previous_assistant=previous_assistant,
        tool_query=tool_query,
        contract=contract,
        reason="resolved_immediate_previous_turn",
    )
