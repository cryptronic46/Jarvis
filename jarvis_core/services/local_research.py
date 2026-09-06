from __future__ import annotations

from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from ipaddress import ip_address
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPHandler, HTTPSHandler, ProxyHandler
from urllib.error import HTTPError, URLError
from io import BytesIO
import json
import re
import socket
import http.client
import unicodedata
import xml.etree.ElementTree as ET

from jarvis_core import __version__
from jarvis_core.services.privacy import privacy_state


@dataclass(slots=True)
class ResearchSource:
    title: str
    url: str
    snippet: str = ""
    text: str = ""
    provider: str = ""

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("text", None)
        return data


@dataclass(slots=True)
class ResearchAnswer:
    ok: bool
    text: str
    elapsed_ms: int
    query: str
    model: str | None = None
    sources: list[dict[str, Any]] | None = None
    error: str | None = None
    message: str | None = None
    reason_code: str | None = None


class LocalResearchFetchError(RuntimeError):
    """Expected fetch/parser failure with a stable machine-readable code."""

    def __init__(self, reason_code: str, message: str = ""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


STANDARD_FETCH_HARD_LIMIT_BYTES = 8_000_000
JSON_FETCH_LIMIT_BYTES = 5_000_000


def _media_type(value: str) -> str:
    return str(value or "").split(";", 1)[0].strip().casefold()


def _is_json_media_type(value: str) -> bool:
    media_type = _media_type(value)
    return media_type in {"application/json", "text/json"} or media_type.endswith("+json")


def _routes_as_json(content_type: str, final_url: str) -> bool:
    if _is_json_media_type(content_type):
        return True
    return (
        _media_type(content_type) in {"", "application/octet-stream", "binary/octet-stream", "text/plain"}
        and urlparse(final_url).path.casefold().endswith(".json")
    )


def _cisa_kev_evidence(payload: dict[str, Any], max_chars: int) -> str | None:
    vulnerabilities = payload.get("vulnerabilities")
    if not isinstance(vulnerabilities, list):
        return None
    header = {
        key: payload.get(key)
        for key in ("title", "catalogVersion", "dateReleased", "count")
        if payload.get(key) is not None
    }
    lines = [json.dumps(header, ensure_ascii=False, separators=(",", ":"))]
    fields = (
        "cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded",
        "shortDescription", "requiredAction", "dueDate",
        "knownRansomwareCampaignUse", "forensicTriage", "notes", "cwes",
    )
    for item in vulnerabilities:
        if not isinstance(item, dict):
            continue
        bounded: dict[str, Any] = {}
        for key in fields:
            value = item.get(key)
            if value is None:
                continue
            if isinstance(value, list):
                bounded[key] = [str(entry)[:500] for entry in value[:32]]
            else:
                bounded[key] = str(value)[:4000]
        row = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        if sum(len(line) + 1 for line in lines) + len(row) > max_chars:
            break
        lines.append(row)
    return "\n".join(lines)[:max_chars]


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._chunks: list[str] = []
        self.title = ""
        self._in_title = False
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip += 1
        if tag == "title" and self._skip == 0:
            self._in_title = True
        if tag == "a" and self._skip == 0:
            href = str(dict(attrs).get("href") or "").strip()
            if href:
                self.links.append(href[:2000])
        if tag in {"p", "div", "article", "section", "li", "br", "h1", "h2", "h3", "h4"} and self._skip == 0:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg", "canvas"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._in_title:
            self.title = (self.title + " " + clean).strip()
        self._chunks.append(clean)

    def text(self, max_chars: int) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\s*\n\s*", "\n", raw)
        return raw.strip()[:max_chars]


class _SearchHTML(HTMLParser):
    """Minimal parser for DuckDuckGo HTML results."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        cls = str(values.get("class") or "")
        href = str(values.get("href") or "")
        if "result__a" in cls and href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        title = re.sub(r"\s+", " ", " ".join(self._text)).strip()
        if title:
            self.results.append((title, self._href))
        self._href = None
        self._text = []


class _SafeRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator):
        super().__init__()
        self._validator = validator

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        self._validator(target)
        return super().redirect_request(req, fp, code, msg, headers, target)



def _pinned_connection_factory(
    connection_class,
    resolved_ips,
):
    pinned_ips = tuple(
        str(value).strip()
        for value in resolved_ips
        if str(value).strip()
    )

    if not pinned_ips:
        raise ValueError(
            "NO_VALIDATED_PUBLIC_ADDRESS"
        )

    def factory(
        host,
        timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
        **kwargs,
    ):
        connection = connection_class(
            host,
            timeout=timeout,
            **kwargs,
        )

        def create_connection(
            address,
            connection_timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
            source_address=None,
        ):
            port = int(
                address[1]
            )

            last_error = None

            for pinned_ip in pinned_ips:
                try:
                    return socket.create_connection(
                        (
                            pinned_ip,
                            port,
                        ),
                        connection_timeout,
                        source_address,
                    )
                except OSError as exc:
                    last_error = exc

            if last_error is not None:
                raise last_error

            raise OSError(
                "NO_VALIDATED_PUBLIC_ADDRESS"
            )

        connection._create_connection = (
            create_connection
        )

        connection._jarvis_pinned_ips = (
            pinned_ips
        )

        return connection

    return factory


class _PinnedHTTPHandler(
    HTTPHandler
):
    def __init__(
        self,
        resolver,
    ):
        super().__init__()
        self._resolver = resolver

    def http_open(
        self,
        req,
    ):
        _, resolved_ips = (
            self._resolver(
                req.full_url
            )
        )

        return self.do_open(
            _pinned_connection_factory(
                http.client.HTTPConnection,
                resolved_ips,
            ),
            req,
        )


class _PinnedHTTPSHandler(
    HTTPSHandler
):
    def __init__(
        self,
        resolver,
    ):
        super().__init__()
        self._resolver = resolver

    def https_open(
        self,
        req,
    ):
        _, resolved_ips = (
            self._resolver(
                req.full_url
            )
        )

        return self.do_open(
            _pinned_connection_factory(
                http.client.HTTPSConnection,
                resolved_ips,
            ),
            req,
            context=self._context,
        )


class LocalResearchEngine:
    """
    Direct web retrieval + JARVIS-owned native local synthesis.

    No external AI provider is contacted. Search/fetch traffic is ordinary HTTPS.
    Retrieved pages are treated as untrusted data and are never executed.

    Every research session is relevance-gated twice: first at search-result level,
    then again after the page body is fetched. Unrelated pages must never reach
    local synthesis or owner-authorized learning storage.
    """

    SEARCH_PROVIDERS = ("bing_rss", "duckduckgo_html", "wikipedia")

    _RELEVANCE_STOPWORDS = frozenset({
        "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e",
        "em", "mais", "na", "nas", "no", "nos", "o", "os", "para", "por",
        "que", "se", "sobre", "um", "uma", "uns", "umas",
        "aprende", "aprender", "aprenderes", "aprendas", "aprendeste", "aprendizagem",
        "internet", "jarvis", "pesquisa", "pesquisar", "quero", "sabes", "saber",
        "usa", "usar", "utiliza", "utilizar",
        "qual", "quais", "diz", "explica", "resume", "resumidamente",
        "versao", "versoes", "atual", "recente", "latest", "current", "version",
        "about", "and", "learn", "more", "of", "on", "research", "the", "to", "web",
        "site", "oficial", "official", "pagina", "page", "stable", "release", "releases",
    })

    _CANONICAL_PHRASES = (
        (r"\bcyber[\s_-]*security\b", "ciberseguranca"),
        (r"\bciber[\s_-]*security\b", "ciberseguranca"),
        (r"\bcyber[\s_-]*seguranca\b", "ciberseguranca"),
        (r"\bciber[\s_-]*seguranca\b", "ciberseguranca"),
        (r"\bseguranca[\s_-]+informatica\b", "ciberseguranca"),
        (r"\bseguranca[\s_-]+digital\b", "ciberseguranca"),
        (r"\bseguranca[\s_-]+(?:da[\s_-]+)?informacao\b", "ciberseguranca"),
        (r"\bseguranca[\s_-]+(?:de[\s_-]+)?redes?\b", "ciberseguranca"),
        (r"\binformation[\s_-]+security\b", "ciberseguranca"),
        (r"\bcomputer[\s_-]+security\b", "ciberseguranca"),
        (r"\bnetwork[\s_-]+security\b", "ciberseguranca"),
        (r"\bdigital[\s_-]+security\b", "ciberseguranca"),
    )

    def __init__(self, settings, events, local_brain):
        self.settings = settings
        self.events = events
        self.local = local_brain

    def available(self) -> bool:
        return bool(
            getattr(self.settings, "local_research_enabled", True)
            and not privacy_state().enabled
        )

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "enabled": bool(getattr(self.settings, "local_research_enabled", True)),
            "available": self.available(),
            "privacy_mode": privacy_state().enabled,
            "external_ai": False,
            "synthesis_model": getattr(self.settings, "model", None),
            "search_providers": list(self.SEARCH_PROVIDERS),
            "network": "direct_https_only",
            "downloads_executed": False,
            "direct_url_same_site_only": True,
            "direct_url_max_depth": 1,
            "direct_url_max_pages": max(1, min(int(getattr(self.settings, "local_research_direct_max_pages", 4)), 8)),
        }

    @classmethod
    def _normalize_relevance_text(cls, value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        text = text.lower()
        for pattern, replacement in cls._CANONICAL_PHRASES:
            text = re.sub(pattern, replacement, text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _relevance_terms(cls, value: str) -> tuple[str, ...]:
        normalized = cls._normalize_relevance_text(value)
        terms: list[str] = []
        seen: set[str] = set()
        for token in normalized.split():
            if len(token) < 3 or token in cls._RELEVANCE_STOPWORDS or token in seen:
                continue
            seen.add(token)
            terms.append(token)
        return tuple(terms)

    @classmethod
    def _relevance_details(cls, subject: str, candidate: str) -> dict[str, Any]:
        terms = cls._relevance_terms(subject)
        normalized_candidate = cls._normalize_relevance_text(candidate)
        candidate_tokens = set(normalized_candidate.split())
        if not terms:
            return {
                "ok": False,
                "coverage": 0.0,
                "matched": [],
                "required": 0,
                "terms": [],
            }

        matched = [term for term in terms if term in candidate_tokens]
        count = len(matched)
        if len(terms) == 1:
            required = 1
        elif len(terms) <= 3:
            required = 2
        else:
            required = max(2, (len(terms) + 1) // 2)
        required = min(required, len(terms))
        coverage = count / len(terms)
        return {
            "ok": count >= required,
            "coverage": round(coverage, 3),
            "matched": matched,
            "required": required,
            "terms": list(terms),
        }

    _FRESHNESS_MARKERS = (
        "atual", "atuais", "mais recente", "mais recentes", "recente", "recentes",
        "latest", "current", "newest", "versao", "versoes", "version", "versions",
        "release", "releases",
    )
    _PRERELEASE_MARKERS = (
        "pre-release", "prerelease", "pre release", "alpha", "beta", "preview",
        "release candidate", "rc",
    )
    _UNSUPPORTED_SOURCE_CLAIM_MARKERS = (
        "com base em informacoes externas",
        "com base em fontes externas",
        "fontes externas confiaveis",
        "informacoes externas confiaveis",
        "segundo fontes externas",
        "according to external sources",
        "based on external sources",
    )
    _VERSION_RE = re.compile(
        r"(?<![A-Za-z0-9])v?(\d+\.\d+(?:\.\d+)?(?:[-_.]?(?:a|alpha|b|beta|rc|pre|preview)\d*)?)(?![A-Za-z0-9])",
        re.IGNORECASE,
    )

    @classmethod
    def _query_requests_learning(cls, query: str) -> bool:
        normalized = cls._normalize_relevance_text(query)
        return any(token in normalized.split() for token in ("aprende", "aprender", "aprendas", "estuda", "estudar", "estudes"))

    @classmethod
    def _freshness_sensitive(cls, query: str, topic: str = "") -> bool:
        normalized = cls._normalize_relevance_text(f"{query} {topic}")
        return any(marker in normalized for marker in cls._FRESHNESS_MARKERS)

    @classmethod
    def _version_query(cls, query: str, topic: str = "") -> bool:
        normalized = cls._normalize_relevance_text(f"{query} {topic}")
        has_version = any(marker in normalized for marker in ("versao", "versoes", "version", "versions", "release", "releases"))
        has_freshness = any(marker in normalized for marker in ("atual", "mais recente", "recente", "latest", "current", "newest"))
        return has_version and has_freshness

    @classmethod
    def _topic_terms_for_evidence(cls, topic: str) -> tuple[str, ...]:
        # Reuse the relevance vocabulary but keep only discriminative terms.
        return cls._relevance_terms(topic)

    @classmethod
    def _version_candidates_from_sources(
        cls,
        query: str,
        topic: str,
        sources: list[ResearchSource] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Derive a deterministic stable-version hint from collected source text.

        This does not use model knowledge. It only ranks version strings literally
        present near the requested topic in the fetched evidence. For a generic
        "current/latest version" question, prerelease-labelled candidates are
        excluded unless the OWNER explicitly asks for a prerelease.
        """
        if not cls._version_query(query, topic):
            return {"applicable": False, "candidate": None, "candidates": []}

        normalized_query = cls._normalize_relevance_text(query)
        wants_prerelease = any(marker in normalized_query for marker in cls._PRERELEASE_MARKERS)
        topic_terms = cls._topic_terms_for_evidence(topic)
        candidates: list[tuple[tuple[int, int, int], str, int, str]] = []

        for source_index, source in enumerate(sources, start=1):
            if isinstance(source, dict):
                body = str(source.get("text") or "")
                title = str(source.get("title") or "")
                url = str(source.get("url") or "")
            else:
                body = str(source.text or "")
                title = str(source.title or "")
                url = str(source.url or "")
            combined_meta = cls._normalize_relevance_text(f"{title} {url}")
            normalized_body = cls._normalize_relevance_text(body)

            for match in cls._VERSION_RE.finditer(body):
                literal = match.group(1)
                numeric = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", literal, re.IGNORECASE)
                if not numeric:
                    continue
                major, minor = int(numeric.group(1)), int(numeric.group(2))
                patch = int(numeric.group(3) or -1)
                start = max(0, match.start() - 180)
                end = min(len(body), match.end() + 180)
                context = cls._normalize_relevance_text(body[start:end])

                # Require topical evidence either in the nearby context or in
                # source metadata. This avoids picking unrelated dependency versions.
                if topic_terms and not any(term in context or term in combined_meta for term in topic_terms):
                    continue

                literal_norm = literal.lower()
                prerelease = bool(re.search(r"(?:a|alpha|b|beta|rc|pre|preview)", literal_norm))
                if not prerelease:
                    # Only treat a prose prerelease label as belonging to this
                    # specific version when it is immediately adjacent. A broad
                    # context window may contain a different prerelease row and
                    # must not poison neighbouring stable releases.
                    adjacent = cls._normalize_relevance_text(
                        body[max(0, match.start() - 18):min(len(body), match.end() + 42)]
                    )
                    prerelease = any(marker in adjacent for marker in cls._PRERELEASE_MARKERS)
                if prerelease and not wants_prerelease:
                    continue

                # Prefer exact x.y.z releases over branch labels x.y. A two-part
                # version remains a fallback when the source exposes no exact release.
                exactness = 1 if numeric.group(3) is not None else 0
                candidates.append(((major, minor, patch), literal, exactness, f"S{source_index}"))

        if not candidates:
            return {"applicable": True, "candidate": None, "candidates": []}

        exact = [item for item in candidates if item[2] == 1]
        pool = exact or candidates
        pool.sort(key=lambda item: item[0], reverse=True)
        best = pool[0]
        public = []
        seen = set()
        for numeric, literal, exactness, source_ref in pool[:12]:
            key = (literal.lower(), source_ref)
            if key in seen:
                continue
            seen.add(key)
            public.append({"version": literal, "source": source_ref, "exact": bool(exactness)})
        return {
            "applicable": True,
            "candidate": best[1],
            "source": best[3],
            "candidates": public,
        }

    @classmethod
    def _deterministic_research_fallback(
        cls,
        *,
        query: str,
        topic: str,
        sources: list[ResearchSource] | list[dict[str, Any]],
    ) -> str | None:
        """Return a narrow answer only when it can be derived without an LLM.

        This is intentionally limited to two high-confidence cases used by the
        public-web router: current-version questions and official-site lookup.
        It never fills gaps from model memory.
        """
        hint = cls._version_candidates_from_sources(query, topic, sources)
        if hint.get("applicable") and hint.get("candidate"):
            candidate = str(hint.get("candidate"))
            source_ref = str(hint.get("source") or "fonte recolhida")
            return f"A versão estável mais recente sustentada pelas fontes recolhidas é {candidate} ({source_ref})."

        normalized = cls._normalize_relevance_text(f"{query} {topic}")
        if "site oficial" in normalized or "official site" in normalized or "link oficial" in normalized:
            terms = [term for term in cls._relevance_terms(topic) if term not in {"site", "oficial", "official"}]
            for source in sources:
                if isinstance(source, dict):
                    url = str(source.get("url") or "")
                    title = str(source.get("title") or "")
                else:
                    url, title = str(source.url or ""), str(source.title or "")
                try:
                    parsed = urlparse(url)
                except Exception:
                    continue
                host = (parsed.hostname or "").lower().rstrip(".")
                haystack = cls._normalize_relevance_text(f"{host} {title}")
                if terms and not any(term in haystack for term in terms):
                    continue
                if parsed.scheme in {"http", "https"} and host:
                    return f"O site oficial encontrado nas fontes públicas é {parsed.scheme}://{host}/."
        return None

    @classmethod
    def _validate_synthesis_grounding(
        cls,
        synthesis: str,
        *,
        query: str,
        topic: str,
        sources: list[ResearchSource] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Fail closed when the local synthesis claims evidence it did not receive."""
        answer = str(synthesis or "").strip()
        if not answer:
            return {"ok": False, "reason": "EMPTY_SYNTHESIS"}

        normalized_answer = cls._normalize_relevance_text(answer)
        if any(marker in normalized_answer for marker in cls._UNSUPPORTED_SOURCE_CLAIM_MARKERS):
            return {"ok": False, "reason": "UNSUPPORTED_EXTERNAL_SOURCE_CLAIM"}

        source_texts: list[str] = []
        for source in sources:
            if isinstance(source, dict):
                source_texts.extend((
                    str(source.get("title") or ""),
                    str(source.get("url") or ""),
                    str(source.get("text") or ""),
                ))
            else:
                source_texts.extend((str(source.title or ""), str(source.url or ""), str(source.text or "")))
        evidence = "\n".join(source_texts)
        evidence_lower = evidence.lower()

        unsupported_versions = []
        for match in cls._VERSION_RE.finditer(answer):
            literal = match.group(1)
            if literal.lower() not in evidence_lower:
                unsupported_versions.append(literal)
        if unsupported_versions:
            return {
                "ok": False,
                "reason": "UNSUPPORTED_VERSION_CLAIM",
                "unsupported_versions": sorted(set(unsupported_versions)),
            }

        hint = cls._version_candidates_from_sources(query, topic, sources)
        candidate = str(hint.get("candidate") or "").strip()
        if hint.get("applicable") and candidate:
            if candidate.lower() not in answer.lower():
                return {
                    "ok": False,
                    "reason": "FRESHNESS_VERSION_MISMATCH",
                    "expected_source_candidate": candidate,
                    "candidate_source": hint.get("source"),
                }

        return {"ok": True, "version_hint": hint}

    @classmethod
    def _search_result_relevant(cls, subject: str, source: ResearchSource) -> bool:
        haystack = " ".join((source.title, source.snippet, source.url))
        return bool(cls._relevance_details(subject, haystack)["ok"])

    @classmethod
    def _fetched_source_relevant(cls, subject: str, source: ResearchSource) -> bool:
        # Search-discovered pages remain strictly relevance-gated because a
        # provider can return stale, poisoned or simply unrelated results.
        return bool(cls._relevance_details(subject, source.text)["ok"])

    @classmethod
    def _owner_selected_root_acceptable(
        cls,
        subject: str,
        source: ResearchSource,
        requested_url: str,
    ) -> bool:
        """Gate an OWNER-selected root URL without second-guessing the URL itself.

        For explicit direct-URL research the OWNER has already selected the root
        authority.  The old generic fetched-page gate could reject valid pages
        whose visible text uses a different language/wording (for example the
        Python downloads page for the Portuguese topic "versão atual do Python").

        We still require a public, successfully fetched, non-empty text page and
        keep redirects on the same host.  If normal relevance succeeds we accept
        immediately.  Otherwise the root is allowed into *local synthesis* only;
        the synthesis layer performs a second semantic relevance check and can
        return [[RESEARCH_RELEVANCE_REJECTED]], so unrelated content is not stored.
        Child pages and search-discovered pages remain under the strict lexical
        gate.
        """
        if not str(source.text or "").strip():
            return False
        try:
            requested = urlparse(requested_url)
            final = urlparse(source.url)
            if (requested.hostname or "").lower().rstrip(".") != (final.hostname or "").lower().rstrip("."):
                return False
        except Exception:
            return False

        if cls._fetched_source_relevant(subject, source):
            return True

        # The explicit root gets a bounded semantic second chance. Include the
        # title and URL because some pages keep the entity mainly in navigation
        # or metadata while the first text window is highly generic.
        candidate = " ".join((source.title, source.url, source.text))
        details = cls._relevance_details(subject, candidate)
        if details.get("matched"):
            return True

        # OWNER-selected root authority: let the local synthesizer decide rather
        # than rejecting before the model sees the requested page.
        return len(str(source.text or "").strip()) >= 80

    @staticmethod
    def _resolve_public_target(
        url: str,
    ) -> tuple[str, tuple[str, ...]]:
        parsed = urlparse(
            str(
                url
                or ""
            ).strip()
        )

        if parsed.scheme.lower() not in {
            "http",
            "https",
        }:
            raise ValueError(
                "UNSUPPORTED_URL_SCHEME"
            )

        if (
            parsed.username
            or parsed.password
        ):
            raise ValueError(
                "URL_CREDENTIALS_BLOCKED"
            )

        host = (
            parsed.hostname
            or ""
        ).strip().lower().rstrip(".")

        if (
            not host
            or host in {
                "localhost",
                "localhost.localdomain",
            }
        ):
            raise ValueError(
                "LOCAL_TARGET_BLOCKED"
            )

        port = (
            parsed.port
            or (
                443
                if parsed.scheme.lower()
                == "https"
                else 80
            )
        )

        try:
            infos = socket.getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise ValueError(
                "DNS_RESOLUTION_FAILED"
            ) from exc

        resolved = []

        for info in infos:
            address = (
                info[4][0]
                .split(
                    "%",
                    1,
                )[0]
            )

            ip = ip_address(
                address
            )

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise ValueError(
                    "PRIVATE_OR_LOCAL_TARGET_BLOCKED"
                )

            normalized = str(ip)

            if normalized not in resolved:
                resolved.append(
                    normalized
                )

        if not resolved:
            raise ValueError(
                "DNS_RESOLUTION_FAILED"
            )

        return (
            parsed.geturl(),
            tuple(resolved),
        )

    @staticmethod
    def _validate_public_url(
        url: str,
    ) -> str:
        safe, _ = (
            LocalResearchEngine
            ._resolve_public_target(
                url
            )
        )

        return safe

    def _get(self, url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, str, str]:
            safe = self._validate_public_url(url)
            opener = build_opener(
                ProxyHandler({}),
                _SafeRedirectHandler(
                    self._validate_public_url
                ),
                _PinnedHTTPHandler(
                    self._resolve_public_target
                ),
                _PinnedHTTPSHandler(
                    self._resolve_public_target
                ),
            )
            request = Request(
                safe,
                headers={
                    "User-Agent": f"JARVIS-Core/{__version__} (+local-research; no-external-ai)",
                    "Accept": "application/json,text/html,application/xhtml+xml,application/xml,text/plain;q=0.9,*/*;q=0.1",
                },
            )
            with opener.open(request, timeout=timeout) as response:
                content_type = _media_type(response.headers.get("Content-Type") or "")
                final_url = str(response.geturl() or safe)
                self._validate_public_url(final_url)
                standard_limit = max(
                    64_000,
                    min(int(max_bytes), STANDARD_FETCH_HARD_LIMIT_BYTES),
                )
                response_limit = (
                    max(standard_limit, JSON_FETCH_LIMIT_BYTES)
                    if _routes_as_json(content_type, final_url)
                    else standard_limit
                )
                length = response.headers.get("Content-Length")
                try:
                    declared_length = int(length) if length else None
                except (TypeError, ValueError):
                    declared_length = None
                if declared_length is not None and declared_length > response_limit:
                    raise LocalResearchFetchError(
                        "LOCAL_RESEARCH_RESPONSE_TOO_LARGE",
                        f"Tamanho declarado {declared_length} excede o limite {response_limit}",
                    )
                raw = response.read(response_limit + 1)
                if len(raw) > response_limit:
                    raise LocalResearchFetchError(
                        "LOCAL_RESEARCH_RESPONSE_TOO_LARGE",
                        f"A resposta excede o limite {response_limit}",
                    )
            return raw, content_type, final_url

    @staticmethod
    def _dedupe(results: list[ResearchSource], limit: int) -> list[ResearchSource]:
        output: list[ResearchSource] = []
        seen: set[str] = set()
        for item in results:
            key = item.url.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            output.append(item)
            if len(output) >= limit:
                break
        return output

    @staticmethod
    def _unwrap_duckduckgo(href: str) -> str:
        parsed = urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com"):
            target = parse_qs(parsed.query).get("uddg")
            if target:
                return unquote(target[0])
        return href

    def _search_bing_rss(self, query: str, limit: int) -> list[ResearchSource]:
        url = "https://www.bing.com/search?format=rss&q=" + quote_plus(query)
        raw, _, _ = self._get(
            url,
            max_bytes=int(getattr(self.settings, "local_research_search_max_bytes", 256000)),
            timeout=float(getattr(self.settings, "local_research_timeout_seconds", 8.0)),
        )
        root = ET.fromstring(raw.decode("utf-8", errors="replace"))
        rows: list[ResearchSource] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            snippet = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
            snippet = re.sub(r"\s+", " ", snippet).strip()
            if title and link:
                rows.append(ResearchSource(title=title, url=link, snippet=snippet, provider="bing_rss"))
            if len(rows) >= limit:
                break
        return rows

    def _search_duckduckgo(self, query: str, limit: int) -> list[ResearchSource]:
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        raw, content_type, _ = self._get(
            url,
            max_bytes=int(getattr(self.settings, "local_research_search_max_bytes", 256000)),
            timeout=float(getattr(self.settings, "local_research_timeout_seconds", 8.0)),
        )
        if "html" not in content_type and content_type:
            return []
        parser = _SearchHTML()
        parser.feed(raw.decode("utf-8", errors="replace"))
        rows: list[ResearchSource] = []
        for title, href in parser.results:
            target = self._unwrap_duckduckgo(href)
            try:
                self._validate_public_url(target)
            except ValueError:
                continue
            rows.append(ResearchSource(title=title, url=target, provider="duckduckgo_html"))
            if len(rows) >= limit:
                break
        return rows

    def _search_wikipedia(self, query: str, limit: int) -> list[ResearchSource]:
        params = (
            "action=query&list=search&format=json&utf8=1&srlimit="
            + str(max(1, min(limit, 10)))
            + "&srsearch="
            + quote_plus(query)
        )
        url = "https://pt.wikipedia.org/w/api.php?" + params
        raw, _, _ = self._get(
            url,
            max_bytes=int(getattr(self.settings, "local_research_search_max_bytes", 256000)),
            timeout=float(getattr(self.settings, "local_research_timeout_seconds", 8.0)),
        )
        data = json.loads(raw.decode("utf-8", errors="replace"))
        rows: list[ResearchSource] = []
        for item in ((data.get("query") or {}).get("search") or []):
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            snippet = re.sub(r"<[^>]+>", " ", str(item.get("snippet") or ""))
            snippet = re.sub(r"\s+", " ", snippet).strip()
            rows.append(
                ResearchSource(
                    title=title,
                    url="https://pt.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
                    snippet=snippet,
                    provider="wikipedia",
                )
            )
            if len(rows) >= limit:
                break
        return rows

    def search(self, query: str, limit: int | None = None) -> dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "PRIVACY_OR_RESEARCH_DISABLED", "results": []}
        limit = max(1, min(int(limit or getattr(self.settings, "local_research_max_results", 5)), 10))
        collected: list[ResearchSource] = []
        errors: list[str] = []
        rejected_irrelevant = 0
        raw_results = 0
        for provider in self.SEARCH_PROVIDERS:
            try:
                if provider == "bing_rss":
                    rows = self._search_bing_rss(query, limit)
                elif provider == "duckduckgo_html":
                    rows = self._search_duckduckgo(query, limit)
                else:
                    rows = self._search_wikipedia(query, limit)

                raw_results += len(rows)
                relevant_rows: list[ResearchSource] = []
                for row in rows:
                    if self._search_result_relevant(query, row):
                        relevant_rows.append(row)
                    else:
                        rejected_irrelevant += 1
                        self.events.emit(
                            "LOCAL_RESEARCH_SEARCH_RESULT_REJECTED",
                            query=query[:300],
                            provider=row.provider,
                            title=row.title[:300],
                            reason="topic_mismatch",
                        )

                collected.extend(relevant_rows)
                collected = self._dedupe(collected, limit)
                if len(collected) >= limit:
                    break
            except (HTTPError, URLError, TimeoutError, ValueError, ET.ParseError, json.JSONDecodeError, OSError) as exc:
                errors.append(f"{provider}:{type(exc).__name__}")
        return {
            "ok": bool(collected),
            "query": query,
            "results": [row.public_dict() for row in collected],
            "_objects": collected,
            "errors": errors,
            "raw_results": raw_results,
            "rejected_irrelevant": rejected_irrelevant,
            "error": None if collected else ("SEARCH_RESULTS_IRRELEVANT" if raw_results else "SEARCH_FAILED"),
        }

    def _fetch_with_links(
        self,
        source: ResearchSource,
        *,
        max_chars: int | None = None,
    ) -> tuple[ResearchSource, list[str]]:
        raw, content_type, final_url = self._get(
            source.url,
            max_bytes=int(getattr(self.settings, "local_research_fetch_max_bytes", 524288)),
            timeout=float(getattr(self.settings, "local_research_timeout_seconds", 8.0)),
        )
        json_route = _routes_as_json(content_type, final_url)
        allowed = ("text/", "application/xhtml+xml", "application/xml", "application/pdf")
        if content_type and not json_route and not content_type.startswith(allowed) and not final_url.casefold().endswith(".pdf"):
            raise LocalResearchFetchError("LOCAL_RESEARCH_CONTENT_TYPE_BLOCKED")
        links: list[str] = []
        char_limit = int(max_chars or getattr(self.settings, "local_research_source_max_chars", 5000))
        if "pdf" in content_type or final_url.casefold().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                chunks: list[str] = []
                total = 0
                for page in PdfReader(BytesIO(raw)).pages:
                    page_text = str(page.extract_text() or "").strip()
                    if page_text:
                        chunks.append(page_text)
                        total += len(page_text)
                    if total >= char_limit:
                        break
                text = "\n".join(chunks)[:char_limit]
                title = source.title
            except Exception as exc:
                raise LocalResearchFetchError(
                    "LOCAL_RESEARCH_PDF_INVALID",
                    f"Falha ao interpretar PDF: {type(exc).__name__}",
                ) from exc
        else:
            decoded = raw.decode("utf-8", errors="replace")
            if json_route:
                try:
                    payload = json.loads(decoded)
                    if not isinstance(payload, (dict, list)):
                        raise LocalResearchFetchError(
                            "LOCAL_RESEARCH_JSON_SCHEMA_INVALID",
                            "A raiz JSON não é um objeto nem uma lista",
                        )
                    cisa_text = (
                        _cisa_kev_evidence(payload, char_limit)
                        if isinstance(payload, dict)
                        else None
                    )
                    text = cisa_text or json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )[:char_limit]
                    title = (
                        str(payload.get("title") or source.title)
                        if isinstance(payload, dict)
                        else source.title
                    )
                except json.JSONDecodeError as exc:
                    raise LocalResearchFetchError(
                        "LOCAL_RESEARCH_JSON_INVALID",
                        "A resposta JSON está incompleta ou é inválida",
                    ) from exc
            elif "html" in content_type or "<html" in decoded[:500].lower():
                parser = _ReadableHTML()
                parser.feed(decoded)
                text = parser.text(char_limit)
                title = parser.title or source.title
                links = [urljoin(final_url, href) for href in parser.links]
            else:
                text = re.sub(r"\s+", " ", decoded).strip()[:char_limit]
                title = source.title
        return (
            ResearchSource(
                title=title[:300],
                url=final_url,
                snippet=source.snippet[:1000],
                text=text,
                provider=source.provider,
            ),
            links,
        )

    def fetch(self, source: ResearchSource) -> ResearchSource:
        item, _ = self._fetch_with_links(source)
        return item

    @staticmethod
    def _same_site_child_urls(root_url: str, links: list[str], limit: int) -> list[str]:
        root = urlparse(root_url)
        root_host = (root.hostname or "").lower().rstrip(".")
        root_path = root.path or "/"
        if not root_path.endswith("/"):
            root_path = root_path.rsplit("/", 1)[0] + "/"

        output: list[str] = []
        seen: set[str] = {root_url.split("#", 1)[0]}
        for raw in links:
            try:
                parsed = urlparse(raw)
            except Exception:
                continue
            if parsed.scheme.lower() not in {"http", "https"}:
                continue
            host = (parsed.hostname or "").lower().rstrip(".")
            if host != root_host:
                continue
            if not (parsed.path or "/").startswith(root_path):
                continue
            clean = parsed._replace(fragment="").geturl()
            if clean in seen:
                continue
            seen.add(clean)
            output.append(clean)
            if len(output) >= max(0, int(limit)):
                break
        return output

    def research_url(
        self,
        url: str,
        *,
        query: str,
        topic: str,
        deep: bool = True,
    ) -> ResearchAnswer:
        """Research one owner-selected public URL with a strictly bounded crawl.

        The supplied URL is the root authority target. At most a small number of
        same-host, same-path-prefix child pages are read at depth 1. No downloaded
        content is executed and no model tools are exposed during synthesis.
        """
        started = monotonic()
        if not self.available():
            return ResearchAnswer(
                ok=False,
                text="A pesquisa externa está desativada pelo modo de privacidade ou configuração local.",
                elapsed_ms=0,
                query=query,
                error="RESEARCH_UNAVAILABLE",
            )

        try:
            safe_root = self._validate_public_url(url)
        except ValueError as exc:
            return ResearchAnswer(
                ok=False,
                text="O endereço fornecido não passou a validação de destino público seguro.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error=str(exc) or "DIRECT_URL_BLOCKED",
            )

        max_pages = max(1, min(int(getattr(self.settings, "local_research_direct_max_pages", 4)), 8))
        per_page_chars = max(1500, min(int(getattr(self.settings, "local_research_direct_source_max_chars", 4500)), 7000))
        # The root selected by the OWNER gets a larger evidence window than child
        # pages. Long release/download pages often place the current release table
        # after navigation boilerplate; truncating the root at 4.5k can surface only
        # stale historical rows. The synthesis layer still enforces a total budget.
        root_page_chars = max(9000, min(per_page_chars * 3, 14000))
        fetched: list[ResearchSource] = []
        rejected = 0
        errors: list[str] = []

        try:
            root_source, links = self._fetch_with_links(
                ResearchSource(title=safe_root, url=safe_root, provider="direct_url"),
                max_chars=root_page_chars,
            )
        except Exception as exc:
            status = int(exc.code) if isinstance(exc, HTTPError) else None
            reason_code = (
                exc.reason_code
                if isinstance(exc, LocalResearchFetchError)
                else (f"HTTP_{status}" if status is not None else "DIRECT_URL_FETCH_FAILED")
            )
            return ResearchAnswer(
                ok=False,
                text=(
                    f"Não consegui ler a página autorizada: o servidor respondeu HTTP {status}."
                    if status is not None
                    else f"Não consegui ler a página autorizada em segurança (motivo: {reason_code})."
                ),
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="DIRECT_URL_FETCH_FAILED",
                message=(f"HTTP status={status}; retryable={status in {429, 500, 502, 503, 504}}" if status is not None else reason_code),
                reason_code=reason_code,
            )

        if not self._owner_selected_root_acceptable(topic, root_source, safe_root):
            return ResearchAnswer(
                ok=False,
                text="A página indicada não pôde ser validada como uma fonte pública legível para o tema pedido.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="DIRECT_URL_ROOT_REJECTED",
                sources=[root_source.public_dict()],
            )
        fetched.append(root_source)

        if deep and max_pages > 1:
            children = self._same_site_child_urls(root_source.url, links, max_pages - 1)
            for child_url in children:
                try:
                    self._validate_public_url(child_url)
                    item, _ = self._fetch_with_links(
                        ResearchSource(title=child_url, url=child_url, provider="direct_url_child"),
                        max_chars=per_page_chars,
                    )
                    if not item.text:
                        continue
                    if not self._fetched_source_relevant(topic, item):
                        rejected += 1
                        continue
                    fetched.append(item)
                except Exception as exc:
                    errors.append(type(exc).__name__)
                if len(fetched) >= max_pages:
                    break

        self.events.emit(
            "LOCAL_DIRECT_URL_SOURCES_READY",
            url=root_source.url[:1000],
            topic=topic[:300],
            sources=len(fetched),
            rejected=rejected,
            max_pages=max_pages,
        )

        try:
            version_hint = self._version_candidates_from_sources(query, topic, fetched)
            hint_text = ""
            if version_hint.get("applicable"):
                if version_hint.get("candidate"):
                    hint_text = (
                        "\n\nEVIDÊNCIA DETERMINÍSTICA EXTRAÍDA DAS FONTES: para este pedido de versão atual, "
                        f"o maior candidato estável exato suportado pelo texto recolhido é "
                        f"{version_hint.get('candidate')} ({version_hint.get('source')}). "
                        "Isto não é conhecimento interno: foi derivado literalmente das fontes acima. "
                        "Não substituas este candidato por uma versão que não esteja sustentada pelas fontes."
                    )
                else:
                    hint_text = (
                        "\n\nEVIDÊNCIA DETERMINÍSTICA: não foi possível extrair das fontes um candidato de versão "
                        "atual suficientemente suportado. Não adivinhes nem uses memória interna."
                    )
            synthesis = self.local.synthesize_research(
                query=(
                    query
                    + f"\n\nÂmbito de navegação: URL fornecido pelo proprietário e no máximo {max_pages} páginas "
                      "do mesmo site/caminho, profundidade 1. Não afirmes que estudaste páginas não recolhidas."
                    + hint_text
                ),
                topic=topic,
                sources=[asdict(item) for item in fetched],
                deep=deep,
                owner_selected_url=safe_root,
                relevance_preverified=self._fetched_source_relevant(topic, root_source),
            )
        except Exception as exc:
            fallback = self._deterministic_research_fallback(query=query, topic=topic, sources=fetched)
            if fallback:
                self.events.emit("LOCAL_RESEARCH_DETERMINISTIC_FALLBACK", reason=type(exc).__name__, topic=topic[:300])
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor",
                    sources=[source.public_dict() for source in fetched],
                    message=f"local_synthesis_failed={type(exc).__name__}; deterministic_grounded_fallback=true",
                )
            return ResearchAnswer(
                ok=False,
                text=f"Falha na síntese local da página indicada: {type(exc).__name__}.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="LOCAL_SYNTHESIS_FAILED",
                message=str(exc)[:500],
                sources=[source.public_dict() for source in fetched],
            )

        if "[[RESEARCH_RELEVANCE_REJECTED]]" in str(synthesis).upper():
            fallback = self._deterministic_research_fallback(query=query, topic=topic, sources=fetched)
            if fallback:
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor",
                    sources=[source.public_dict() for source in fetched],
                )
            return ResearchAnswer(
                ok=False,
                text=(
                    "A síntese local rejeitou o conteúdo por falta de correspondência com o tema pedido."
                    + (" A aprendizagem não foi guardada." if self._query_requests_learning(query) else "")
                ),
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="LOCAL_SYNTHESIS_RELEVANCE_REJECTED",
                sources=[source.public_dict() for source in fetched],
            )

        grounding = self._validate_synthesis_grounding(
            synthesis, query=query, topic=topic, sources=fetched
        )
        if not grounding.get("ok"):
            self.events.emit(
                "LOCAL_RESEARCH_SYNTHESIS_GROUNDING_REJECTED",
                query=query[:300],
                topic=topic[:300],
                reason=str(grounding.get("reason") or "UNKNOWN"),
            )
            fallback = self._deterministic_research_fallback(query=query, topic=topic, sources=fetched)
            if fallback:
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor",
                    sources=[source.public_dict() for source in fetched],
                )
            return ResearchAnswer(
                ok=False,
                text=(
                    "A síntese local incluiu uma afirmação que não ficou sustentada pelas fontes públicas "
                    "recolhidas; por isso não a apresento como verificada."
                ),
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error=str(grounding.get("reason") or "LOCAL_SYNTHESIS_UNGROUNDED"),
                message=json.dumps(grounding, ensure_ascii=False)[:800],
                sources=[source.public_dict() for source in fetched],
            )

        return ResearchAnswer(
            ok=True,
            text=synthesis,
            elapsed_ms=round((monotonic() - started) * 1000),
            query=query,
            model=getattr(self.settings, "model", None),
            sources=[source.public_dict() for source in fetched],
            message=f"direct_url_pages={len(fetched)}; rejected={rejected}; errors={len(errors)}",
        )

    def research(
        self,
        query: str,
        *,
        topic: str | None = None,
        deep: bool = False,
        search_query: str | None = None,
    ) -> ResearchAnswer:
        started = monotonic()
        if not self.available():
            return ResearchAnswer(
                ok=False,
                text="A pesquisa externa está desativada pelo modo de privacidade ou configuração local.",
                elapsed_ms=0,
                query=query,
                error="RESEARCH_UNAVAILABLE",
            )

        relevance_subject = str(topic or search_query or query).strip() or query
        search = self.search(search_query or query)
        objects = list(search.get("_objects") or [])
        if not objects:
            irrelevant = search.get("error") == "SEARCH_RESULTS_IRRELEVANT"
            return ResearchAnswer(
                ok=False,
                text=(
                    (
                        "Encontrei resultados públicos, mas rejeitei-os porque não correspondiam ao tema pedido. "
                        "A aprendizagem não foi executada."
                        if self._query_requests_learning(query)
                        else "Encontrei resultados públicos, mas rejeitei-os porque não correspondiam ao tema pedido."
                    )
                    if irrelevant
                    else "Não consegui obter resultados públicos para esta pesquisa."
                ),
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="SEARCH_RESULTS_IRRELEVANT" if irrelevant else "SEARCH_FAILED",
                message=", ".join(search.get("errors") or [])[:500],
            )

        fetched: list[ResearchSource] = []
        fetch_errors: list[str] = []
        rejected_irrelevant = 0
        for source in objects:
            try:
                item = self.fetch(source)
                if not item.text:
                    continue
                if not self._fetched_source_relevant(relevance_subject, item):
                    rejected_irrelevant += 1
                    self.events.emit(
                        "LOCAL_RESEARCH_FETCHED_SOURCE_REJECTED",
                        query=query[:300],
                        topic=relevance_subject[:300],
                        provider=item.provider,
                        title=item.title[:300],
                        url=item.url[:1000],
                        reason="topic_mismatch",
                    )
                    continue
                fetched.append(item)
            except Exception as exc:
                fetch_errors.append(f"{source.provider}:{type(exc).__name__}")
            if len(fetched) >= int(getattr(self.settings, "local_research_max_sources", 4)):
                break

        if not fetched:
            if rejected_irrelevant:
                return ResearchAnswer(
                    ok=False,
                    text=(
                        "Os resultados encontrados conduziram a páginas que não correspondiam ao tema pedido. "
                        + ("Rejeitei as fontes e não guardei qualquer aprendizagem." if self._query_requests_learning(query) else "Rejeitei essas fontes.")
                    ),
                    elapsed_ms=round((monotonic() - started) * 1000),
                    query=query,
                    error="FETCHED_SOURCES_IRRELEVANT",
                    message=f"rejected_irrelevant={rejected_irrelevant}; " + ", ".join(fetch_errors)[:400],
                    sources=[source.public_dict() for source in objects],
                )
            return ResearchAnswer(
                ok=False,
                text="Encontrei resultados, mas não consegui ler nenhuma fonte pública em segurança.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="FETCH_FAILED",
                message=", ".join(fetch_errors)[:500],
                sources=[source.public_dict() for source in objects],
            )

        self.events.emit(
            "LOCAL_RESEARCH_SOURCES_READY",
            query=query[:300],
            topic=relevance_subject[:300],
            sources=len(fetched),
            irrelevant_rejected=rejected_irrelevant,
        )
        synthesis_topic = str(topic or query)
        version_hint = self._version_candidates_from_sources(query, synthesis_topic, fetched)
        hint_text = ""
        if version_hint.get("applicable"):
            if version_hint.get("candidate"):
                hint_text = (
                    "\n\nEVIDÊNCIA DETERMINÍSTICA EXTRAÍDA DAS FONTES: o maior candidato estável exato "
                    f"suportado pelo texto recolhido é {version_hint.get('candidate')} ({version_hint.get('source')}). "
                    "Não uses uma versão que não esteja nas fontes."
                )
            else:
                hint_text = "\n\nEVIDÊNCIA DETERMINÍSTICA: não foi extraída uma versão atual segura; não adivinhes."
        try:
            synthesis = self.local.synthesize_research(
                query=query + hint_text,
                topic=synthesis_topic,
                sources=[asdict(item) for item in fetched],
                deep=deep,
            )
        except Exception as exc:
            fallback = self._deterministic_research_fallback(query=query, topic=synthesis_topic, sources=fetched)
            if fallback:
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor",
                    sources=[source.public_dict() for source in fetched],
                    message=f"local_synthesis_failed={type(exc).__name__}; deterministic_grounded_fallback=true",
                )
            return ResearchAnswer(
                ok=False,
                text=f"Falha na síntese local da pesquisa: {type(exc).__name__}.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="LOCAL_SYNTHESIS_FAILED",
                message=str(exc)[:500],
                sources=[source.public_dict() for source in fetched],
            )

        if "[[RESEARCH_RELEVANCE_REJECTED]]" in str(synthesis).upper():
            fallback = self._deterministic_research_fallback(query=query, topic=synthesis_topic, sources=fetched)
            if fallback:
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor", sources=[source.public_dict() for source in fetched],
                )
            return ResearchAnswer(
                ok=False,
                text=(
                    "A síntese local considerou as fontes insuficientemente relacionadas com o tema pedido."
                    + (" A aprendizagem não foi guardada." if self._query_requests_learning(query) else "")
                ),
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error="LOCAL_SYNTHESIS_RELEVANCE_REJECTED",
                sources=[source.public_dict() for source in fetched],
            )

        grounding = self._validate_synthesis_grounding(
            synthesis, query=query, topic=synthesis_topic, sources=fetched
        )
        if not grounding.get("ok"):
            fallback = self._deterministic_research_fallback(query=query, topic=synthesis_topic, sources=fetched)
            if fallback:
                return ResearchAnswer(
                    ok=True, text=fallback, elapsed_ms=round((monotonic() - started) * 1000),
                    query=query, model="deterministic-source-extractor", sources=[source.public_dict() for source in fetched],
                )
            return ResearchAnswer(
                ok=False,
                text="A síntese local incluiu uma afirmação não sustentada pelas fontes recolhidas; por isso não a apresento como verificada.",
                elapsed_ms=round((monotonic() - started) * 1000),
                query=query,
                error=str(grounding.get("reason") or "LOCAL_SYNTHESIS_UNGROUNDED"),
                message=json.dumps(grounding, ensure_ascii=False)[:800],
                sources=[source.public_dict() for source in fetched],
            )

        return ResearchAnswer(
            ok=True,
            text=synthesis,
            elapsed_ms=round((monotonic() - started) * 1000),
            query=query,
            model=getattr(self.settings, "model", None),
            sources=[source.public_dict() for source in fetched],
        )

