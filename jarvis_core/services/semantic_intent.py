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

_MUTE_EXACT = frozenset({
    "silencia o audio",
    "silencia o som",
    "desliga o som",
    "poe no silencio",
    "coloca no silencio",
    "mute",
})

_UNMUTE_EXACT = frozenset({
    "ativa o som",
    "activa o som",
    "tira o silencio",
    "retira o silencio",
    "liga o som",
    "unmute",
})

_LOCK_WORKSTATION_EXACT = frozenset({
    "bloqueia o computador",
    "bloqueia o pc",
    "tranca o computador",
    "tranca o pc",
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



def _clean_owner_memory_fact(
    value: str,
) -> str:
    """Remove command metadata that is not part of the OWNER fact."""

    text = str(
        value or ""
    ).strip()

    text = re.sub(
        (
            r"(?:[.!?]\s*)+"
            r"(?:isto\s+(?:e|\u00e9)|e)"
            r"\s+uma\s+ordem"
            r"[.!?]*\s*$"
        ),
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    return text.rstrip(
        " ,;:.!?"
    ).strip()


def _extract_explicit_owner_memory_fact(
    value: str,
) -> str | None:
    """Resolve explicit OWNER memory writes before execution.

    SemanticResolver owns the linguistic meaning and exact fact.
    Downstream routers receive only the immutable StructuredRequest
    and must not re-parse OWNER language to decide what is stored.
    """

    raw = re.sub(
        (
            r"^\s*"
            r"(?:jarvis|jervis|jarves|jarviz|"
            r"zarbis|zarvis|jarbis)"
            r"\s*[,;:\-]?\s*"
        ),
        "",
        str(value or ""),
        count=1,
        flags=re.IGNORECASE,
    ).strip()

    if not raw:
        return None

    patterns = (
        # Current semantic contract:
        # "memoriza que X", "memoriza isto: X",
        # "guarda na memoria que X", "lembra-te que X",
        # "lembra que X", "recorda que X" and
        # "quero que te recordes que X".
        (
            r"(?:"
            r"memoriza(?:\s+isto)?"
            r"(?:\s*:\s*|\s+que\s+)"
            r"|guarda"
            r"(?:\s+na\s+mem[o\u00f3]ria)?"
            r"(?:\s*:\s*|\s+que\s+)"
            r"|lembra(?:\s*-\s*|\s+)te"
            r"(?:\s*:\s*|\s+que\s+)"
            r"|lembra"
            r"(?:\s*:\s*|\s+que\s+)"
            r"|recorda"
            r"(?:\s*:\s*|\s+que\s+)"
            r"|quero\s+que\s+te\s+recordes"
            r"(?:\s*:\s*|\s+que\s+)"
            r")"
            r"(?P<fact>.+?)"
            r"\s*[.!?]?\s*"
        ),

        # Fact first, followed by an explicit order to store
        # "this information".
        (
            r"(?P<fact>.+?)"
            r"(?:\s+e\s+|[.!?]\s*)"
            r"(?:eu\s+)?"
            r"(?:quero|pretendo)\s+que\s+"
            r"(?:guardes|memorizes|recordes)\s+"
            r"(?:esta|essa|a)\s+"
            r"informa[c\u00e7][a\u00e3]o"
            r"(?:\s+(?:na|em)\s+"
            r"(?:tua\s+)?mem[o\u00f3]ria)?"
            r"(?:[.!?].*)?"
        ),


        # Fact first, followed by a direct order to store
        # the immediately preceding information:
        # "X, guarda esta informacao".
        (
            r"(?P<fact>.+?)"
            r"(?:\s*[,;:]\s*|[.!?]\s+)"
            r"(?:guarda|memoriza|recorda)\s+"
            r"(?:esta|essa|a)\s+"
            r"informa[c\u00e7][a\u00e3]o"
            r"(?:\s+(?:na|em)\s+"
            r"(?:tua\s+)?mem[o\u00f3]ria)?"
            r"\s*[.!?]?\s*"
        ),

        # Command first:
        # "quero que guardes na tua memoria que X".
        (
            r"(?:eu\s+)?"
            r"(?:quero|pretendo)\s+que\s+"
            r"(?:guardes|memorizes|recordes)\s+"
            r"(?:(?:esta|essa|a)\s+"
            r"informa[c\u00e7][a\u00e3]o\s*)?"
            r"(?:(?:na|em)\s+"
            r"(?:tua\s+)?mem[o\u00f3]ria\s*)?"
            r"(?::|de\s+que|que)\s*"
            r"(?P<fact>.+?)"
            r"\s*[.!?]?\s*"
        ),

        # Legacy direct form with optional "esta informacao"
        # and explicit memory target.
        (
            r"(?:guarda|memoriza|recorda|"
            r"lembra[ -]?te)\s+"
            r"(?:(?:esta|essa|a)\s+"
            r"informa[c\u00e7][a\u00e3]o\s*)?"
            r"(?:(?:na|em)\s+"
            r"(?:tua\s+)?mem[o\u00f3]ria\s*)?"
            r"(?::|que)\s*"
            r"(?P<fact>.+?)"
            r"\s*[.!?]?\s*"
        ),

        # Natural explicit memory instruction:
        # "quero que memorizes o nome..."
        (
            r"(?:eu\s+)?"
            r"(?:quero|pretendo)\s+que\s+"
            r"memorizes\s+"
            r"(?P<fact>.+?)"
            r"\s*[.!?]?\s*"
        ),

        # Natural direct instruction:
        # "memoriza o nome..."
        (
            r"memoriza\s+"
            r"(?P<fact>.+?)"
            r"\s*[.!?]?\s*"
        ),

        # Explicit memory suffix:
        # "guarda X na tua memoria".
        (
            r"(?:guarda|memoriza|recorda)\s+"
            r"(?P<fact>.+?)\s+"
            r"(?:na|em)\s+"
            r"(?:tua\s+)?mem[o\u00f3]ria"
            r"(?:[.!?]\s*)?"
        ),
    )

    for pattern in patterns:
        match = re.fullmatch(
            pattern,
            raw,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if match is None:
            continue

        fact = (
            _clean_owner_memory_fact(
                match.group(
                    "fact"
                )
            )
        )

        deictic = _norm(
            fact
        )

        if deictic in {
            "isso",
            "isto",
            "essa informacao",
            "esta informacao",
            "a informacao",
            "essa",
            "esta",
        }:
            return None

        return fact or None

    return None


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


def _known_app_close(
    normalized: str,
    app_aliases: dict[str, str] | None,
) -> tuple[str, str] | None:
    """Resolve an explicit close order only for a known app."""

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
        r"^(?:fecha|encerra|termina)"
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


def _owner_memory_scope(
    value: str,
) -> str | None:
    """Resolve an OWNER concept into its admissible memory scope."""

    normalized = _semantic_text(
        value
    )

    patterns = (
        (
            "OWNER_FULL_NAME",
            (
                r"(?:qual e )?"
                r"o meu nome completo"
                r"|meu nome completo"
            ),
        ),
        (
            "OWNER_PROFILE",
            (
                r"como me chamo"
                r"|quem sou eu"
                r"|ainda sabes o meu nome"
                r"|sabes o meu nome"
                r"|mostra (?:o )?meu perfil"
                r"|mostra(?: |-)me "
                r"o meu perfil de utilizador"
                r"|mostra o meu "
                r"perfil de utilizador"
            ),
        ),
        (
            "OWNER_FACTUAL_SUMMARY",
            (
                r"o que sabes(?: realmente)? "
                r"sobre mim"
                r"|o que te lembras de mim"
            ),
        ),
        (
            "OWNER_MEMORY_OVERVIEW",
            (
                r"mostra "
                r"(?:a minha |a )?"
                r"memoria"
            ),
        ),
        (
            "OWNER_GOALS",
            (
                r"que objetivos tenho"
                r"|quais(?: sao)? "
                r"(?:os )?meus objetivos"
                r"|meus objetivos atuais"
                r"|o que quero alcancar"
            ),
        ),
        (
            "OWNER_LEARNING_GOALS",
            (
                r"o que quero aprender"
                r"|o que ando a estudar"
                r"|que temas quero aprender"
                r"|quais sao os meus "
                r"objetivos de aprendizagem"
                r"|meus objetivos de aprendizagem"
            ),
        ),
        (
            "OWNER_HOME",
            (
                r"onde moro"
                r"|(?:(?:recorda|recordas) "
                r"te de )?"
                r"onde eu moro"
                r"|em que cidade vivo"
            ),
        ),
        (
            "OWNER_PERSONAL_MODEL",
            (
                r"mostra o teu modelo "
                r"sobre mim"
                r"|como me modelas"
                r"|(?:mostra(?: |-)me )?"
                r"(?:o )?"
                r"modelo pessoal "
                r"que tens sobre mim"
                r"|que modelo pessoal "
                r"tens de mim"
                r"|meu modelo pessoal"
                r"|modelo pessoal sobre mim"
            ),
        ),
        (
            "OWNER_VIEW",
            (
                r"fala(?: |-)me sobre mim"
                r"|o que (?:pensas|achas) "
                r"de mim"
                r"|(?:de que forma|como) "
                r"(?:tu )?me ves"
                r"|qual e a tua opiniao "
                r"sobre mim"
            ),
        ),
        (
            "OWNER_RELATIONSHIP",
            (
                r"(?:qual e )?"
                r"o nome da minha mulher"
                r"|quem e "
                r"(?:a )?minha mulher"
                r"|(?:recorda|recordas)"
                r"(?: |-)te "
                r"(?:do nome da minha mulher"
                r"|de quem e a minha mulher)"
                r"|quem e (?:a )?"
                r"[^?!.]{2,80} para mim"
            ),
        ),
        (
            "OWNER_EXPLICIT_FACT",
            (
                r"qual (?:era|foi) "
                r"o codigo de teste"
                r"(?: .*)?"
                r"|codigo de teste "
                r"desta sessao"
            ),
        ),
    )

    for scope, pattern in patterns:
        if re.fullmatch(
            pattern,
            normalized,
        ):
            return scope

    return None


def _jarvis_memory_scope(
    value: str,
) -> str | None:
    """Resolve a JARVIS-self concept into its memory scope."""

    normalized = _semantic_text(
        value
    )

    if re.fullmatch(
        (
            r"quais sao "
            r"(?:os )?"
            r"teus objetivos "
            r"de aprendizagem"
            r"|teus objetivos "
            r"de aprendizagem"
        ),
        normalized,
    ):
        return (
            "JARVIS_LEARNING_GOALS"
        )

    if re.fullmatch(
        (
            r"quais sao "
            r"(?:as )?"
            r"tuas diretivas"
            r"|tuas diretivas"
        ),
        normalized,
    ):
        return (
            "JARVIS_DIRECTIVES"
        )

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

    volume_match = re.fullmatch(
        (
            r"(?:coloca|poe|mete|define)\s+"
            r"(?:o\s+)?(?:volume|som)\s+"
            r"(?:a|em)\s+"
            r"(\d{1,3})\s*%?"
        ),
        normalized,
    )

    if volume_match is not None:
        percent = int(
            volume_match.group(1)
        )

        if 0 <= percent <= 100:
            return StructuredRequest(
                raw_text=raw,
                effective_text=raw,
                intent="OPERATIONAL_ACTION",
                domain="system",
                subject="SYSTEM",
                action="set_volume",
                target="master_volume",
                requires_tool=True,
                preferred_tool="set_master_volume",
                tool_arguments={
                    "percent": percent,
                },
                epistemic_learning_eligible=False,
                confidence=0.99,
            )

    if normalized in _UNMUTE_EXACT:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="set_mute",
            target="master_audio",
            requires_tool=True,
            preferred_tool="set_mute",
            tool_arguments={
                "muted": False,
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    if normalized in _MUTE_EXACT:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="set_mute",
            target="master_audio",
            requires_tool=True,
            preferred_tool="set_mute",
            tool_arguments={
                "muted": True,
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    if normalized in _LOCK_WORKSTATION_EXACT:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="lock",
            target="workstation",
            requires_tool=True,
            preferred_tool="lock_workstation",
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    telemetry_words = set(
        re.findall(
            r"[a-z0-9]+",
            normalized,
        )
    )

    if {
        "cpu",
        "ram",
        "gpu",
    }.issubset(
        telemetry_words
    ):
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_combined_telemetry",
            target="system_telemetry",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    gpu_subject = bool(
        telemetry_words.intersection({
            "gpu",
            "grafica",
            "rtx",
        })
    )

    gpu_metric = bool(
        telemetry_words.intersection({
            "agora",
            "atual",
            "temperatura",
            "estado",
            "utilizacao",
            "uso",
            "vram",
            "memoria",
        })
    )

    if gpu_subject and gpu_metric:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_gpu_telemetry",
            target="gpu",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    cpu_subject = bool(
        telemetry_words.intersection({
            "cpu",
            "processador",
        })
    )

    cpu_metric = bool(
        telemetry_words.intersection({
            "utilizacao",
            "uso",
            "atual",
            "agora",
            "estado",
        })
    )

    if cpu_subject and cpu_metric:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_cpu_telemetry",
            target="cpu",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    ram_subject = (
        "ram"
        in telemetry_words
    )

    ram_metric = bool(
        telemetry_words.intersection({
            "utilizacao",
            "uso",
            "usar",
            "utilizar",
            "total",
            "quanto",
            "quanta",
            "atual",
            "agora",
            "estado",
        })
    )

    if ram_subject and ram_metric:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_ram_telemetry",
            target="ram",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
            tool_arguments={},
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    system_telemetry_exact = {
        "como esta o pc",
        "como esta o meu pc",
        "como esta o computador",
        "como esta o meu computador",
        "estado do pc",
        "estado do computador",
        "estado do sistema",
        (
            "resumo rapido do estado "
            "atual do meu computador"
        ),
        (
            "resumo do estado atual "
            "do computador"
        ),
        (
            "faz um resumo do estado "
            "atual do computador"
        ),
    }

    if normalized in system_telemetry_exact:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="system",
            subject="SYSTEM",
            action="read_system_telemetry",
            target="system_telemetry",
            requires_tool=True,
            preferred_tool=(
                "get_pre_request_telemetry"
            ),
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

    # Direct OWNER context belongs to grounded conversation.
    #
    # These are semantic owner-context concepts rather than
    # deterministic commands: identity, profile, the assistant's
    # grounded view of the owner, goals, learning, home context
    # and the personal model.
    #
    # This check intentionally precedes JARVIS self-state so
    # questions such as "o que pensas de mim?" cannot be
    # misread as a request for JARVIS internal affect.
    semantic_owner_text = re.sub(
        r"^jarvis[\s,:;\-]+",
        "",
        normalized,
        count=1,
    ).strip()



    # Explicit OWNER memory writes are deterministic operations.
    # SemanticResolver owns the meaning, exact tool and exact fact.
    # FastRouter must not re-parse OWNER language to decide what to store.
    memory_fact = _extract_explicit_owner_memory_fact(
        raw
    )

    if memory_fact:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="owner_memory",
            subject="OWNER",
            action="remember_owner_fact",
            target="OWNER",
            requires_tool=True,
            preferred_tool="remember_user_fact",
            tool_arguments={
                "fact": memory_fact,
                "category": "user_explicit",
            },
            epistemic_learning_eligible=False,
            confidence=0.99,
        )

    recent_explicit_owner_memory = bool(
        re.fullmatch(
            (
                r"(?:recorda|lembra(?: |-)te) "
                r"(?:do|o) que te pedi para "
                r"(?:guardar|memorizar|lembrares)"
                r"(?: .*)?"
            ),
            semantic_owner_text,
        )
    )

    if recent_explicit_owner_memory:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="GENERAL_CONVERSATION",
            domain="owner_memory",
            subject="OWNER",
            action="recall_recent_explicit_memory",
            target="OWNER",
            memory_scope=
                "OWNER_RECENT_EXPLICIT",
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.95,
        )

    direct_owner_context = bool(
        re.fullmatch(
            (
                r"(?:"
                r"como me chamo"
                r"|quem sou eu"
                r"|mostra (?:o )?meu perfil"
                r"|fala(?: |-)me sobre mim"
                r"|o que (?:pensas|achas) de mim"
                r"|(?:de que forma|como) (?:tu )?me ves"
                r"|qual e a tua opiniao sobre mim"
                r"|que objetivos tenho"
                r"|quais(?: sao)? (?:os )?meus objetivos"
                r"|meus objetivos atuais"
                r"|o que quero alcancar"
                r"|o que quero aprender"
                r"|o que ando a estudar"
                r"|que temas quero aprender"
                r"|onde moro"
                r"|(?:(?:recorda|recordas) te de )?onde eu moro"
                r"|em que cidade vivo"
                r"|mostra o teu modelo sobre mim"
                r"|como me modelas"
                r"|mostra(?: |-)me o meu perfil de utilizador"
                r"|mostra o meu perfil de utilizador"
                r"|(?:qual e )?o meu nome completo"
                r"|meu nome completo"
                r"|o que te lembras de mim"
                r"|mostra (?:a minha |a )?memoria"
                r"|quais sao os meus objetivos de aprendizagem"
                r"|meus objetivos de aprendizagem"
                r"|(?:mostra(?: |-)me )?(?:o )?modelo pessoal que tens sobre mim"
                r"|meu modelo pessoal"
                r"|modelo pessoal sobre mim"
                r"|(?:recorda|recordas)(?: |-)te "
                r"(?:do nome da minha mulher|de quem e a minha mulher)"
                r"|quem e (?:a )?[^?!.]{2,80} para mim"
                r"|qual (?:era|foi) o codigo de teste(?: .*)?"
                r"|codigo de teste desta sessao"
                r")"
            ),
            semantic_owner_text,
        )
    )

    if direct_owner_context:
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="GENERAL_CONVERSATION",
            domain="owner_memory",
            subject="OWNER",
            action="discuss_owner_context",
            target="OWNER",
            memory_scope=_owner_memory_scope(
                raw
            ),
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.95,
        )

    # Direct first-person self-state concepts belong to the
    # conversational model, not to the deterministic router.
    #
    # Keep this semantic rather than route-specific: affect,
    # internal-state inspection and active intention/objective
    # are all interpretations of JARVIS runtime self-state.
    semantic_self_text = re.sub(
        r"^jarvis[\s,:;\-]+",
        "",
        normalized,
        count=1,
    ).strip()

    direct_self_state = bool(
        re.fullmatch(
            (
                r"(?:"
                r"o que sentes"
                r"(?: agora| neste momento)?"
                r"|"
                r"(?:mostra(?: me)? )?"
                r"(?:o )?teu estado interno"
                r"(?: neste momento)?"
                r"|"
                r"(?:tens (?:algum )?)?"
                r"(?:pensamento ou )?"
                r"(?:objetivo|intencao|pensamento) ativo"
                r"(?: neste momento)?"
                r")"
            ),
            semantic_self_text,
        )
    )

    if direct_self_state:
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

    known_app_close = _known_app_close(
        normalized,
        app_aliases,
    )

    if known_app_close is not None:
        (
            semantic_target,
            tool_target,
        ) = known_app_close

        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="OPERATIONAL_ACTION",
            domain="desktop",
            subject="SYSTEM",
            action="close",
            target=semantic_target,
            requires_tool=True,
            preferred_tool="close_application",
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

    # High-confidence self-state meaning must win
    # over a generic JARVIS subject hint. Phrases such as
    # "qual e a tua carga cognitiva" contain possessives
    # ("tua"/"teu"), but they ask about current runtime
    # state rather than JARVIS identity.
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

    subject_hint = _subject_hint(
        raw,
        normalized,
    )

    if subject_hint == "OWNER":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="GENERAL_CONVERSATION",
            domain="owner_memory",
            subject="OWNER",
            action="discuss_owner_context",
            target="OWNER",
            memory_scope=_owner_memory_scope(
                raw
            ),
            requires_tool=False,
            preferred_tool=None,
            epistemic_learning_eligible=False,
            confidence=0.95,
        )

    if subject_hint == "JARVIS":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="IDENTITY_DIALOGUE",
            domain="jarvis_self",
            subject="JARVIS",
            action="discuss_identity",
            target="JARVIS",
            memory_scope=_jarvis_memory_scope(
                raw
            ),
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

    if legacy.kind == "IDENTITY_DIALOGUE":
        return StructuredRequest(
            raw_text=raw,
            effective_text=raw,
            intent="IDENTITY_DIALOGUE",
            domain="jarvis_self",
            subject="JARVIS",
            action="discuss_identity",
            target="JARVIS",
            memory_scope=_jarvis_memory_scope(
                raw
            ),
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
