from __future__ import annotations

import re
import unicodedata

from jarvis_core.services.learning_followup import (
    isolated_public_url,
)
from jarvis_core.services.autonomy import (
    parse_direct_external_learning_order,
    parse_learning_goal,
    parse_local_teaching_statement,
)
from jarvis_core.services.context_clause_resolver import (
    resolve_context_clauses,
)
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

_CURRENT_TIME_EXACT = frozenset({
    "que horas sao",
    "qual e a hora atual",
    "agora sao que horas",
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

    # Terminal punctuation does not change semantic intent.
    normalized = normalized.rstrip(" .!?").strip()

    return normalized


def _clean_app_target(
    value: str,
) -> str:
    target = _semantic_text(value)

    target = re.sub(
        r"^(?:o|a|os|as|um|uma)\s+",
        "",
        target,
        count=1,
    ).strip()

    return target.strip(
        " ,.;:!?\\\"'"
    )


def _known_app_open(
    normalized: str,
    app_aliases: dict[str, str] | None,
) -> tuple[str, str] | None:
    aliases: dict[str, str] = {}

    for alias, canonical in dict(
        app_aliases or {}
    ).items():
        alias_normalized = _clean_app_target(
            str(alias)
        )

        canonical_value = str(
            canonical
            or ""
        ).strip()

        if (
            alias_normalized
            and canonical_value
        ):
            aliases[
                alias_normalized
            ] = canonical_value

    if not aliases:
        return None

    match = re.match(
        r"^(?:abre(?:-me)?|inicia|lanca|executa|corre)"
        r"\s+(.+)$",
        normalized,
    )

    if not match:
        return None

    semantic_target = _clean_app_target(
        match.group(1)
    )

    tool_target = aliases.get(
        semantic_target
    )

    if not tool_target:
        return None

    return (
        semantic_target,
        tool_target,
    )


def _subject_hint(
    raw: str,
    normalized: str,
) -> str | None:
    # Subject inference is deliberately restricted to
    # questions so possessives inside operational orders
    # cannot accidentally change execution semantics.
    if not str(raw).rstrip().endswith("?"):
        return None

    if (
        re.search(
            r"\b(?:meu|minha|meus|minhas|mim)\b",
            normalized,
        )
        or re.search(
            r"\b(?:eu\s+prefiro|prefiro)\b",
            normalized,
        )
        or normalized.startswith(
            "onde vivo"
        )
    ):
        return "OWNER"

    if (
        re.search(
            r"\b(?:teu|tua|teus|tuas|ti)\b",
            normalized,
        )
        or re.search(
            r"\btu\s+preferes\b",
            normalized,
        )
        or normalized.startswith(
            "onde vives"
        )
    ):
        return "JARVIS"

    return None


def local_pdf_library_sync_requested(
    text: str,
) -> bool:
    """Detect an explicit request to synchronize the local PDF library."""
    value = str(text or "").casefold()

    asks_to_learn = bool(
        re.search(
            r"\b(?:aprende|aprender|estuda|estudar|indexa|indexar)\b",
            value,
        )
    )

    targets_pdfs = bool(
        re.search(
            r"\bpdfs?\b",
            value,
        )
    )

    targets_collection = bool(
        re.search(
            r"\b(?:todos|todas|documentos|livros|biblioteca)\b",
            value,
        )
    )

    external_source = bool(
        re.search(
            r"https?://|\b(?:web|internet|online)\b",
            value,
        )
    )

    return (
        asks_to_learn
        and targets_pdfs
        and targets_collection
        and not external_source
    )


def resolve_semantic_request(
    text: str,
    *,
    recent_turns: list[dict] | None = None,
    app_aliases: dict[str, str] | None = None,
    learning_followup: dict | None = None,
) -> StructuredRequest:
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

    if normalized in _CURRENT_TIME_EXACT:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_time",
            target="current_time",
            requires_tool=True,
            preferred_tool="get_current_time",
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    if local_pdf_library_sync_requested(raw):
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="knowledge",
            subject="SYSTEM",
            action="sync_library",
            target="local_pdf_library",
            requires_tool=True,
            preferred_tool="sync_book_library",
            tool_arguments={
                "force": False,
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    direct_external_learning = (
        parse_direct_external_learning_order(
            raw
        )
    )

    if direct_external_learning is not None:
        topic = str(
            direct_external_learning.get("topic")
            or ""
        ).strip()

        query = str(
            direct_external_learning.get("query")
            or ""
        ).strip()

        source_url = str(
            direct_external_learning.get("source_url")
            or ""
        ).strip()

        if topic and query:
            return StructuredRequest(
                raw_text=raw,
                effective_text=raw,
                intent="RESEARCH",
                domain="web",
                subject="EXTERNAL",
                action="learn_external",
                target=topic,
                requires_tool=True,
                preferred_tool=(
                    "execute_authorized_external_learning"
                ),
                tool_arguments={
                    "topic": topic,
                    "query": query,
                    "source_text": raw,
                    "deep": bool(
                        direct_external_learning.get(
                            "deep",
                            True,
                        )
                    ),
                    "scope": (
                        "single_research_session"
                    ),
                    "source_url": source_url,
                    "standing_public_web_read_only_grant": bool(
                        direct_external_learning.get(
                            "standing_public_web_read_only_grant"
                        )
                    ),
                },
                epistemic_learning_eligible=True,
                confidence=0.99,
            )

    local_teaching = (
        parse_local_teaching_statement(
            raw
        )
    )

    if local_teaching is not None:
        statement = str(
            local_teaching.get("statement")
            or ""
        ).strip()

        if statement:
            return StructuredRequest(
                raw_text=raw,
                effective_text=raw,
                intent="OPERATIONAL_ACTION",
                domain="knowledge",
                subject="JARVIS",
                action="record_local_teaching",
                target=statement,
                requires_tool=True,
                preferred_tool="record_local_teaching",
                tool_arguments={
                    "statement": statement,
                    "source_text": raw,
                },
                epistemic_learning_eligible=False,
                confidence=0.99,
            )

    learning_goal = (
        parse_learning_goal(
            raw
        )
    )

    if learning_goal is not None:
        topic = str(
            learning_goal.get("topic")
            or ""
        ).strip()

        if topic:
            return StructuredRequest(
                raw_text=raw,
                effective_text=raw,
                intent="OPERATIONAL_ACTION",
                domain="knowledge",
                subject="JARVIS",
                action="record_learning_goal",
                target=topic,
                requires_tool=True,
                preferred_tool="record_jarvis_learning_goal",
                tool_arguments={
                    "topic": topic,
                    "source_text": raw,
                },
                epistemic_learning_eligible=True,
                confidence=0.99,
            )

    followup_url = (
        isolated_public_url(
            raw
        )
    )

    followup_topic = str(
        (
            learning_followup
            or {}
        ).get(
            "topic"
        )
        or ""
    ).strip()

    followup_created_at = (
        (
            learning_followup
            or {}
        ).get(
            "created_at"
        )
    )

    if (
        followup_url
        and followup_topic
        and isinstance(
            followup_created_at,
            (int, float),
        )
        and float(
            followup_created_at
        ) > 0.0
    ):
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="RESEARCH",
            domain="web",
            subject="EXTERNAL",
            action="learn_external",
            target=followup_topic,
            referent=followup_topic,
            requires_tool=True,
            preferred_tool=(
                "execute_authorized_external_learning"
            ),
            tool_arguments={
                "topic": followup_topic,
                "query": followup_topic,
                "source_text": raw,
                "deep": True,
                "scope":
                    "single_research_session",
                "source_url": followup_url,
                "standing_public_web_read_only_grant":
                    False,
                "authority_mode":
                    "followup_url",
            },
            epistemic_learning_eligible=True,
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

    context_resolution = resolve_context_clauses(
        raw,
        recent_turns=recent_turns,
        app_aliases=app_aliases,
    )

    if context_resolution.kind == "SELF_STATE":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="SELF_STATE",
            domain="jarvis_self",
            subject="JARVIS",
            action="read_state",
            target="JARVIS",
            referent=context_resolution.referent,
            requires_tool=True,
            preferred_tool="get_synthetic_self_state",
            epistemic_learning_eligible=False,
            confidence=context_resolution.confidence,
        )

    if context_resolution.kind == "OPERATIONAL_ACTION":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action=context_resolution.action,
            target=context_resolution.target,
            requires_tool=True,
            preferred_tool="open_application",
            tool_arguments={
                "app_name": context_resolution.target,
            },
            epistemic_learning_eligible=False,
            confidence=context_resolution.confidence,
        )

    if context_resolution.kind == "SOCIAL_INTERACTION":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="SOCIAL_INTERACTION",
            domain="conversation",
            subject="JARVIS",
            action=context_resolution.action,
            target="OWNER",
            referent=context_resolution.referent,
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=context_resolution.confidence,
        )

    known_app_open = _known_app_open(
        normalized,
        app_aliases,
    )

    if known_app_open is not None:
        (
            semantic_target,
            tool_target,
        ) = known_app_open

        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="open",
            target=semantic_target,
            requires_tool=True,
            preferred_tool="open_application",
            tool_arguments={
                "app_name": tool_target,
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    ambiguous_action = re.match(
        r"^(?:abre(?:-me)?|fecha|inicia|lanca|executa|corre)"
        r"\s+(?:isso|isto|aquilo)$",
        normalized,
    )

    if ambiguous_action:
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

    subject_hint = _subject_hint(
        raw,
        normalized,
    )

    if subject_hint is not None:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="UNKNOWN",
            domain=(
                "owner_memory"
                if subject_hint == "OWNER"
                else "jarvis_self"
            ),
            subject=subject_hint,
            action=None,
            target=None,
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.95,
        )

    # Compound or negated operational language that was not
    # deterministically resolved above must remain fail closed.
    # resolver. Until that exists, fail closed rather than act on a bad target.
    operational_word = re.search(
        r"\b(?:abre|abrir|abras|inicia|iniciar|lanca|lancar|executa|executar|"
        r"fecha|fechar|feches|encerra|encerrar|termina|terminar)\b",
        normalized,
    )

    compound_marker = (
        re.search(
            r"\b(?:nao|nem)\b",
            normalized,
        )
        or re.search(
            r"\bem vez d(?:e|o|a|os|as)\b",
            normalized,
        )
    )

    if operational_word and compound_marker:
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
                preferred_tool = "open_application"
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
            tool_arguments=(
                {"app_name": target}
                if (
                    preferred_tool == "open_application"
                    and target
                )
                else None
            ),
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
