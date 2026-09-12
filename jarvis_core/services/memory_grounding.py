from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol
import re
import unicodedata


ACTIVE_MEMORY_SOURCES = frozenset({
    "user_profile",
    "explicit_fact",
    "conversation",
    "memory_graph",
    "personal_model",
    "authorized_learning",
})


OWNER_PERSONAL_MODEL_KINDS = (
    "preferences",
    "goals",
    "constraints",
    "projects",
    "owner_learning_goals",
    "time_boundaries",
)


MEMORY_RETRIEVAL_STRATEGIES = frozenset({
    "RELEVANCE",
    "RECENT",
})


MEMORY_MISSING_POLICIES = frozenset({
    "REPORT_MISSING",
})


MEMORY_SCOPE_NAMES = frozenset({
    "OWNER_PROFILE",
    "OWNER_FULL_NAME",
    "OWNER_FACTUAL_SUMMARY",
    "OWNER_MEMORY_OVERVIEW",
    "OWNER_PREFERENCES",
    "OWNER_GOALS",
    "OWNER_CONSTRAINTS",
    "OWNER_PROJECTS",
    "OWNER_LEARNING_GOALS",
    "OWNER_HOME",
    "OWNER_PERSONAL_MODEL",
    "OWNER_VIEW",
    "OWNER_RELATIONSHIP",
    "OWNER_EXPLICIT_FACT",
    "OWNER_RECENT_EXPLICIT",
    "JARVIS_LEARNING_GOALS",
    "JARVIS_DIRECTIVES",
})


MemoryFilter = (
    Sequence[str]
    | set[str]
    | None
)


class MemoryBackend(Protocol):
    """Stable retrieval interface beneath request grounding.

    The current implementation is UnifiedMemoryIndex/FTS5.
    A future hybrid lexical/vector backend must preserve this
    contract so semantic ownership and grounding scopes do not
    need to change.
    """

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        sources: MemoryFilter = None,
        kinds: MemoryFilter = None,
    ) -> dict[str, Any]:
        ...

    def recent_records(
        self,
        *,
        limit: int = 10,
        sources: MemoryFilter = None,
        kinds: MemoryFilter = None,
    ) -> dict[str, Any]:
        ...


@dataclass(
    frozen=True,
    slots=True,
)
class MemoryGroundingLane:
    """One admissible retrieval lane inside a memory scope."""

    name: str
    strategy: str
    sources: tuple[str, ...]
    kinds: tuple[str, ...] | None = None
    limit: int = 4
    validator: str | None = None

    def __post_init__(
        self,
    ) -> None:
        name = str(
            self.name
            or ""
        ).strip()

        strategy = str(
            self.strategy
            or ""
        ).strip().upper()

        sources = tuple(
            dict.fromkeys(
                str(
                    value
                    or ""
                ).strip()
                for value
                in self.sources
                if str(
                    value
                    or ""
                ).strip()
            )
        )

        kinds = (
            None
            if self.kinds
            is None
            else tuple(
                dict.fromkeys(
                    str(
                        value
                        or ""
                    ).strip()
                    for value
                    in self.kinds
                    if str(
                        value
                        or ""
                    ).strip()
                )
            )
        )

        validator = (
            None
            if self.validator
            is None
            else str(
                self.validator
                or ""
            ).strip()
            or None
        )

        if not name:
            raise ValueError(
                "memory grounding lane name must not be empty"
            )

        if (
            strategy
            not in MEMORY_RETRIEVAL_STRATEGIES
        ):
            raise ValueError(
                (
                    "invalid memory retrieval strategy: "
                    + strategy
                )
            )

        if not sources:
            raise ValueError(
                "memory grounding lane requires sources"
            )

        invalid_sources = sorted(
            set(
                sources
            )
            - ACTIVE_MEMORY_SOURCES
        )

        if invalid_sources:
            raise ValueError(
                (
                    "invalid memory sources: "
                    + repr(
                        invalid_sources
                    )
                )
            )

        if (
            self.kinds
            is not None
            and not kinds
        ):
            raise ValueError(
                (
                    "kinds must be None "
                    "or contain at least one kind"
                )
            )

        limit = int(
            self.limit
        )

        if (
            limit < 1
            or limit > 50
        ):
            raise ValueError(
                "memory grounding lane limit must be 1..50"
            )

        object.__setattr__(
            self,
            "name",
            name,
        )

        object.__setattr__(
            self,
            "strategy",
            strategy,
        )

        object.__setattr__(
            self,
            "sources",
            sources,
        )

        object.__setattr__(
            self,
            "kinds",
            kinds,
        )

        object.__setattr__(
            self,
            "limit",
            limit,
        )

        object.__setattr__(
            self,
            "validator",
            validator,
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "name":
                self.name,
            "strategy":
                self.strategy,
            "sources":
                list(
                    self.sources
                ),
            "kinds":
                (
                    list(
                        self.kinds
                    )
                    if self.kinds
                    is not None
                    else None
                ),
            "limit":
                self.limit,
            "validator":
                self.validator,
        }


@dataclass(
    frozen=True,
    slots=True,
)
class MemoryGroundingScope:
    """Immutable evidence contract for one semantic memory concept."""

    name: str
    subject: str
    lanes: tuple[
        MemoryGroundingLane,
        ...,
    ]
    missing_reason: str
    missing_policy: str = "REPORT_MISSING"
    max_results: int = 6
    rules: tuple[str, ...] = ()

    def __post_init__(
        self,
    ) -> None:
        name = str(
            self.name
            or ""
        ).strip().upper()

        subject = str(
            self.subject
            or ""
        ).strip().upper()

        lanes = tuple(
            self.lanes
        )

        missing_reason = str(
            self.missing_reason
            or ""
        ).strip()

        missing_policy = str(
            self.missing_policy
            or ""
        ).strip().upper()

        rules = tuple(
            str(
                value
                or ""
            ).strip()
            for value
            in self.rules
            if str(
                value
                or ""
            ).strip()
        )

        if (
            name
            not in MEMORY_SCOPE_NAMES
        ):
            raise ValueError(
                (
                    "invalid memory scope: "
                    + name
                )
            )

        if subject not in {
            "OWNER",
            "JARVIS",
        }:
            raise ValueError(
                (
                    "invalid memory grounding subject: "
                    + subject
                )
            )

        if not lanes:
            raise ValueError(
                "memory grounding scope requires at least one lane"
            )

        if not all(
            isinstance(
                lane,
                MemoryGroundingLane,
            )
            for lane
            in lanes
        ):
            raise TypeError(
                "memory grounding lanes must be MemoryGroundingLane"
            )

        if not missing_reason:
            raise ValueError(
                "memory grounding scope requires missing_reason"
            )

        if (
            missing_policy
            not in MEMORY_MISSING_POLICIES
        ):
            raise ValueError(
                (
                    "invalid memory missing policy: "
                    + missing_policy
                )
            )

        max_results = int(
            self.max_results
        )

        if (
            max_results < 1
            or max_results > 50
        ):
            raise ValueError(
                "memory grounding max_results must be 1..50"
            )

        object.__setattr__(
            self,
            "name",
            name,
        )

        object.__setattr__(
            self,
            "subject",
            subject,
        )

        object.__setattr__(
            self,
            "lanes",
            lanes,
        )

        object.__setattr__(
            self,
            "missing_reason",
            missing_reason,
        )

        object.__setattr__(
            self,
            "missing_policy",
            missing_policy,
        )

        object.__setattr__(
            self,
            "max_results",
            max_results,
        )

        object.__setattr__(
            self,
            "rules",
            rules,
        )

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "name":
                self.name,
            "subject":
                self.subject,
            "lanes": [
                lane.as_dict()
                for lane
                in self.lanes
            ],
            "missing_reason":
                self.missing_reason,
            "missing_policy":
                self.missing_policy,
            "max_results":
                self.max_results,
            "rules":
                list(
                    self.rules
                ),
        }


class MemoryGroundingRegistry:
    """Read-only registry of semantic memory evidence scopes."""

    def __init__(
        self,
        scopes: Sequence[
            MemoryGroundingScope
        ],
    ) -> None:
        rows = {}

        for scope in scopes:
            if not isinstance(
                scope,
                MemoryGroundingScope,
            ):
                raise TypeError(
                    "registry values must be MemoryGroundingScope"
                )

            if scope.name in rows:
                raise ValueError(
                    (
                        "duplicate memory scope: "
                        + scope.name
                    )
                )

            rows[
                scope.name
            ] = scope

        names = frozenset(
            rows
        )

        if (
            names
            != MEMORY_SCOPE_NAMES
        ):
            missing = sorted(
                MEMORY_SCOPE_NAMES
                - names
            )

            extra = sorted(
                names
                - MEMORY_SCOPE_NAMES
            )

            raise ValueError(
                (
                    "memory scope registry mismatch; "
                    f"missing={missing!r}, "
                    f"extra={extra!r}"
                )
            )

        self._scopes = (
            MappingProxyType(
                rows
            )
        )

    @property
    def names(
        self,
    ) -> frozenset[str]:
        return frozenset(
            self._scopes
        )

    def get(
        self,
        name: str | None,
    ) -> MemoryGroundingScope | None:
        key = str(
            name
            or ""
        ).strip().upper()

        if not key:
            return None

        return self._scopes.get(
            key
        )

    def require(
        self,
        name: str,
    ) -> MemoryGroundingScope:
        scope = self.get(
            name
        )

        if scope is None:
            raise KeyError(
                (
                    "unknown memory grounding scope: "
                    + str(
                        name
                    )
                )
            )

        return scope

    def all(
        self,
    ) -> tuple[
        MemoryGroundingScope,
        ...,
    ]:
        return tuple(
            self._scopes[
                name
            ]
            for name
            in sorted(
                self._scopes
            )
        )


def _normalize_evidence_text(
    value: object,
) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(
            value
            or ""
        ).casefold(),
    )

    text = "".join(
        char
        for char in text
        if not unicodedata.combining(
            char
        )
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _strip_assistant_vocative(
    value: object,
) -> str:
    return re.sub(
        (
            r"^\s*"
            r"(?:jarvis|jervis|jarves|"
            r"jarviz|zarvis|zarbis|jarbis)"
            r"\s*[,;:\-]?\s*"
        ),
        "",
        str(
            value
            or ""
        ).strip(),
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _name_token_count(
    value: object,
) -> int:
    return len(
        re.findall(
            r"[\w'-]+",
            str(
                value
                or ""
            ),
            flags=re.UNICODE,
        )
    )


def _explicit_owner_full_name(
    row: dict[str, Any],
) -> bool:
    text = str(
        row.get(
            "text"
        )
        or ""
    )

    if not text.strip():
        return False

    # Structured profile data is accepted only when the
    # field itself explicitly means full name. A generic
    # name=Tiago field is deliberately insufficient.
    for line in text.splitlines():
        match = re.match(
            (
                r"^\s*"
                r"(?P<key>[^:=]+?)"
                r"\s*[:=]\s*"
                r"(?P<value>.+?)"
                r"\s*$"
            ),
            line,
        )

        if match is None:
            continue

        key = (
            _normalize_evidence_text(
                match.group(
                    "key"
                )
            )
        )

        if key not in {
            "full_name",
            "full name",
            "nome_completo",
            "nome completo",
            "owner full name",
        }:
            continue

        return (
            _name_token_count(
                match.group(
                    "value"
                )
            )
            >= 2
        )

    normalized = (
        _normalize_evidence_text(
            text
        )
    )

    patterns = (
        (
            r"\b(?:o )?"
            r"meu nome completo"
            r"\s*(?:e|=|:)\s*"
            r"(?P<value>.+)$"
        ),
        (
            r"\bowner full name"
            r"\s*(?:is|=|:)\s*"
            r"(?P<value>.+)$"
        ),
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            normalized,
        )

        if match is None:
            continue

        return (
            _name_token_count(
                match.group(
                    "value"
                )
            )
            >= 2
        )

    return False


def _explicit_owner_relationship(
    row: dict[str, Any],
) -> bool:
    normalized = (
        _normalize_evidence_text(
            row.get(
                "text"
            )
        )
    )

    if not normalized:
        return False

    return bool(
        re.search(
            (
                r"\bminha mulher\b"
                r"|\bminha esposa\b"
                r"|\bmy wife\b"
                r"|\bmy spouse\b"
                r"|relation\s*[:=]\s*partner\b"
                r"|relationship\s*[:=]\s*partner\b"
            ),
            normalized,
        )
    )


def _explicit_owner_home(
    row: dict[str, Any],
) -> bool:
    normalized = (
        _normalize_evidence_text(
            row.get(
                "text"
            )
        )
    )

    if not normalized:
        return False

    return bool(
        re.search(
            (
                r"(?:^|\s)"
                r"(?:home(?:\.[\w_-]+)?"
                r"|address"
                r"|morada"
                r"|cidade)"
                r"\s*[:=]"
            ),
            normalized,
        )
    )


_MEMORY_EVIDENCE_VALIDATORS = (
    MappingProxyType({
        "explicit_owner_full_name":
            _explicit_owner_full_name,

        "explicit_owner_relationship":
            _explicit_owner_relationship,

        "explicit_owner_home":
            _explicit_owner_home,
    })
)


def _row_allowed_by_lane(
    row: dict[str, Any],
    lane: MemoryGroundingLane,
) -> bool:
    source = str(
        row.get(
            "source"
        )
        or ""
    ).strip()

    kind = str(
        row.get(
            "kind"
        )
        or ""
    ).strip()

    if source not in lane.sources:
        return False

    if (
        lane.kinds
        is not None
        and kind
        not in lane.kinds
    ):
        return False

    if not str(
        row.get(
            "text"
        )
        or ""
    ).strip():
        return False

    if lane.validator is None:
        return True

    validator = (
        _MEMORY_EVIDENCE_VALIDATORS
        .get(
            lane.validator
        )
    )

    if validator is None:
        return False

    return bool(
        validator(
            row
        )
    )


def _evidence_identity(
    row: dict[str, Any],
) -> tuple[
    str,
    str,
    str,
]:
    source = str(
        row.get(
            "source"
        )
        or ""
    )

    identity = str(
        row.get(
            "content_hash"
        )
        or row.get(
            "id"
        )
        or row.get(
            "source_id"
        )
        or row.get(
            "text"
        )
        or ""
    )

    kind = str(
        row.get(
            "kind"
        )
        or ""
    )

    return (
        source,
        kind,
        identity,
    )


class MemoryGroundingExecutor:
    """Execute immutable scopes against any compatible backend.

    This layer is deliberately backend-agnostic. It re-applies
    source/kind boundaries after retrieval so a loose lexical,
    vector or hybrid backend cannot widen the evidence scope.
    """

    def __init__(
        self,
        backend: MemoryBackend,
        registry: (
            MemoryGroundingRegistry
            | None
        ) = None,
    ) -> None:
        self.backend = backend

        self.registry = (
            registry
            if registry is not None
            else MEMORY_GROUNDING_REGISTRY
        )

    def execute(
        self,
        scope_name: str,
        query: str = "",
    ) -> dict[str, Any]:
        scope = (
            self.registry
            .require(
                scope_name
            )
        )

        effective_query = (
            _strip_assistant_vocative(
                query
            )
        )

        selected = []
        seen = set()
        lane_results = []

        for lane in scope.lanes:
            try:
                if (
                    lane.strategy
                    == "RECENT"
                ):
                    result = (
                        self.backend
                        .recent_records(
                            limit=
                                lane.limit,
                            sources=
                                lane.sources,
                            kinds=
                                lane.kinds,
                        )
                    )

                elif (
                    lane.strategy
                    == "RELEVANCE"
                ):
                    result = (
                        self.backend
                        .search(
                            effective_query,
                            limit=
                                lane.limit,
                            sources=
                                lane.sources,
                            kinds=
                                lane.kinds,
                        )
                    )

                else:
                    return {
                        "ok": False,
                        "error":
                            (
                                "INVALID_MEMORY_"
                                "RETRIEVAL_STRATEGY"
                            ),
                        "scope":
                            scope.name,
                        "results": [],
                    }

            except Exception as exc:
                return {
                    "ok": False,
                    "error":
                        (
                            "MEMORY_BACKEND_"
                            "EXECUTION_FAILED:"
                            + type(
                                exc
                            ).__name__
                        ),
                    "scope":
                        scope.name,
                    "lane":
                        lane.name,
                    "results": [],
                }

            if not result.get(
                "ok"
            ):
                return {
                    "ok": False,
                    "error":
                        str(
                            result.get(
                                "error"
                            )
                            or (
                                "MEMORY_BACKEND_"
                                "UNAVAILABLE"
                            )
                        ),
                    "scope":
                        scope.name,
                    "lane":
                        lane.name,
                    "results": [],
                }

            raw_rows = [
                dict(
                    row
                )
                for row
                in list(
                    result.get(
                        "results"
                    )
                    or []
                )
                if isinstance(
                    row,
                    dict,
                )
            ]

            accepted = []

            for row in raw_rows:
                if not _row_allowed_by_lane(
                    row,
                    lane,
                ):
                    continue

                identity = (
                    _evidence_identity(
                        row
                    )
                )

                if identity in seen:
                    continue

                seen.add(
                    identity
                )

                item = dict(
                    row
                )

                item[
                    "grounding_scope"
                ] = scope.name

                item[
                    "grounding_lane"
                ] = lane.name

                accepted.append(
                    item
                )

                selected.append(
                    item
                )

                if (
                    len(
                        selected
                    )
                    >= scope.max_results
                ):
                    break

            lane_results.append({
                "lane":
                    lane.name,
                "strategy":
                    lane.strategy,
                "sources":
                    list(
                        lane.sources
                    ),
                "kinds":
                    (
                        list(
                            lane.kinds
                        )
                        if lane.kinds
                        is not None
                        else None
                    ),
                "validator":
                    lane.validator,
                "raw_count":
                    len(
                        raw_rows
                    ),
                "accepted_count":
                    len(
                        accepted
                    ),
            })

            if (
                len(
                    selected
                )
                >= scope.max_results
            ):
                break

        retrieved = bool(
            selected
        )

        return {
            "ok": True,
            "retrieved":
                retrieved,
            "reason":
                (
                    "scoped_memory_evidence"
                    if retrieved
                    else scope.missing_reason
                ),
            "scope":
                scope.name,
            "subject":
                scope.subject,
            "retrieval_mode":
                "scoped_memory_grounding",
            "backend_query":
                effective_query,
            "evidence_status":
                (
                    "present"
                    if retrieved
                    else "missing"
                ),
            "missing_reason":
                scope.missing_reason,
            "missing_policy":
                scope.missing_policy,
            "rules":
                list(
                    scope.rules
                ),
            "lanes":
                lane_results,
            "results":
                selected[
                    :scope.max_results
                ],
        }


def _lane(
    name: str,
    strategy: str,
    sources: tuple[str, ...],
    *,
    kinds: tuple[str, ...] | None = None,
    limit: int = 4,
    validator: str | None = None,
) -> MemoryGroundingLane:
    return MemoryGroundingLane(
        name=name,
        strategy=strategy,
        sources=sources,
        kinds=kinds,
        limit=limit,
        validator=validator,
    )


_MEMORY_SCOPES = (
    MemoryGroundingScope(
        name="OWNER_PROFILE",
        subject="OWNER",
        lanes=(
            _lane(
                "profile",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
            ),
        ),
        missing_reason=
            "owner_profile_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_FULL_NAME",
        subject="OWNER",
        lanes=(
            _lane(
                "profile_full_name",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
                validator=
                    "explicit_owner_full_name",
            ),
            _lane(
                "explicit_full_name",
                "RELEVANCE",
                (
                    "explicit_fact",
                ),
                limit=6,
                validator=
                    "explicit_owner_full_name",
            ),
        ),
        missing_reason=
            "owner_full_name_not_stored",
        max_results=2,
        rules=(
            (
                "Use only evidence that explicitly "
                "states the OWNER full name."
            ),
            (
                "A first name, ambient identity or "
                "another person's name is not "
                "full-name evidence."
            ),
            (
                "If evidence is missing, report "
                "that the OWNER full name is not "
                "stored in admissible evidence."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_FACTUAL_SUMMARY",
        subject="OWNER",
        lanes=(
            _lane(
                "profile",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
            ),
            _lane(
                "explicit_facts",
                "RECENT",
                (
                    "explicit_fact",
                ),
                limit=5,
            ),
        ),
        missing_reason=
            "owner_factual_memory_not_stored",
        rules=(
            (
                "Report only scoped OWNER profile "
                "and explicit OWNER facts."
            ),
            (
                "Do not fill factual gaps from "
                "ambient relational context or "
                "JARVIS learning."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_MEMORY_OVERVIEW",
        subject="OWNER",
        lanes=(
            _lane(
                "profile",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
            ),
            _lane(
                "explicit_facts",
                "RECENT",
                (
                    "explicit_fact",
                ),
                limit=4,
            ),
            _lane(
                "personal_model",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=
                    OWNER_PERSONAL_MODEL_KINDS,
                limit=4,
            ),
            _lane(
                "relationships",
                "RECENT",
                (
                    "memory_graph",
                ),
                kinds=(
                    "edge",
                    "node:fact",
                ),
                limit=3,
                validator=
                    "explicit_owner_relationship",
            ),
        ),
        missing_reason=
            "owner_memory_not_stored",
        max_results=10,
        rules=(
            (
                "Report only evidence admitted by "
                "this OWNER memory scope."
            ),
            (
                "Never present jarvis_directives "
                "or jarvis_learning_goals as "
                "OWNER memory."
            ),
            (
                "Do not invent privacy or access "
                "limitations."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_PREFERENCES",
        subject="OWNER",
        lanes=(
            _lane(
                "preferences",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "preferences",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_preferences_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_GOALS",
        subject="OWNER",
        lanes=(
            _lane(
                "goals",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "goals",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_goals_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_CONSTRAINTS",
        subject="OWNER",
        lanes=(
            _lane(
                "constraints",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "constraints",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_constraints_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_PROJECTS",
        subject="OWNER",
        lanes=(
            _lane(
                "projects",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "projects",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_projects_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_LEARNING_GOALS",
        subject="OWNER",
        lanes=(
            _lane(
                "owner_learning_goals",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "owner_learning_goals",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_learning_goals_not_stored",
        rules=(
            (
                "Only owner_learning_goals are "
                "OWNER learning-goal evidence."
            ),
            (
                "Never substitute "
                "jarvis_learning_goals or "
                "jarvis_directives."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_HOME",
        subject="OWNER",
        lanes=(
            _lane(
                "home",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
                validator=
                    "explicit_owner_home",
            ),
        ),
        missing_reason=
            "owner_home_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_PERSONAL_MODEL",
        subject="OWNER",
        lanes=(
            _lane(
                "owner_personal_model",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=
                    OWNER_PERSONAL_MODEL_KINDS,
                limit=10,
            ),
        ),
        missing_reason=
            "owner_personal_model_empty",
        max_results=10,
        rules=(
            (
                "Describe only OWNER personal-model "
                "buckets admitted by this scope."
            ),
            (
                "Exclude jarvis_directives and "
                "jarvis_learning_goals."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_VIEW",
        subject="OWNER",
        lanes=(
            _lane(
                "profile",
                "RECENT",
                (
                    "user_profile",
                ),
                kinds=(
                    "profile",
                ),
                limit=1,
            ),
            _lane(
                "owner_personal_model",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=
                    OWNER_PERSONAL_MODEL_KINDS,
                limit=8,
            ),
        ),
        missing_reason=
            "owner_view_evidence_not_stored",
        max_results=8,
    ),

    MemoryGroundingScope(
        name="OWNER_RELATIONSHIP",
        subject="OWNER",
        lanes=(
            _lane(
                "explicit_relationship",
                "RELEVANCE",
                (
                    "explicit_fact",
                ),
                limit=8,
                validator=
                    "explicit_owner_relationship",
            ),
            _lane(
                "graph_relationship",
                "RELEVANCE",
                (
                    "memory_graph",
                ),
                kinds=(
                    "edge",
                    "node:fact",
                ),
                limit=8,
                validator=
                    "explicit_owner_relationship",
            ),
        ),
        missing_reason=
            "owner_relationship_not_stored",
        max_results=6,
        rules=(
            (
                "Use only evidence explicitly "
                "stating the requested OWNER "
                "relationship."
            ),
            (
                "A person name alone is not "
                "relationship evidence."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="OWNER_EXPLICIT_FACT",
        subject="OWNER",
        lanes=(
            _lane(
                "explicit_fact",
                "RELEVANCE",
                (
                    "explicit_fact",
                ),
                limit=6,
            ),
        ),
        missing_reason=
            "owner_explicit_fact_not_stored",
    ),

    MemoryGroundingScope(
        name="OWNER_RECENT_EXPLICIT",
        subject="OWNER",
        lanes=(
            _lane(
                "recent_explicit",
                "RECENT",
                (
                    "explicit_fact",
                ),
                kinds=(
                    "user_explicit",
                ),
                limit=1,
            ),
        ),
        missing_reason=
            "recent_owner_explicit_fact_not_stored",
        max_results=1,
    ),

    MemoryGroundingScope(
        name="JARVIS_LEARNING_GOALS",
        subject="JARVIS",
        lanes=(
            _lane(
                "jarvis_learning_goals",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "jarvis_learning_goals",
                ),
                limit=8,
            ),
        ),
        missing_reason=
            "jarvis_learning_goals_not_stored",
        max_results=8,
        rules=(
            (
                "Only jarvis_learning_goals are "
                "JARVIS learning-goal evidence."
            ),
            (
                "Do not substitute OWNER goals, "
                "preferences or "
                "owner_learning_goals."
            ),
        ),
    ),

    MemoryGroundingScope(
        name="JARVIS_DIRECTIVES",
        subject="JARVIS",
        lanes=(
            _lane(
                "jarvis_directives",
                "RECENT",
                (
                    "personal_model",
                ),
                kinds=(
                    "jarvis_directives",
                ),
                limit=8,
            ),
        ),
        missing_reason=
            "jarvis_directives_not_stored",
        max_results=8,
    ),
)


MEMORY_GROUNDING_REGISTRY = (
    MemoryGroundingRegistry(
        _MEMORY_SCOPES
    )
)


def memory_grounding_scope(
    name: str | None,
) -> MemoryGroundingScope | None:
    return (
        MEMORY_GROUNDING_REGISTRY
        .get(
            name
        )
    )


def require_memory_grounding_scope(
    name: str,
) -> MemoryGroundingScope:
    return (
        MEMORY_GROUNDING_REGISTRY
        .require(
            name
        )
    )
