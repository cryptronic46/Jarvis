from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from secrets import token_hex
from threading import RLock
from typing import Any
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


CAPABILITIES = {
    "web_research",
    "cloud_reasoning",
    "external_learning",
    "tool_override",
}

AUTONOMOUS_CLOUD_REASONS = {
    "complex_task",
    "complex_local_insufficient",
    "resource_pressure_offload",
    "local_error_fallback",
}

DIRECT_EXTERNAL_REASONS = {
    "forced_cloud",
    "forced_web",
    "forced_sol",
    "explicit_cloud",
    "explicit_web",
}


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _norm(value: str) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or "").lower(),
    )
    text = "".join(
        ch
        for ch in text
        if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", text).strip()


_LEARNING_STOPWORDS = {
    "a", "ao", "aos", "as", "o", "os", "um", "uma", "uns", "umas",
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "por", "para", "com", "sem", "e", "ou", "que", "qual", "quais",
    "como", "sobre", "isto", "isso", "aquilo", "este", "esta", "estes",
    "estas", "me", "te", "se", "eu", "tu", "ele", "ela", "eles", "elas",
    "meu", "minha", "meus", "minhas", "seu", "sua", "seus", "suas",
    "jarvis", "senhor", "sabe", "sabes", "sei", "aprendi", "aprendeu",
    "aprendeste", "aprendemos", "aprendizagem", "conhecimento", "conhecimentos",
    "diz", "dizer", "fala", "falar", "explica", "explicar", "tudo", "algo",
}


def _learning_term(value: str) -> str:
    """Small deterministic normalizer for topical learning retrieval.

    It is intentionally not a linguistic stemmer. It only collapses common
    Portuguese plural/gender endings so e.g. humano/humanos/humana can match
    the same stored topic without adding a heavyweight dependency.
    """
    token = re.sub(r"[^a-z0-9_-]", "", _norm(value))
    if len(token) >= 6 and token.endswith("s"):
        token = token[:-1]
    if len(token) >= 6 and token.endswith(("o", "a")):
        token = token[:-1]
    return token


def _learning_terms(value: str) -> set[str]:
    output: set[str] = set()
    normalized = _norm(value)
    # Preserve dotted software/version identifiers (e.g. 3.14, 3.14.7).
    # The old tokenizer split them into 1-2 character fragments and could turn
    # an exact version lookup into a generic recent-record match.
    for version in re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", normalized):
        output.add(version)
    for raw in re.findall(r"[a-z0-9_-]+", normalized):
        if len(raw) < 3 or raw in _LEARNING_STOPWORDS:
            continue
        term = _learning_term(raw)
        if len(term) >= 3 and term not in _LEARNING_STOPWORDS:
            output.add(term)
    return output


def _canonical_payload(
    capability: str,
    payload: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "capability": str(capability),
            "payload": payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def scope_hash(
    capability: str,
    payload: dict[str, Any],
) -> str:
    return sha256(
        _canonical_payload(
            capability,
            payload,
        ).encode("utf-8")
    ).hexdigest()



DIRECT_INTERNET_MARKERS = (
    "internet",
    "web",
    "online",
)

LEARNING_VERBS = (
    "aprende",
    "aprender",
    "aprendas",
    "aprenda",
    "estuda",
    "estudar",
    "estudes",
    "pesquisa",
    "pesquisar",
    "investiga",
    "investigar",
)

AUTHORITY_MARKERS = (
    "tens a minha autorizacao",
    "tem a minha autorizacao",
    "dou te autorizacao",
    "dou-te autorizacao",
    "autorizo te",
    "autorizo-te",
    "estas autorizado",
    "esta autorizado",
    "podes",
)

STANDING_PUBLIC_WEB_PERMISSION = "public_web_read_only_learning"
STANDING_PUBLIC_WEB_RESEARCH_PERMISSION = "public_web_read_only_research"


def explicit_standing_public_web_grant(text: str) -> bool:
    """Return True only for an explicit OWNER grant to access public web.

    This standing permission is intentionally narrow: read-only public web
    research used for learning. It never permits downloads, shell execution,
    account actions, purchases, posting, or widening another security scope.
    """
    normalized = _norm(text)
    patterns = (
        r"\b(?:tens|tem) a minha autorizacao para aceder(?:es)? (?:a |à )?(?:internet|web)\b",
        r"\bdou(?:-te| te)? autorizacao para aceder(?:es)? (?:a |à )?(?:internet|web)\b",
        r"\bautorizo(?:-te| te)? a aceder(?:es)? (?:a |à )?(?:internet|web)\b",
        r"\bpodes aceder (?:a |à )?(?:internet|web)\b",
        r"\b(?:tens|tem) a minha autorizacao para (?:usar|utilizar) (?:a )?(?:internet|web)\b",
        r"\bdou(?:-te| te)? autorizacao para (?:usar|utilizar) (?:a )?(?:internet|web)\b",
        r"\bautorizo(?:-te| te)? a (?:usar|utilizar) (?:a )?(?:internet|web)\b",
        r"\bpodes (?:pesquisar|consultar|estudar) (?:na|pela|atraves da|através da) (?:internet|web)(?: quando precisares)?\b",
        r"\bpodes (?:usar|utilizar) (?:a )?(?:internet|web) quando precisares\b",
    )
    return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns)

LEARNING_GOAL_MARKERS = (
    "quero que tu aprendas",
    "quero que aprendas",
    "quero que estudes",
    "quero que tu estudes",
    "aprende tudo sobre",
    "aprende sobre",
)

_URL_PATTERN = re.compile(r"(?i)https?://[^\s<>\"']+")


_TRACKING_QUERY_KEYS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid",
    "ref", "ref_src", "source",
})


def canonicalize_public_url(url: str, *, preserve_trailing_slash: bool = False) -> str:
    """Return a stable identity URL while preserving functional query keys."""
    raw = str(url or "").strip().rstrip(").,;!?]}")
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return raw[:1200]
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    path = parsed.path or "/"
    if path != "/" and not preserve_trailing_slash:
        path = path.rstrip("/") or "/"
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse((parsed.scheme.lower(), host, path, "", urlencode(query, doseq=True), ""))[:1200]


def _extract_explicit_url(text: str) -> str:
    match = _URL_PATTERN.search(str(text or ""))
    if not match:
        return ""
    return canonicalize_public_url(match.group(0), preserve_trailing_slash=True)


def _topic_for_explicit_url(text: str, url: str) -> str:
    raw = str(text or "")
    without_url = _URL_PATTERN.sub(" ", raw)
    without_url = re.sub(
        r"(?i)[,;]?\s*(?:tens|tem)\s+a\s+minha\s+autoriza(?:ç|c)[aã]o.*$",
        "",
        without_url,
    )
    without_url = re.sub(
        r"(?i)[,;]?\s*autorizo(?:-te|\s+te)?.*$",
        "",
        without_url,
    )
    patterns = (
        r"(?i)aprende\s+tudo\s+o\s+que\s+tens\s+a\s+aprender\s+sobre\s+(.+)$",
        r"(?i)aprende(?:r)?\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)estuda(?:r)?\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)investiga(?:r)?\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)(?:aprende|aprender|estuda|estudar)\s+(.+?)(?:\s+atrav[eé]s\s+(?:deste|desta|do|da)\s+(?:guia|site|p[aá]gina|feed|url)[^:]*)?\s*:?$",
    )
    topic = ""
    # Natural direct-URL question: "Estuda <url> e diz-me qual é a versão ...".
    # The relevance subject must be the question, not the URL + whole command.
    tail = re.search(r"(?i)\b(?:e\s+)?diz[- ]?me\s+(.+)$", without_url)
    if tail:
        topic = _clean_topic(tail.group(1))
        topic = re.sub(r"(?i)^qual\s+(?:e|é)\s+", "", topic).strip()
    for pattern in patterns:
        if topic:
            break
        match = re.search(pattern, without_url)
        if match:
            topic = _clean_topic(match.group(1))
            if topic:
                break

    normalized_topic = _norm(topic)
    vague = {
        "", "isto", "isso", "este site", "esta pagina", "esta página",
        "estas ferramentas", "as ferramentas", "essas ferramentas",
        "o site", "a pagina", "a página", "o conteudo", "o conteúdo",
    }

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path or "/"
    except Exception:
        host, path = "", "/"

    if normalized_topic in {_norm(item) for item in vague}:
        known = (
            (host == "beej.us" and path.startswith("/guide/bgc"), "programação em C"),
            (host == "beej.us" and path.startswith("/guide/bgnet"), "programação de redes e sockets"),
            (host.endswith("debian-handbook.info"), "Debian Administrator Handbook"),
            (host.endswith("richardhammack.github.io") and "bookofproof" in path.casefold(), "Book of Proof"),
            (host.endswith("rust-lang.org") and path.startswith("/book"), "Rust Book"),
            (host == "go.dev" and path.startswith("/ref/spec"), "especificação da linguagem Go"),
            (host.endswith("rfc-editor.org") and "rfc9293" in path.casefold(), "RFC 9293 TCP"),
            (host.endswith("rfc-editor.org") and "rfc8200" in path.casefold(), "RFC 8200 IPv6"),
            (host.endswith("rfc-editor.org") and "rfc8446" in path.casefold(), "RFC 8446 TLS 1.3"),
            (host.endswith("openlogicproject.org"), "Open Logic Project"),
            (host.endswith("cisa.gov") and "known_exploited_vulnerabilities" in path.casefold(), "CISA Known Exploited Vulnerabilities"),
        )
        for applies, resolved_topic in known:
            if applies:
                return resolved_topic
        if host.endswith("kali.org") and path.startswith("/tools"):
            return "ferramentas Kali Linux"
        if host:
            # A bare owner-selected URL needs a meaningful topic.  The old
            # generic label (for example, "conteúdo técnico do site docs" for
            # docs.python.org) made valid Python summaries fail storage
            # relevance merely because they did not repeat "docs".
            ignored_labels = {"www", "docs", "doc", "help", "support", "blog", "dt", "mec"}
            labels = [
                label.replace("-", " ").strip()
                for label in host.split(".")
                if label and label not in ignored_labels
            ]
            # This is only a topic label for the exact owner-selected URL;
            # source and synthesis validation remain unchanged.
            label = labels[-2] if len(labels) >= 2 and labels[-1] in {"org", "com", "net", "edu", "gov", "pt", "uk", "us", "info", "io", "dev"} else (labels[-1] if labels else host)
            return _clean_topic(label or host)

    return topic or _clean_topic(host)


def _clean_topic(value: str) -> str:
    topic = str(value or "").strip()
    # Authorization belongs to the authority layer, never to the subject sent
    # to search/research. Strip only well-known scaffolding, not topic words.
    authorization_prefixes = (
        r"(?i)^tens\s+a\s+minha\s+autoriza[cç][aã]o\s+para\s+",
        r"(?i)^dou[-\s]?te\s+autoriza[cç][aã]o\s+para\s+",
        r"(?i)^autorizo[-\s]?te\s+(?:a|para)\s+",
        r"(?i)^est[aá]s\s+autorizad[oa]\s+(?:a|para)\s+",
        r"(?i)^podes\s+",
        r"(?i)^por\s+minha\s+autoriza[cç][aã]o[,;:]?\s*",
    )
    changed = True
    while changed:
        changed = False
        for pattern in authorization_prefixes:
            cleaned = re.sub(pattern, "", topic, count=1).strip()
            if cleaned != topic:
                topic = cleaned
                changed = True
    topic = re.sub(
        r"(?i)\s*(?:,|;|\-|—)?\s*(?:com\s+a\s+minha\s+autoriza[cç][aã]o|autorizad[oa]\s+por\s+mim)\s*$",
        "",
        topic,
    )
    topic = re.sub(
        r"^[\s,:;.!?\-]+|[\s,:;.!?\-]+$",
        "",
        topic,
    )
    topic = re.sub(
        r"\b(?:atraves|através)\s+(?:da|de)\s+(?:internet|web)\b.*$",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = re.sub(
        r"\b(?:na|pela|via)\s+(?:internet|web)\b.*$",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = re.sub(
        r"\b(?:online)\b.*$",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    # A learning objective can be followed by a clarification about what the
    # OWNER does *not* mean.  That clarification is not part of the topic.
    # Example: "quero que aprendas comportamento humano. Não significa que
    # eu tenha paixão por isso".  Keep only the objective clause.
    topic = re.split(
        r"(?i)[.!?]+\s*(?=(?:nao|não|isto|isso|essa|esta)\b)",
        topic,
        maxsplit=1,
    )[0]
    topic = re.sub(r"(?i)\be\s+sobre\s+", " e ", topic)
    topic = re.sub(r"\s+", " ", topic).strip()
    return topic[:300]


def _topic_after_learning_verb(
    text: str,
) -> str:
    original = str(text or "").strip()

    patterns = (
        # Prefer explicit "sobre X" forms because they give the cleanest
        # topic boundary.
        r"(?i)\baprender\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\baprendas\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\baprenda\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\baprende\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\bestudar\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\bestudes\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\bestuda\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\bpesquisar\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\bpesquisa\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\binvestigar\s+(?:tudo\s+)?sobre\s+(.+)$",
        r"(?i)\binvestiga\s+(?:tudo\s+)?sobre\s+(.+)$",
        # Portuguese users also express learning goals as an infinitive
        # complement rather than "sobre": "aprende a programar em Python",
        # "quero que aprendas a usar Docker", etc.  These forms used to fall
        # through to the LLM, which could then incorrectly deny an OWNER
        # authorization that the deterministic authority layer should own.
        r"(?i)\baprender\s+(?:a\s+)?(.+)$",
        r"(?i)\baprendas\s+(?:a\s+)?(.+)$",
        r"(?i)\baprenda\s+(?:a\s+)?(.+)$",
        r"(?i)\baprende\s+(?:a\s+)?(.+)$",
        r"(?i)\bestudar\s+(.+)$",
        r"(?i)\bestudes\s+(.+)$",
        r"(?i)\bestuda\s+(.+)$",
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            original,
        )
        if match:
            topic = _clean_topic(
                match.group(1)
            )
            if topic:
                return topic

    return ""


def build_external_learning_query(
    topic: str,
) -> str:
    clean = _clean_topic(topic)
    return (
        "Pesquisa na Internet fontes públicas atuais e credíveis sobre "
        f"{clean}. Constrói uma síntese estruturada para aprendizagem futura "
        "do JARVIS: conceitos fundamentais, arquitetura ou categorias, padrões, "
        "limitações, evidência relevante, controvérsias, aplicações práticas e riscos. "
        "Distingue factos, inferências e opiniões. Não inventes dados e evita "
        "inferir características sensíveis do utilizador."
    )


def parse_direct_external_learning_order(
    text: str,
) -> dict[str, Any] | None:
    """
    Detect a direct owner instruction/authorization to perform one bounded
    external-learning research session.

    This does NOT create standing permission. It only recognizes the current
    user utterance as authority for the exact extracted topic.
    """
    raw = str(text or "").strip()
    normalized = _norm(raw)
    source_url = _extract_explicit_url(raw)

    has_external_target = bool(source_url) or any(
        marker in normalized
        for marker in DIRECT_INTERNET_MARKERS
    ) or any(
        marker in normalized
        for marker in ("visita este site", "visita o site", "consulta este site", "consulta o site")
    )
    if not has_external_target:
        return None

    # External research is not the same thing as durable learning.  A plain
    # "pesquisa/consulta/investiga <URL>" must remain a research request; only
    # an explicit learn/study verb authorizes the learning pipeline.
    explicit_learning_markers = (
        "aprende", "aprender", "aprendas", "aprenda",
        "estuda", "estudar", "estudes",
    )
    if not any(marker in normalized for marker in explicit_learning_markers):
        return None

    explicit_authority = any(
        marker in normalized
        for marker in AUTHORITY_MARKERS
    )
    direct_order = bool(source_url) or any(
        marker in normalized
        for marker in (
            "pesquisa na internet",
            "pesquisa na web",
            "aprende atraves da internet",
            "aprende através da internet",
            "aprende pela internet",
            "estuda na internet",
            "investiga na internet",
            "visita este site",
            "visita o site",
            "consulta este site",
            "consulta o site",
        )
    )

    if not (
        explicit_authority
        or direct_order
    ):
        return None

    topic = (
        _topic_for_explicit_url(raw, source_url)
        if source_url
        else _topic_after_learning_verb(raw)
    )
    if not topic:
        # Authorization phrasing often places the topic before "através da
        # internet"; capture the phrase after "sobre" as a safe fallback.
        match = re.search(
            r"(?i)\bsobre\s+(.+)$",
            raw,
        )
        if match:
            topic = _clean_topic(
                match.group(1)
            )

    if not topic:
        return None

    return {
        "kind": "direct_external_learning",
        "topic": topic,
        "query": (
            raw
            if source_url
            else build_external_learning_query(topic)
        ),
        "deep": True,
        "scope": "single_research_session",
        "direct_user_authority": True,
        "standing_public_web_read_only_grant": explicit_standing_public_web_grant(raw),
        "source_url": source_url or None,
    }


def parse_learning_goal(
    text: str,
) -> dict[str, Any] | None:
    """
    Detect an explicit OWNER learning objective that does not itself mention an
    external source.  This is *local intent only*: it must never trigger Web
    access, even when a standing public-Web permission exists.  Web research
    requires an explicit current-turn Web/Internet/URL instruction.
    """
    raw = str(text or "").strip()
    normalized = _norm(raw)

    if any(
        marker in normalized
        for marker in DIRECT_INTERNET_MARKERS
    ):
        return None

    explicit_goal = any(
        marker in normalized
        for marker in LEARNING_GOAL_MARKERS
    ) or bool(
        re.search(
            r"(?i)\b(?:aprende|aprender|aprendas|aprenda|estuda|estudar|estudes)\s+(?:a\s+)?[^\s].+",
            raw,
        )
    )
    if not explicit_goal:
        return None

    topic = _topic_after_learning_verb(
        raw
    )
    if not topic:
        return None

    return {
        "kind": "learning_goal",
        "topic": topic,
        "local_only": True,
        "web_requested": False,
    }


def parse_local_teaching_statement(text: str) -> dict[str, Any] | None:
    """Extract knowledge explicitly taught in the current conversation.

    This is deliberately narrower than parse_learning_goal: only wording that
    contains the statement itself is accepted. URLs remain in the external
    learning pipeline.
    """
    raw = str(text or "").strip()
    if _extract_explicit_url(raw):
        return None
    raw = re.sub(r"(?i)^\s*jarvis\s*[,;:]?\s*", "", raw).strip()
    patterns = (
        r"(?is)^aprende\s+(?:isto|esta\s+informa[cç][aã]o)\s*[:,-]\s*(.+)$",
        r"(?is)^aprende\s+que\s+(.+)$",
        r"(?is)^(?:fica\s+a\s+saber|toma\s+nota)\s+que\s+(.+)$",
    )
    statement = ""
    for pattern in patterns:
        match = re.match(pattern, raw)
        if match:
            statement = re.sub(r"\s+", " ", match.group(1)).strip(" \t\r\n.;")
            break
    if len(statement) < 3:
        return None
    return {
        "kind": "local_teaching",
        "statement": statement[:1500],
        "local_only": True,
        "web_requested": False,
    }


class AutonomyGuardian:
    """
    Owner-authority gate for autonomous JARVIS actions.

    Security invariants:
    - The model may request permission but has no tool/API for approving it.
    - Approval is performed only by the local CLI/user-input path.
    - Grants are exact-scope, one-shot and expire.
    - A denial wins; JARVIS cannot widen a denied or approved scope.
    - Direct user instructions may authorize that exact action, but never a
      broader standing permission.
    """

    def __init__(
        self,
        settings,
        events,
        state_path: str | Path = "memory/autonomy_state.json",
        audit_path: str | Path = "memory/autonomy_audit.jsonl",
    ):
        self.settings = settings
        self.events = events
        self.state_path = Path(state_path)
        self.audit_path = Path(audit_path)
        self.state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.audit_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._lock = RLock()
        self._ensure_state()

    def _default_state(self) -> dict[str, Any]:
        return {
            "mode": "owner_strict",
            "owner_authority": "absolute",
            "pending": [],
            "grants": [],
            "denied": [],
            "cooldowns": [],
            "standing_permissions": {},
            "created_at": _iso(),
            "updated_at": _iso(),
        }

    def _ensure_state(self) -> None:
        if not self.state_path.exists():
            self._save(
                self._default_state()
            )
            return

        try:
            state = self._load()
        except Exception:
            state = self._default_state()

        state["mode"] = "owner_strict"
        state["owner_authority"] = "absolute"
        state.setdefault("pending", [])
        state.setdefault("grants", [])
        state.setdefault("denied", [])
        state.setdefault("cooldowns", [])
        state.setdefault("standing_permissions", {})

        # 0.26.5 migration: earlier releases audited the OWNER's explicit
        # general Internet grant but intentionally consumed only the immediate
        # learning action. Recover that exact broad read-only grant from the
        # immutable audit trail so the OWNER does not have to repeat it.
        perms = state.get("standing_permissions") or {}
        if not (perms.get(STANDING_PUBLIC_WEB_PERMISSION) or {}).get("active"):
            migrated = self._find_explicit_standing_web_grant_in_audit()
            if migrated is not None:
                perms[STANDING_PUBLIC_WEB_PERMISSION] = migrated
                state["standing_permissions"] = perms
        self._save(state)

    def _find_explicit_standing_web_grant_in_audit(self) -> dict[str, Any] | None:
        if not self.audit_path.exists():
            return None
        try:
            lines = self.audit_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None
        for line in reversed(lines[-1000:]):
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if str(row.get("event") or "") != "direct_authorized_by_owner":
                continue
            source_text = str(row.get("source_text") or "")
            if explicit_standing_public_web_grant(source_text):
                return {
                    "active": True,
                    "scope": STANDING_PUBLIC_WEB_PERMISSION,
                    "granted_at": str(row.get("timestamp") or _iso()),
                    "source": "migrated_explicit_owner_audit",
                    "description": "public web read-only access authorized by OWNER",
                }
        return None

    def grant_standing_public_web_learning(self, source_text: str) -> dict[str, Any]:
        if not explicit_standing_public_web_grant(source_text):
            return {"ok": False, "error": "STANDING_WEB_GRANT_NOT_EXPLICIT"}
        with self._lock:
            state = self._purge(self._load())
            perms = state.setdefault("standing_permissions", {})
            row = {
                "active": True,
                "scope": STANDING_PUBLIC_WEB_PERMISSION,
                "granted_at": _iso(),
                "source": "explicit_owner_instruction",
                "description": "public web read-only research for OWNER-requested learning",
            }
            perms[STANDING_PUBLIC_WEB_PERMISSION] = row
            # A general explicit Internet grant also authorizes read-only public
            # research. This never grants downloads, account actions, shell,
            # purchases, posting, or expansion of cyber target scope.
            perms[STANDING_PUBLIC_WEB_RESEARCH_PERMISSION] = {
                **row,
                "scope": STANDING_PUBLIC_WEB_RESEARCH_PERMISSION,
                "description": "public web read-only research authorized by OWNER",
            }
            self._save(state)
            self._audit(
                "standing_public_web_learning_granted",
                scope=STANDING_PUBLIC_WEB_PERMISSION,
                source_text=str(source_text or "")[:500],
            )
            return {"ok": True, "permission": row}

    def has_standing_public_web_learning(self) -> bool:
        with self._lock:
            state = self._purge(self._load())
            self._save(state)
            row = (state.get("standing_permissions") or {}).get(STANDING_PUBLIC_WEB_PERMISSION) or {}
            return bool(row.get("active"))

    def has_standing_public_web_research(self) -> bool:
        with self._lock:
            state = self._purge(self._load())
            perms = state.setdefault("standing_permissions", {})
            row = perms.get(STANDING_PUBLIC_WEB_RESEARCH_PERMISSION) or {}
            # Backward-compatible migration: an explicit general Internet grant
            # recovered as the learning permission is sufficient for read-only
            # research as well.
            if not row.get("active"):
                legacy = perms.get(STANDING_PUBLIC_WEB_PERMISSION) or {}
                if legacy.get("active"):
                    row = {
                        **legacy,
                        "scope": STANDING_PUBLIC_WEB_RESEARCH_PERMISSION,
                        "description": "public web read-only research authorized by OWNER",
                    }
                    perms[STANDING_PUBLIC_WEB_RESEARCH_PERMISSION] = row
            self._save(state)
            return bool(row.get("active"))

    def _load(self) -> dict[str, Any]:
        data = json.loads(
            self.state_path.read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(data, dict):
            raise ValueError("Invalid autonomy state")
        return data

    def _save(
        self,
        state: dict[str, Any],
    ) -> None:
        state["mode"] = "owner_strict"
        state["owner_authority"] = "absolute"
        state["updated_at"] = _iso()
        self.state_path.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def _audit(
        self,
        event: str,
        **data: Any,
    ) -> None:
        row = {
            "timestamp": _iso(),
            "event": event,
            **data,
        }
        with self.audit_path.open(
            "a",
            encoding="utf-8",
        ) as stream:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )

        self.events.emit(
            f"AUTONOMY_{event.upper()}",
            **data,
        )

    def _parse_dt(
        self,
        value: Any,
    ) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(
                str(value)
            )
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt
        except Exception:
            return None

    def _purge(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now()

        pending = []
        cooldowns = list(state.get("cooldowns") or [])
        for row in state.get(
            "pending"
        ) or []:
            expiry = self._parse_dt(
                row.get("expires_at")
            )
            if expiry and expiry >= now:
                pending.append(row)
            else:
                self._audit(
                    "expired",
                    token=row.get("token"),
                    capability=row.get(
                        "capability"
                    ),
                    scope_hash=row.get(
                        "scope_hash"
                    ),
                    kind="pending",
                )
                # Expiring a prompt must not immediately recreate the exact
                # same request. Keep a narrow scope-hash cooldown.
                wanted_hash = str(row.get("scope_hash") or "")
                if wanted_hash:
                    mins = max(1.0, float(getattr(
                        self.settings, "autonomy_expired_cooldown_minutes", 180.0
                    )))
                    cooldowns.append({
                        "scope_hash": wanted_hash,
                        "capability": row.get("capability"),
                        "reason": "expired",
                        "created_at": _iso(),
                        "until": _iso(now + timedelta(minutes=mins)),
                    })

        grants = []
        for row in state.get(
            "grants"
        ) or []:
            expiry = self._parse_dt(
                row.get("expires_at")
            )
            remaining = int(
                row.get("remaining_uses")
                or 0
            )
            if (
                expiry
                and expiry >= now
                and remaining > 0
            ):
                grants.append(row)
            elif remaining > 0:
                self._audit(
                    "expired",
                    token=row.get("token"),
                    capability=row.get(
                        "capability"
                    ),
                    scope_hash=row.get(
                        "scope_hash"
                    ),
                    kind="grant",
                )

        cooldown = timedelta(
            hours=max(
                1.0,
                float(
                    self.settings.autonomy_denial_cooldown_hours
                ),
            )
        )
        denied = []
        for row in state.get(
            "denied"
        ) or []:
            when = self._parse_dt(
                row.get("denied_at")
            )
            if when and now - when <= cooldown:
                denied.append(row)

        active_cooldowns = []
        for row in cooldowns:
            until = self._parse_dt(row.get("until"))
            if until and until >= now:
                active_cooldowns.append(row)

        state["pending"] = pending
        state["grants"] = grants
        state["denied"] = denied
        state["cooldowns"] = active_cooldowns
        return state

    def _ttl(
        self,
        seconds: int,
    ) -> str:
        return _iso(
            _now()
            + timedelta(
                seconds=max(
                    30,
                    int(seconds),
                )
            )
        )

    def _matching_pending(
        self,
        state: dict[str, Any],
        wanted_hash: str,
    ) -> dict[str, Any] | None:
        for row in state.get(
            "pending"
        ) or []:
            if row.get(
                "scope_hash"
            ) == wanted_hash:
                return row
        return None

    def _recently_denied(
        self,
        state: dict[str, Any],
        wanted_hash: str,
    ) -> bool:
        return any(
            row.get("scope_hash")
            == wanted_hash
            for row in state.get(
                "denied"
            ) or []
        )

    def _active_cooldown(
        self,
        state: dict[str, Any],
        wanted_hash: str,
    ) -> dict[str, Any] | None:
        for row in state.get("cooldowns") or []:
            if row.get("scope_hash") == wanted_hash:
                return row
        return None

    def request(
        self,
        *,
        capability: str,
        payload: dict[str, Any],
        reason: str,
        description: str,
        action: str = "resume_query",
        source: str = "autonomous",
    ) -> dict[str, Any]:
        cap = str(capability or "").strip()
        if cap not in CAPABILITIES:
            return {
                "ok": False,
                "error": "UNKNOWN_AUTONOMY_CAPABILITY",
                "capability": cap,
            }

        payload = dict(payload or {})
        wanted_hash = scope_hash(
            cap,
            payload,
        )

        with self._lock:
            state = self._purge(
                self._load()
            )

            # Existing exact grant: consume it immediately.
            for row in state.get(
                "grants"
            ) or []:
                if (
                    row.get("scope_hash")
                    == wanted_hash
                    and row.get("capability")
                    == cap
                    and int(
                        row.get(
                            "remaining_uses"
                        )
                        or 0
                    )
                    > 0
                ):
                    row["remaining_uses"] = (
                        int(
                            row.get(
                                "remaining_uses"
                            )
                            or 0
                        )
                        - 1
                    )
                    row["consumed_at"] = _iso()
                    self._save(state)
                    self._audit(
                        "grant_consumed",
                        token=row.get("token"),
                        capability=cap,
                        scope_hash=wanted_hash,
                        reason=reason,
                    )
                    return {
                        "ok": True,
                        "allowed": True,
                        "authorization": row,
                    }

            existing = self._matching_pending(
                state,
                wanted_hash,
            )
            if existing:
                return {
                    "ok": True,
                    "allowed": False,
                    "pending": True,
                    "reused_pending": True,
                    "token": existing.get(
                        "token"
                    ),
                    "message": self._message(
                        existing
                    ),
                }

            cooldown = self._active_cooldown(state, wanted_hash)
            if cooldown:
                self._save(state)
                return {
                    "ok": True,
                    "allowed": False,
                    "pending": False,
                    "cooldown": True,
                    "cooldown_reason": cooldown.get("reason"),
                    "cooldown_until": cooldown.get("until"),
                    "message": (
                        "Senhor, já lhe pedi autorização para esta pesquisa recentemente. "
                        "Não vou repetir o pedido por agora."
                    ),
                }

            if self._recently_denied(
                state,
                wanted_hash,
            ):
                return {
                    "ok": True,
                    "allowed": False,
                    "pending": False,
                    "denied_recently": True,
                    "message": (
                        "Senhor, esta ação foi recusada recentemente. "
                        "Não vou voltar a pedi-la durante o período de proteção."
                    ),
                }

            if len(
                state.get("pending")
                or []
            ) >= max(
                1,
                int(
                    self.settings.autonomy_max_pending
                ),
            ):
                return {
                    "ok": False,
                    "allowed": False,
                    "error": "AUTONOMY_PENDING_LIMIT",
                }

            token = token_hex(3).upper()
            row = {
                "token": token,
                "capability": cap,
                "payload": payload,
                "scope_hash": wanted_hash,
                "reason": str(reason or "")[
                    :240
                ],
                "description": str(
                    description or ""
                )[:500],
                "action": str(action or "")[
                    :80
                ],
                "source": str(source or "")[
                    :80
                ],
                "created_at": _iso(),
                "expires_at": self._ttl(
                    int(
                        self.settings.autonomy_pending_ttl_seconds
                    )
                ),
            }
            state["pending"].append(row)
            self._save(state)
            self._audit(
                "permission_requested",
                token=token,
                capability=cap,
                scope_hash=wanted_hash,
                reason=row["reason"],
                description=row[
                    "description"
                ],
                source=row["source"],
            )
            return {
                "ok": True,
                "allowed": False,
                "pending": True,
                "token": token,
                "message": self._message(
                    row
                ),
            }

    def _message(
        self,
        row: dict[str, Any],
    ) -> str:
        description = str(
            row.get("description")
            or "executar uma ação autónoma"
        )
        reason = str(
            row.get("reason")
            or "considerei que pode ser útil"
        )
        return (
            f"Senhor, quero {description}. "
            f"Motivo: {reason}. "
            "Não vou avançar sem a sua autorização. "
            "Pode responder simplesmente 'sim', 'podes' ou 'autoriza'. "
            "Para recusar, diga 'não' ou 'agora não'."
        )

    def record_direct_authorization(
        self,
        *,
        capability: str,
        payload: dict[str, Any],
        description: str,
        source_text: str,
    ) -> dict[str, Any]:
        """
        Record an explicit owner instruction from the current user turn.

        It does not create a reusable grant. The caller must execute the exact
        action immediately in the same control path.
        """
        cap = str(capability or "").strip()
        if cap not in CAPABILITIES:
            return {
                "ok": False,
                "error": "UNKNOWN_AUTONOMY_CAPABILITY",
            }

        payload = dict(payload or {})
        wanted_hash = scope_hash(
            cap,
            payload,
        )

        with self._lock:
            state = self._purge(
                self._load()
            )

            # If JARVIS had already asked for the same learning topic, the
            # owner's direct instruction supersedes that pending prompt.
            topic = _norm(
                payload.get("topic")
                or ""
            )
            pending = []
            cleared = 0
            for row in state.get(
                "pending"
            ) or []:
                row_topic = _norm(
                    (row.get("payload") or {}).get(
                        "topic"
                    )
                    or ""
                )
                if (
                    row.get("capability") == cap
                    and topic
                    and row_topic == topic
                ):
                    cleared += 1
                    continue
                pending.append(row)

            state["pending"] = pending
            self._save(state)

            authorization = {
                "capability": cap,
                "payload": payload,
                "scope_hash": wanted_hash,
                "scope": "exact_current_user_instruction",
                "authorized_at": _iso(),
                "source": "direct_user_instruction",
                "reusable": False,
                "remaining_uses": 0,
                "description": str(
                    description or ""
                )[:500],
            }
            self._audit(
                "direct_authorized_by_owner",
                capability=cap,
                scope_hash=wanted_hash,
                description=authorization[
                    "description"
                ],
                cleared_matching_pending=cleared,
                source_text=str(
                    source_text or ""
                )[:500],
            )
            return {
                "ok": True,
                "authorized": True,
                "authorization": authorization,
                "cleared_matching_pending": cleared,
            }

    def authorize(
        self,
        token: str,
    ) -> dict[str, Any]:
        wanted = str(
            token or ""
        ).strip().upper()

        with self._lock:
            state = self._purge(
                self._load()
            )
            match = None
            remaining = []

            for row in state.get(
                "pending"
            ) or []:
                if (
                    match is None
                    and str(
                        row.get("token")
                        or ""
                    ).upper()
                    == wanted
                ):
                    match = row
                else:
                    remaining.append(row)

            if match is None:
                self._save(state)
                return {
                    "ok": False,
                    "error": "UNKNOWN_OR_EXPIRED_AUTHORIZATION",
                }

            state["pending"] = remaining
            grant = {
                **match,
                "authorized_at": _iso(),
                "expires_at": self._ttl(
                    int(
                        self.settings.autonomy_grant_ttl_seconds
                    )
                ),
                "remaining_uses": 1,
            }
            state["grants"].append(
                grant
            )
            self._save(state)
            self._audit(
                "authorized_by_owner",
                token=wanted,
                capability=grant.get(
                    "capability"
                ),
                scope_hash=grant.get(
                    "scope_hash"
                ),
                action=grant.get(
                    "action"
                ),
            )
            return {
                "ok": True,
                "authorized": True,
                "authorization": grant,
            }

    def deny(
        self,
        token: str,
    ) -> dict[str, Any]:
        wanted = str(
            token or ""
        ).strip().upper()

        with self._lock:
            state = self._purge(
                self._load()
            )
            match = None
            remaining = []

            for row in state.get(
                "pending"
            ) or []:
                if (
                    match is None
                    and str(
                        row.get("token")
                        or ""
                    ).upper()
                    == wanted
                ):
                    match = row
                else:
                    remaining.append(row)

            if match is None:
                return {
                    "ok": False,
                    "error": "UNKNOWN_OR_EXPIRED_AUTHORIZATION",
                }

            state["pending"] = remaining
            denied = {
                **match,
                "denied_at": _iso(),
            }
            state["denied"].append(
                denied
            )
            self._save(state)
            self._audit(
                "denied_by_owner",
                token=wanted,
                capability=denied.get(
                    "capability"
                ),
                scope_hash=denied.get(
                    "scope_hash"
                ),
            )
            return {
                "ok": True,
                "denied": True,
                "authorization": denied,
            }

    def revoke_all(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._purge(
                self._load()
            )
            pending = len(
                state.get("pending")
                or []
            )
            grants = len(
                state.get("grants")
                or []
            )
            standing = sum(
                1 for row in (state.get("standing_permissions") or {}).values()
                if isinstance(row, dict) and row.get("active")
            )
            state["pending"] = []
            state["grants"] = []
            state["standing_permissions"] = {}
            self._save(state)
            self._audit(
                "revoked_all",
                pending=pending,
                grants=grants,
                standing_permissions=standing,
            )
            return {
                "ok": True,
                "revoked_pending": pending,
                "revoked_grants": grants,
                "revoked_standing_permissions": standing,
            }

    def status(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._purge(
                self._load()
            )
            self._save(state)
            return {
                "ok": True,
                "mode": "owner_strict",
                "owner_authority": "absolute",
                "self_authorization": False,
                "direct_user_order_scope": "exact_action_only",
                "external_ai_policy": {
                    "mode": "complex_only_after_local" if bool(getattr(self.settings, "external_ai_complex_only", True)) else "manual_or_fallback",
                    "complexity_threshold": int(getattr(self.settings, "external_ai_complexity_threshold", 4)),
                    "auto_escalate_complex": bool(getattr(self.settings, "external_ai_auto_escalate_complex", True)),
                    "fallback_on_local_error": bool(getattr(self.settings, "cloud_fallback_on_local_error", False)),
                    "pressure_offload": bool(getattr(self.settings, "performance_cloud_offload_under_pressure", False)),
                },
                "standing_public_web_read_only_learning": bool(
                    ((state.get("standing_permissions") or {}).get(STANDING_PUBLIC_WEB_PERMISSION) or {}).get("active")
                ),
                "standing_public_web_read_only_research": bool(
                    ((state.get("standing_permissions") or {}).get(STANDING_PUBLIC_WEB_RESEARCH_PERMISSION) or {}).get("active")
                    or ((state.get("standing_permissions") or {}).get(STANDING_PUBLIC_WEB_PERMISSION) or {}).get("active")
                ),
                "pending": len(
                    state.get("pending")
                    or []
                ),
                "active_grants": len(
                    state.get("grants")
                    or []
                ),
                "denial_cooldown_hours": float(
                    self.settings.autonomy_denial_cooldown_hours
                ),
                "pending_ttl_seconds": int(
                    self.settings.autonomy_pending_ttl_seconds
                ),
                "grant_ttl_seconds": int(
                    self.settings.autonomy_grant_ttl_seconds
                ),
                "capabilities": sorted(
                    CAPABILITIES
                ),
            }

    def pending(
        self,
    ) -> list[dict[str, Any]]:
        with self._lock:
            state = self._purge(
                self._load()
            )
            self._save(state)
            return list(
                state.get("pending")
                or []
            )

    def history(
        self,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        if not self.audit_path.exists():
            return []

        rows = []
        for line in self.audit_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)

        return rows[
            -max(
                1,
                min(
                    int(limit),
                    200,
                ),
            ):
        ]


class AuthorizedLearningStore:
    """
    Local journal of external research the owner explicitly authorized JARVIS
    to retain. Entries are synthesized by the JARVIS-owned local Qwen model from
    directly fetched public web sources and remain labelled as summaries rather
    than verified primary-source documents.

    0.20.4 adds a final storage relevance invariant: direct-web local summaries
    must match their own topic. Previously persisted mismatches are quarantined
    rather than deleted, so audit history is preserved without contaminating
    active recall.
    """

    LEGACY_DIRECT_WEB_SOURCE_TYPE = "authorized_direct_web_local_model_summary"
    GROUNDED_DIRECT_WEB_SOURCE_TYPE = "authorized_direct_web_local_model_summary_v2"
    RELEVANCE_VALIDATED_SOURCE_TYPES = frozenset({
        LEGACY_DIRECT_WEB_SOURCE_TYPE,
        GROUNDED_DIRECT_WEB_SOURCE_TYPE,
    })
    _FRESHNESS_LEARNING_MARKERS = (
        "versao", "versoes", "version", "versions", "release", "releases",
        "atual", "atuais", "mais recente", "mais recentes", "latest", "current",
        "newest", "preco", "preços", "price", "cotacao", "cotação", "noticias",
        "notícias", "news", "cve", "vulnerabilidade", "driver", "firmware",
    )

    def __init__(
        self,
        path: str | Path = "knowledge/autonomy/authorized_learning.jsonl",
    ):
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.quarantine_path = self.path.with_name(
            "authorized_learning_quarantine.jsonl"
        )
        self._lock = RLock()
        self.last_repair = self._repair_irrelevant_records()

    @staticmethod
    def _summary_matches_topic(topic: str, summary: str) -> bool:
        if not str(topic or "").strip() or not str(summary or "").strip():
            return False
        try:
            from jarvis_core.services.local_research import LocalResearchEngine
            return bool(
                LocalResearchEngine._relevance_details(
                    str(topic),
                    str(summary),
                )["ok"]
            )
        except Exception:
            # Fail closed for active direct-web learning if the deterministic
            # relevance helper itself cannot be loaded.
            return False

    @classmethod
    def _row_requires_relevance_validation(cls, row: dict[str, Any]) -> bool:
        return str(row.get("source_type") or "") in cls.RELEVANCE_VALIDATED_SOURCE_TYPES

    @classmethod
    def _row_is_legacy_freshness_learning(cls, row: dict[str, Any]) -> bool:
        if str(row.get("source_type") or "") != cls.LEGACY_DIRECT_WEB_SOURCE_TYPE:
            return False
        normalized = _norm(" ".join((
            str(row.get("topic") or ""),
            str(row.get("query") or ""),
        )))
        return any(marker in normalized for marker in cls._FRESHNESS_LEARNING_MARKERS)

    def _read_raw_rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        output: list[dict[str, Any]] = []
        for line in self.path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                output.append(row)
        return output

    def _repair_irrelevant_records(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"ok": True, "quarantined": 0}

        with self._lock:
            rows = self._read_raw_rows()
            keep: list[dict[str, Any]] = []
            quarantine: list[dict[str, Any]] = []
            for row in rows:
                quarantine_reason = None
                if self._row_is_legacy_freshness_learning(row):
                    # 0.27.8 v6 and earlier could store a time-sensitive direct-URL
                    # synthesis that was topically relevant but factually stale.
                    # Preserve it for audit, but never feed it back into active RAG.
                    quarantine_reason = "legacy_freshness_learning_unverified"
                elif (
                    self._row_requires_relevance_validation(row)
                    and not self._summary_matches_topic(
                        str(row.get("topic") or ""),
                        str(row.get("summary") or ""),
                    )
                ):
                    quarantine_reason = "topic_summary_mismatch"

                if quarantine_reason:
                    quarantine.append({
                        "quarantined_at": _iso(),
                        "quarantine_reason": quarantine_reason,
                        "original": row,
                    })
                else:
                    keep.append(row)

            if not quarantine:
                return {"ok": True, "quarantined": 0}

            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            try:
                with tmp.open("w", encoding="utf-8") as stream:
                    for row in keep:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                with self.quarantine_path.open("a", encoding="utf-8") as stream:
                    for row in quarantine:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                tmp.replace(self.path)
            except Exception as exc:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
                return {
                    "ok": False,
                    "quarantined": 0,
                    "error": type(exc).__name__,
                }

            return {
                "ok": True,
                "quarantined": len(quarantine),
                "quarantine_path": str(self.quarantine_path),
            }

    def add(
        self,
        *,
        topic: str,
        query: str,
        summary: str,
        model: str | None,
        authorization_token: str,
        sources: list[dict[str, Any]] | None = None,
        source_type: str = "authorized_web_research_model_summary",
    ) -> dict[str, Any]:
        normalized_source_type = str(source_type or "authorized_web_research_model_summary")[:120]
        normalized_summary = _norm(summary)
        insufficient_markers = (
            "evidencia insuficiente", "conteudo insuficiente", "informacao insuficiente",
            "nao ha conteudo factual suficiente", "nao contem conteudo factual suficiente",
            "nao foi possivel extrair conteudo", "a iniciar a aplicacao",
        )
        if str(summary or "").count("```") % 2:
            return {
                "ok": False, "stored": False, "topic": str(topic or "")[:300],
                "error": "LEARNING_TRUNCATED", "reason_code": "TRUNCATED",
                "message": "A síntese terminou com um bloco incompleto; a aprendizagem não foi guardada.",
            }
        if (
            normalized_source_type in self.RELEVANCE_VALIDATED_SOURCE_TYPES
            and not self._summary_matches_topic(topic, summary)
        ):
            return {
                "ok": False,
                "stored": False,
                "topic": str(topic or "")[:300],
                "error": "LEARNING_TOPIC_MISMATCH",
                "message": (
                    "A síntese não corresponde ao tópico autorizado; "
                    "o conhecimento não foi guardado."
                ),
            }

        if normalized_source_type in self.RELEVANCE_VALIDATED_SOURCE_TYPES and (
            len(str(summary or "").strip()) < 30
            or any(marker in normalized_summary for marker in insufficient_markers)
        ):
            return {
                "ok": False, "stored": False, "topic": str(topic or "")[:300],
                "error": "LEARNING_INSUFFICIENT_EVIDENCE",
                "reason_code": "INSUFFICIENT_EVIDENCE",
                "message": "A fonte não forneceu conteúdo substantivo suficiente; a aprendizagem não foi guardada.",
            }

        learned_at = _iso()
        try:
            from jarvis_core.services.learning_gap import deterministic_confidence_from_sources
            confidence = deterministic_confidence_from_sources(sources)
        except Exception:
            confidence = 0.55

        normalized_sources = [
            {
                "title": str(item.get("title") or "")[:300],
                "url": str(item.get("url") or "")[:1000],
                "canonical_url": canonicalize_public_url(str(item.get("url") or "")),
                "source_id": sha256(canonicalize_public_url(str(item.get("url") or "")).encode("utf-8")).hexdigest() if item.get("url") else "",
                "provider": str(item.get("provider") or "")[:80],
            }
            for item in (sources or [])[:12]
            if isinstance(item, dict)
        ]
        source_identity = str((normalized_sources[0] if normalized_sources else {}).get("source_id") or "")

        row = {
            "timestamp": learned_at,
            "learned_at": learned_at,
            "topic": str(topic or "")[
                :300
            ],
            "query": str(query or "")[
                :1000
            ],
            "summary": str(summary or "")[
                :12000
            ],
            "model": model,
            "authorization_token": str(
                authorization_token or ""
            )[:16],
            "source_type": normalized_source_type,
            "grounding_schema": (
                "source_claim_v2"
                if normalized_source_type == self.GROUNDED_DIRECT_WEB_SOURCE_TYPE
                else "legacy_or_unverified"
            ),
            "sources": normalized_sources,
            "source_identity": source_identity,
            "authority": (
                "explicit_owner_authorization"
            ),
            # Backward-compatible legacy field.  Its semantics are source
            # diversity/provenance, NOT probability that a learned claim is true.
            "confidence": round(float(confidence), 3),
            "source_confidence": round(float(confidence), 3),
            "confidence_semantics": "source_diversity_score",
            "claim_confidence": None,
            "claim_confidence_semantics": "not_computed",
            "source_count": len([
                item for item in (sources or []) if isinstance(item, dict)
            ]),
            "topic_validation": (
                "deterministic_relevance_pass"
                if normalized_source_type in self.RELEVANCE_VALIDATED_SOURCE_TYPES
                else "source_type_not_relevance_gated"
            ),
        }

        with self._lock:
            if source_identity:
                for existing in self._read_raw_rows():
                    if (
                        str(existing.get("source_identity") or "") == source_identity
                        and _norm(str(existing.get("topic") or "")) == _norm(str(topic or ""))
                    ):
                        return {
                            "ok": True, "stored": True, "duplicate": True,
                            "topic": str(existing.get("topic") or topic)[:300],
                            "path": str(self.path),
                            "reason_code": "ALREADY_STORED",
                        }
            with self.path.open(
                "a",
                encoding="utf-8",
            ) as stream:
                stream.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return {
            "ok": True,
            "stored": True,
            "topic": row["topic"],
            "path": str(self.path),
        }

    @staticmethod
    def _with_confidence_semantics(row: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(row)
        if "confidence" in enriched and "source_confidence" not in enriched:
            enriched["source_confidence"] = enriched.get("confidence")
        if "confidence" in enriched and "confidence_semantics" not in enriched:
            enriched["confidence_semantics"] = "source_diversity_score"
        enriched.setdefault("claim_confidence", None)
        enriched.setdefault("claim_confidence_semantics", "not_computed")
        return enriched

    def rows(
        self,
    ) -> list[dict[str, Any]]:
        # Defense in depth: even if an on-disk repair could not rewrite the
        # journal, a mismatched direct-web summary is excluded from active
        # retrieval. The original row remains available in the file/audit path.
        output: list[dict[str, Any]] = []
        for row in self._read_raw_rows():
            if self._row_is_legacy_freshness_learning(row):
                continue
            if (
                self._row_requires_relevance_validation(row)
                and not self._summary_matches_topic(
                    str(row.get("topic") or ""),
                    str(row.get("summary") or ""),
                )
            ):
                continue
            output.append(self._with_confidence_semantics(row))
        return output

    def search(
        self,
        query: str,
        limit: int = 8,
    ) -> dict[str, Any]:
        terms = _learning_terms(query)
        bounded_limit = max(1, min(int(limit), 30))
        active_rows = self.rows()

        # Generic questions such as "o que aprendeste?" contain no topical
        # terms after stopword removal.  Return the most recent verified
        # learning records rather than giving the model an empty context that
        # it might fill from pretraining and mislabel as newly learned.
        if not terms:
            recent = sorted(
                active_rows,
                key=lambda row: str(row.get("learned_at") or row.get("timestamp") or ""),
                reverse=True,
            )[:bounded_limit]
            return {
                "ok": True,
                "query": query,
                "results": recent,
                "count": len(recent),
                "source_type": "authorized_external_research_summary",
                "mode": "recent_verified_learning",
            }

        scored = []
        for row in active_rows:
            source_text = " ".join(
                str(item.get("title") or "") + " " + str(item.get("url") or "")
                for item in list(row.get("sources") or [])
                if isinstance(item, dict)
            )
            full_text = " ".join([
                str(row.get("topic") or ""),
                str(row.get("query") or ""),
                str(row.get("summary") or ""),
                source_text,
            ])
            haystack_terms = _learning_terms(full_text)
            topic_terms = _learning_terms(str(row.get("topic") or ""))
            central_terms = _learning_terms(" ".join([
                str(row.get("topic") or ""),
                str(row.get("query") or ""),
                source_text,
            ]))
            matched_terms = terms.intersection(haystack_terms)
            topic_matches = terms.intersection(topic_terms)
            central_matches = terms.intersection(central_terms)
            coverage = len(matched_terms) / max(1, len(terms))
            # A single incidental word in a long summary is not verified-topic
            # evidence. Require a central match, or strong multi-term coverage.
            if not central_matches and (len(terms) <= 2 or coverage < 0.67):
                continue
            score = len(matched_terms) + (4 * len(central_matches)) + (8 * len(topic_matches))
            if score:
                enriched = dict(row)
                enriched["retrieval_match"] = {
                    "mode": "topic_weighted_terms",
                    "score": score,
                    "coverage": round(coverage, 3),
                    "matched_terms": sorted(matched_terms),
                    "central_terms": sorted(central_matches),
                    "topic_terms": sorted(topic_matches),
                    "query_terms": sorted(terms),
                    "literal_query_match": _norm(str(query or "")) in _norm(full_text),
                }
                scored.append(
                    (
                        score,
                        row.get("timestamp") or "",
                        enriched,
                    )
                )

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        rows = [
            item[2]
            for item in scored[:bounded_limit]
        ]
        return {
            "ok": True,
            "query": query,
            "results": rows,
            "count": len(rows),
            "source_type": "authorized_external_research_summary",
        }

    def quarantine_rows(
        self,
        query: str = "",
        limit: int = 30,
    ) -> dict[str, Any]:
        """Read quarantined learning records with their recorded reasons.

        Quarantine is an audit/read path only.  Entries returned here are never
        reintroduced into active RAG by this function.
        """
        rows: list[dict[str, Any]] = []
        if self.quarantine_path.exists():
            for line in self.quarantine_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)

        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            original = item.get("original") if isinstance(item.get("original"), dict) else {}
            item["original"] = self._with_confidence_semantics(original)
            normalized_rows.append(item)
        rows = normalized_rows

        wanted = _learning_terms(query)
        if wanted:
            filtered: list[dict[str, Any]] = []
            for row in rows:
                original = row.get("original") if isinstance(row.get("original"), dict) else {}
                source_text = " ".join(
                    str(item.get("url") or "") + " " + str(item.get("title") or "")
                    for item in list(original.get("sources") or [])
                    if isinstance(item, dict)
                )
                haystack = _learning_terms(
                    " ".join([
                        str(row.get("quarantine_reason") or ""),
                        str(original.get("topic") or ""),
                        str(original.get("query") or ""),
                        str(original.get("summary") or ""),
                        source_text,
                    ])
                )
                if wanted.intersection(haystack):
                    filtered.append(row)
            rows = filtered

        bounded = max(1, min(int(limit), 100))
        rows = sorted(
            rows,
            key=lambda row: str(row.get("quarantined_at") or ""),
            reverse=True,
        )[:bounded]
        return {
            "ok": True,
            "query": str(query or ""),
            "results": rows,
            "count": len(rows),
            "quarantine_path": str(self.quarantine_path),
            "active_rag": False,
        }

    def status(
        self,
    ) -> dict[str, Any]:
        rows = self.rows()
        quarantine_entries = 0
        if self.quarantine_path.exists():
            quarantine_entries = sum(
                1
                for line in self.quarantine_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).splitlines()
                if line.strip()
            )
        return {
            "ok": True,
            "entries": len(rows),
            "path": str(self.path),
            "quarantined_entries": quarantine_entries,
            "quarantine_path": str(self.quarantine_path),
            "last_repair": dict(self.last_repair),
            "source_type": "authorized_external_research_summary",
        }


_GUARDIAN: AutonomyGuardian | None = None
_LEARNING: AuthorizedLearningStore | None = None


def set_autonomy_guardian(
    guardian: AutonomyGuardian,
) -> None:
    global _GUARDIAN
    _GUARDIAN = guardian


def autonomy_guardian() -> AutonomyGuardian:
    if _GUARDIAN is None:
        raise RuntimeError(
            "Autonomy Guardian not initialized"
        )
    return _GUARDIAN


def authorized_learning() -> AuthorizedLearningStore:
    global _LEARNING
    if _LEARNING is None:
        _LEARNING = AuthorizedLearningStore()
    return _LEARNING


def get_autonomy_status() -> dict[str, Any]:
    return autonomy_guardian().status()


def get_autonomy_pending() -> dict[str, Any]:
    return {
        "ok": True,
        "pending": autonomy_guardian().pending(),
    }


def search_authorized_learning(
    query: str,
    limit: int = 8,
) -> dict[str, Any]:
    return authorized_learning().search(
        query,
        limit=limit,
    )


def get_authorized_learning_status() -> dict[str, Any]:
    return authorized_learning().status()


def list_quarantined_learning(
    query: str = "",
    limit: int = 30,
) -> dict[str, Any]:
    return authorized_learning().quarantine_rows(query=query, limit=limit)
