from __future__ import annotations

import re
import unicodedata

from jarvis_core.services.request_intent import classify_request_intent
from jarvis_core.services.semantic_request import StructuredRequest


_GREETING_EXACT = frozenset({
    "ola",
    "bom dia",
    "boa tarde",
    "boa noite",
    "hey",
    "hello",
})

_SOCIAL_EXACT = frozenset({
    "provoca-me",
    "provoca me",
    "flirta comigo",
    "seduz-me",
    "seduz me",
    "fala comigo",
    "conversa comigo",
    "faz-me companhia",
    "faz me companhia",
})

_EXPLICIT_RESEARCH_PREFIXES = (
    "pesquisa na web ",
    "pesquisa na internet ",
    "pesquisa online ",
    "procura na web ",
    "procura na internet ",
    "procura online ",
    "consulta a web ",
    "consulta a internet ",
    "investiga na web ",
)


def _norm(value: str) -> str:
    value = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )
    value = "".join(
        ch for ch in value
        if not unicodedata.combining(ch)
    )
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _semantic_text(value: str) -> str:
    normalized = _norm(value)

    normalized = re.sub(
        r"^(?:jarvis|jervis|jarves|jarviz|zarvis)[,;:\s]+",
        "",
        normalized,
        count=1,
    ).strip()

    normalized = re.sub(
        r"[,;:\s]+(?:jarvis|jervis|jarves|jarviz|zarvis)$",
        "",
        normalized,
        count=1,
    ).strip()

    return normalized


def resolve_semantic_request(text: str) -> StructuredRequest:
    """
    Resolve one OWNER message into the single structured semantic contract.

    v1 is intentionally conservative:
    - exact/high-confidence conversational signals are resolved here;
    - the legacy RequestIntent classifier is consumed only as a temporary
      compatibility signal;
    - ambiguous language remains UNKNOWN instead of being guessed.
    """

    raw = str(text or "").strip()
    if not raw:
        raise ValueError("semantic request text must not be empty")

    normalized = _semantic_text(raw)

    if normalized in _GREETING_EXACT:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="GENERAL_CONVERSATION",
            domain="conversation",
            subject="JARVIS",
            action="greet",
            target="JARVIS",
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    if normalized in _SOCIAL_EXACT:
        action = (
            "provoke"
            if normalized in {"provoca-me", "provoca me"}
            else "social_engage"
        )

        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="SOCIAL_INTERACTION",
            domain="conversation",
            subject="JARVIS",
            action=action,
            target="OWNER",
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    if any(
        normalized.startswith(prefix)
        for prefix in _EXPLICIT_RESEARCH_PREFIXES
    ):
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="RESEARCH",
            domain="web",
            subject="EXTERNAL",
            action="research",
            target=None,
            requires_tool=True,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    legacy = classify_request_intent(raw)

    if legacy.kind == "SELF_STATE_CONVERSATION":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="SELF_STATE",
            domain="jarvis_self",
            subject="JARVIS",
            action="read_state",
            target="JARVIS",
            requires_tool=True,
            preferred_tool="get_synthetic_self_state",
            epistemic_learning_eligible=False,
            confidence=0.98,
        )

    if legacy.kind == "IDENTITY_DIALOGUE":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="IDENTITY_DIALOGUE",
            domain="jarvis_self",
            subject="JARVIS",
            action="discuss_identity",
            target="JARVIS",
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.98,
        )

    if legacy.kind == "CONVERSATION_RECALL":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="CONVERSATION_RECALL",
            domain="owner_memory",
            subject="OWNER",
            action="recall_conversation",
            target=None,
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.98,
        )

    if legacy.kind == "KNOWLEDGE_CAPABILITY":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="KNOWLEDGE_CAPABILITY",
            domain="knowledge",
            subject="JARVIS",
            action="answer_knowledge",
            target=None,
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=True,
            confidence=0.95,
        )

    if legacy.kind == "OPERATIONAL_ACTION":
        action = None
        target = None
        preferred_tool = None

        match = re.match(
            r"^(?:jarvis[,;:\s]+)?"
            r"(abre|fecha|inicia|lanca|executa|corre)\s+(.+)$",
            normalized,
        )

        if match:
            verb = match.group(1)
            target = match.group(2).strip()
            target = re.sub(
                r"^(?:o|a|os|as|um|uma)\s+",
                "",
                target,
                count=1,
            ).strip()

            if verb in {"abre", "inicia", "lanca"}:
                action = "open"
                preferred_tool = "open_app"
            elif verb == "fecha":
                action = "close"
            else:
                action = "execute"

        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="desktop" if action in {"open", "close"} else "system",
            subject="SYSTEM",
            action=action,
            target=target,
            requires_tool=True,
            preferred_tool=preferred_tool,
            epistemic_learning_eligible=False,
            confidence=0.95,
        )

    return StructuredRequest(
        raw_text=raw,
        effective_text=raw,
        intent="UNKNOWN",
        domain="unknown",
        subject="UNKNOWN",
        action=None,
        target=None,
        requires_tool=False,
        preferred_tool=None,
        epistemic_learning_eligible=False,
        confidence=0.20,
    )
