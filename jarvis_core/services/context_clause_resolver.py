from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Mapping

from jarvis_core.services.request_intent import (
    classify_request_intent,
)


@dataclass(frozen=True, slots=True)
class ContextClauseResolution:
    """
    Deterministic semantic resolution for immediate context
    and compound clause polarity.

    This service never executes tools and never grants
    authorization.
    """

    kind: str = "NONE"
    action: str | None = None
    target: str | None = None
    referent: str | None = None
    excluded_targets: tuple[str, ...] = ()
    confidence: float = 0.0


def _norm(value: str) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )

    text = "".join(
        ch
        for ch in text
        if not unicodedata.combining(ch)
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _semantic_text(value: str) -> str:
    text = _norm(value)

    text = re.sub(
        r"^(?:jarvis|jervis|jarves|jarviz|zarvis)"
        r"[,;:\s]+",
        "",
        text,
        count=1,
    ).strip()

    return text.rstrip(
        " .!?"
    ).strip()


def _clean_target(value: str) -> str:
    target = _semantic_text(value)

    target = re.sub(
        r"^(?:o|a|os|as|um|uma)\s+",
        "",
        target,
        count=1,
    ).strip()

    return target.strip(
        " ,.;:!?\"'"
    )


def _normalized_aliases(
    app_aliases: Mapping[str, str] | None,
) -> dict[str, str]:
    result: dict[str, str] = {}

    for alias, canonical in dict(
        app_aliases or {}
    ).items():
        alias_norm = _clean_target(
            str(alias)
        )

        canonical_norm = _clean_target(
            str(canonical)
        )

        if alias_norm and canonical_norm:
            result[alias_norm] = canonical_norm

    return result


def _resolve_known_target(
    value: str,
    aliases: Mapping[str, str],
) -> str | None:
    target = _clean_target(value)

    if not target:
        return None

    return aliases.get(target)


def _direct_self_state(
    normalized: str,
) -> bool:
    markers = (
        "tua confianca",
        "teu nivel de confianca",
        "estas focada",
        "estas focado",
        "teu foco",
        "tens alguma intencao ativa",
        "tens alguma intencao",
        "tua intencao ativa",
        "o que te esta a motivar",
        "o que te motiva",
        "teu estado atual",
        "teu estado sintetico",
    )

    return any(
        marker in normalized
        for marker in markers
    )


def _previous_is_self_state(
    recent_turns: list[dict] | None,
) -> bool:
    rows = list(
        recent_turns or []
    )

    if not rows:
        return False

    latest = (
        rows[-1]
        if isinstance(rows[-1], dict)
        else {}
    )

    route = _norm(
        latest.get("route")
        or ""
    )

    if (
        "self_state" in route
        or "jarvis_self" in route
    ):
        return True

    previous_user = str(
        latest.get("user")
        or ""
    ).strip()

    if not previous_user:
        return False

    try:
        intent = classify_request_intent(
            previous_user
        )
    except Exception:
        return False

    return (
        intent.kind
        == "SELF_STATE_CONVERSATION"
    )


def _contextual_self_state(
    normalized: str,
    recent_turns: list[dict] | None,
) -> bool:
    if not _previous_is_self_state(
        recent_turns
    ):
        return False

    contextual_exact = {
        "e de curiosidade",
        "em que",
        "e alguma preocupacao",
        "isso mudou desde ha pouco",
    }

    return normalized in contextual_exact


def _previous_is_social(
    recent_turns: list[dict] | None,
) -> bool:
    rows = list(
        recent_turns or []
    )

    if not rows:
        return False

    latest = (
        rows[-1]
        if isinstance(rows[-1], dict)
        else {}
    )

    route = _norm(
        latest.get("route")
        or ""
    )

    if "social" in route:
        return True

    previous_user = _semantic_text(
        str(
            latest.get("user")
            or ""
        )
    )

    direct_social = {
        "provoca-me",
        "provoca me",
        "flirta comigo",
        "seduz-me",
        "seduz me",
        "fala comigo",
        "conversa comigo",
        "faz-me companhia",
        "faz me companhia",
    }

    return previous_user in direct_social


def _contextual_social(
    normalized: str,
    recent_turns: list[dict] | None,
) -> bool:
    if not _previous_is_social(
        recent_turns
    ):
        return False

    contextual_exact = {
        "mais",
        "continua",
        "mais subtil",
        "agora mais provocadora",
        "se mais atrevida",
        "agora surpreende-me",
        "quero diversao",
        "que tipo de diversao tens em mente",
    }

    return normalized in contextual_exact


def _add_unique(
    rows: list[str],
    target: str | None,
) -> None:
    if (
        target
        and target not in rows
    ):
        rows.append(target)


def _compound_application_selection(
    normalized: str,
    app_aliases: Mapping[str, str] | None,
) -> ContextClauseResolution | None:
    aliases = _normalized_aliases(
        app_aliases
    )

    # Safety boundary:
    # compound preference/polarity language is promoted
    # to open_application only when the application is
    # known by the runtime-supplied application catalogue.
    if not aliases:
        return None

    has_compound_signal = bool(
        re.search(
            r"[,;.]",
            normalized,
        )
        or " mas " in normalized
        or re.search(
            r"\bem vez d(?:e|o|a|os|as)\b",
            normalized,
        )
    )

    if not has_compound_signal:
        return None

    excluded: list[str] = []
    positive: list[
        tuple[str, str]
    ] = []

    for match in re.finditer(
        r"\bem vez d(?:e|o|a|os|as)"
        r"\s+([^,;.]+)",
        normalized,
    ):
        _add_unique(
            excluded,
            _resolve_known_target(
                match.group(1),
                aliases,
            ),
        )

    clauses = [
        part.strip()
        for part in re.split(
            r"\s*[,;.]\s*|\s+mas\s+",
            normalized,
        )
        if part.strip()
    ]

    open_verbs = (
        r"(?:abre|abra|abrir|inicia|iniciar|"
        r"lanca|lancar)"
    )

    negative_open_verbs = (
        r"(?:abre|abra|abras|abrir|"
        r"inicia|inicies|iniciar|"
        r"lanca|lances|lancar)"
    )

    for original_clause in clauses:
        clause = original_clause.strip()

        if re.match(
            r"^em vez d(?:e|o|a|os|as)\s+",
            clause,
        ):
            continue

        clause = re.split(
            r"\s+em vez d(?:e|o|a|os|as)\s+",
            clause,
            maxsplit=1,
        )[0].strip()

        if not clause:
            continue

        match = re.match(
            rf"^nao\s+{negative_open_verbs}"
            rf"\s+(.+)$",
            clause,
        )

        if match:
            _add_unique(
                excluded,
                _resolve_known_target(
                    match.group(1),
                    aliases,
                ),
            )
            continue

        match = re.match(
            rf"^{open_verbs}\s+(.+)$",
            clause,
        )

        if match:
            target = _resolve_known_target(
                match.group(1),
                aliases,
            )

            if target:
                positive.append(
                    (
                        target,
                        "explicit_open",
                    )
                )
            continue

        match = re.match(
            r"^nao\s+quero\s+(.+)$",
            clause,
        )

        if match:
            _add_unique(
                excluded,
                _resolve_known_target(
                    match.group(1),
                    aliases,
                ),
            )
            continue

        match = re.match(
            r"^quero\s+(.+)$",
            clause,
        )

        if match:
            target = _resolve_known_target(
                match.group(1),
                aliases,
            )

            if target:
                positive.append(
                    (
                        target,
                        "app_choice",
                    )
                )
            continue

        match = re.match(
            r"^nao\s+(?:o|a|os|as)?\s*(.+)$",
            clause,
        )

        if match:
            _add_unique(
                excluded,
                _resolve_known_target(
                    match.group(1),
                    aliases,
                ),
            )
            continue

        match = re.match(
            r"^(.+?)\s+(nao|sim)$",
            clause,
        )

        if match:
            target = _resolve_known_target(
                match.group(1),
                aliases,
            )

            if not target:
                continue

            if match.group(2) == "sim":
                positive.append(
                    (
                        target,
                        "app_choice",
                    )
                )
            else:
                _add_unique(
                    excluded,
                    target,
                )

    unique_positive: list[
        tuple[str, str]
    ] = []

    for target, source in positive:
        if target in excluded:
            continue

        if any(
            existing_target == target
            for existing_target, _ in unique_positive
        ):
            continue

        unique_positive.append(
            (
                target,
                source,
            )
        )

    if len(unique_positive) != 1:
        return None

    target, source = unique_positive[0]

    confidence = (
        0.99
        if source == "explicit_open"
        else 0.97
    )

    return ContextClauseResolution(
        kind="OPERATIONAL_ACTION",
        action="open",
        target=target,
        excluded_targets=tuple(
            excluded
        ),
        confidence=confidence,
    )


def resolve_context_clauses(
    text: str,
    *,
    recent_turns: list[dict] | None = None,
    app_aliases: Mapping[str, str] | None = None,
) -> ContextClauseResolution:
    """
    Resolve only deterministic context or clause meaning.

    No tools are executed here.

    Ambiguous ellipsis remains unresolved without
    immediate contextual evidence.

    Compound application choice remains unresolved
    without the runtime application catalogue.
    """

    normalized = _semantic_text(text)

    if not normalized:
        return ContextClauseResolution()

    if _direct_self_state(normalized):
        return ContextClauseResolution(
            kind="SELF_STATE",
            action="read_state",
            target="JARVIS",
            referent="jarvis_self_state",
            confidence=0.98,
        )

    if _contextual_self_state(
        normalized,
        recent_turns,
    ):
        return ContextClauseResolution(
            kind="SELF_STATE",
            action="read_state",
            target="JARVIS",
            referent="jarvis_self_state",
            confidence=0.96,
        )

    if _contextual_social(
        normalized,
        recent_turns,
    ):
        return ContextClauseResolution(
            kind="SOCIAL_INTERACTION",
            action="social_continue",
            target="OWNER",
            referent="social_interaction",
            confidence=0.96,
        )

    compound = (
        _compound_application_selection(
            normalized,
            app_aliases,
        )
    )

    if compound is not None:
        return compound

    return ContextClauseResolution()
