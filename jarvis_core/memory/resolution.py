from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .errors import MemoryValidationError
from .ids import new_memory_id
from .validation import (
    require_confidence,
    require_predicate,
    require_text,
)


PROPERTY_ID_PREFIX = "property_"


class CanonicalIdentityDomain(StrEnum):
    ENTITY = "ENTITY"
    PROPERTY = "PROPERTY"


class IdentityResolutionAction(StrEnum):
    EXISTING = "EXISTING"
    NEW = "NEW"
    AMBIGUOUS = "AMBIGUOUS"


def _checked_labels(
    values: tuple[str, ...],
    *,
    name: str,
) -> tuple[str, ...]:
    if not isinstance(
        values,
        tuple,
    ):
        raise MemoryValidationError(
            f"{name} must be a tuple"
        )

    result: list[str] = []

    for value in values:
        if not isinstance(
            value,
            str,
        ):
            raise MemoryValidationError(
                f"{name} values must be text"
            )

        text = value.strip()

        if not text:
            raise MemoryValidationError(
                f"{name} contains empty value"
            )

        result.append(
            text
        )

    checked = tuple(
        result
    )

    if not checked:
        raise MemoryValidationError(
            f"{name} must not be empty"
        )

    if (
        len(
            set(
                checked
            )
        )
        != len(
            checked
        )
    ):
        raise MemoryValidationError(
            f"{name} must be unique"
        )

    return checked


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalIdentityCandidate:
    domain: CanonicalIdentityDomain
    canonical_id: str
    semantic_labels: tuple[str, ...]
    semantic_type: str

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.domain,
            CanonicalIdentityDomain,
        ):
            raise MemoryValidationError(
                "candidate.domain must be "
                "CanonicalIdentityDomain"
            )

        require_text(
            self.canonical_id,
            "candidate.canonical_id",
        )

        require_text(
            self.semantic_type,
            "candidate.semantic_type",
        )

        checked_labels = (
            _checked_labels(
                self.semantic_labels,
                name=(
                    "candidate.semantic_labels"
                ),
            )
        )

        object.__setattr__(
            self,
            "semantic_labels",
            checked_labels,
        )

        if (
            self.domain
            is CanonicalIdentityDomain.PROPERTY
        ):
            require_predicate(
                self.canonical_id
            )


@dataclass(
    frozen=True,
    slots=True,
)
class ModelCandidateView:
    handle: str
    domain: CanonicalIdentityDomain
    semantic_labels: tuple[str, ...]
    semantic_type: str

    def __post_init__(
        self,
    ) -> None:
        require_text(
            self.handle,
            "ModelCandidateView.handle",
        )

        if not isinstance(
            self.domain,
            CanonicalIdentityDomain,
        ):
            raise MemoryValidationError(
                "ModelCandidateView.domain must be "
                "CanonicalIdentityDomain"
            )

        require_text(
            self.semantic_type,
            "ModelCandidateView.semantic_type",
        )

        checked_labels = (
            _checked_labels(
                self.semantic_labels,
                name=(
                    "ModelCandidateView.semantic_labels"
                ),
            )
        )

        object.__setattr__(
            self,
            "semantic_labels",
            checked_labels,
        )


@dataclass(
    frozen=True,
    slots=True,
)
class IdentitySelection:
    action: IdentityResolutionAction
    confidence: float
    selected_handle: str | None = None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.action,
            IdentityResolutionAction,
        ):
            raise MemoryValidationError(
                "selection.action must be "
                "IdentityResolutionAction"
            )

        require_confidence(
            self.confidence
        )

        if (
            self.action
            is IdentityResolutionAction.EXISTING
        ):
            require_text(
                self.selected_handle or "",
                "selection.selected_handle",
            )

        elif (
            self.selected_handle
            is not None
        ):
            raise MemoryValidationError(
                "only EXISTING selection may "
                "carry selected_handle"
            )


@dataclass(
    frozen=True,
    slots=True,
)
class CanonicalIdentityResolution:
    domain: CanonicalIdentityDomain
    action: IdentityResolutionAction
    confidence: float
    canonical_id: str | None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.domain,
            CanonicalIdentityDomain,
        ):
            raise MemoryValidationError(
                "resolution.domain must be "
                "CanonicalIdentityDomain"
            )

        if not isinstance(
            self.action,
            IdentityResolutionAction,
        ):
            raise MemoryValidationError(
                "resolution.action must be "
                "IdentityResolutionAction"
            )

        require_confidence(
            self.confidence
        )

        if (
            self.action
            is IdentityResolutionAction.AMBIGUOUS
        ):
            if (
                self.canonical_id
                is not None
            ):
                raise MemoryValidationError(
                    "AMBIGUOUS resolution cannot "
                    "carry canonical_id"
                )

            return

        require_text(
            self.canonical_id or "",
            "resolution.canonical_id",
        )

        if (
            self.domain
            is CanonicalIdentityDomain.PROPERTY
        ):
            require_predicate(
                self.canonical_id or ""
            )


class SemanticIdentityMatcher(
    Protocol
):
    def select_identity(
        self,
        *,
        domain: CanonicalIdentityDomain,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
        candidates: tuple[
            ModelCandidateView,
            ...
        ],
    ) -> IdentitySelection:
        ...


def _candidate_handle(
    index: int,
) -> str:
    if (
        not isinstance(
            index,
            int,
        )
        or isinstance(
            index,
            bool,
        )
        or index < 0
    ):
        raise MemoryValidationError(
            "candidate index must be "
            "non-negative integer"
        )

    return (
        "candidate_"
        + str(
            index
        ).zfill(
            4
        )
    )


def _mint_identity(
    domain: CanonicalIdentityDomain,
) -> str:
    if (
        domain
        is CanonicalIdentityDomain.ENTITY
    ):
        return new_memory_id()

    if (
        domain
        is CanonicalIdentityDomain.PROPERTY
    ):
        memory_id = (
            new_memory_id()
            .replace(
                "-",
                "",
            )
        )

        predicate = (
            PROPERTY_ID_PREFIX
            + memory_id
        )

        require_predicate(
            predicate
        )

        return predicate

    raise MemoryValidationError(
        "unsupported canonical identity domain"
    )


@dataclass(
    frozen=True,
    slots=True,
)
class CandidateCatalog:
    domain: CanonicalIdentityDomain
    candidates: tuple[
        CanonicalIdentityCandidate,
        ...
    ]

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.domain,
            CanonicalIdentityDomain,
        ):
            raise MemoryValidationError(
                "catalog.domain must be "
                "CanonicalIdentityDomain"
            )

        if not isinstance(
            self.candidates,
            tuple,
        ):
            raise MemoryValidationError(
                "catalog.candidates must be tuple"
            )

        ids: list[str] = []

        for candidate in self.candidates:
            if not isinstance(
                candidate,
                CanonicalIdentityCandidate,
            ):
                raise MemoryValidationError(
                    "catalog contains invalid "
                    "candidate"
                )

            if (
                candidate.domain
                is not self.domain
            ):
                raise MemoryValidationError(
                    "catalog candidate domain "
                    "does not match catalog"
                )

            ids.append(
                candidate.canonical_id
            )

        if (
            len(
                set(
                    ids
                )
            )
            != len(
                ids
            )
        ):
            raise MemoryValidationError(
                "catalog canonical IDs "
                "must be unique"
            )

    def model_views(
        self,
    ) -> tuple[
        ModelCandidateView,
        ...
    ]:
        return tuple(
            ModelCandidateView(
                handle=(
                    _candidate_handle(
                        index
                    )
                ),
                domain=(
                    candidate.domain
                ),
                semantic_labels=(
                    candidate
                    .semantic_labels
                ),
                semantic_type=(
                    candidate
                    .semantic_type
                ),
            )
            for index, candidate
            in enumerate(
                self.candidates
            )
        )

    def _canonical_id_for_handle(
        self,
        handle: str,
    ) -> str:
        require_text(
            handle,
            "catalog.handle",
        )

        mapping = {
            _candidate_handle(
                index
            ):
                candidate
                .canonical_id

            for index, candidate
            in enumerate(
                self.candidates
            )
        }

        try:
            return mapping[
                handle
            ]

        except KeyError as exc:
            raise MemoryValidationError(
                "matcher selected unknown "
                "candidate handle"
            ) from exc

    def resolve_selection(
        self,
        selection: IdentitySelection,
    ) -> CanonicalIdentityResolution:
        if not isinstance(
            selection,
            IdentitySelection,
        ):
            raise MemoryValidationError(
                "matcher returned invalid "
                "selection object"
            )

        if (
            selection.action
            is IdentityResolutionAction.EXISTING
        ):
            canonical_id = (
                self
                ._canonical_id_for_handle(
                    selection
                    .selected_handle
                    or ""
                )
            )

            return (
                CanonicalIdentityResolution(
                    domain=self.domain,
                    action=(
                        IdentityResolutionAction
                        .EXISTING
                    ),
                    confidence=(
                        selection.confidence
                    ),
                    canonical_id=(
                        canonical_id
                    ),
                )
            )

        if (
            selection.action
            is IdentityResolutionAction.NEW
        ):
            return (
                CanonicalIdentityResolution(
                    domain=self.domain,
                    action=(
                        IdentityResolutionAction
                        .NEW
                    ),
                    confidence=(
                        selection.confidence
                    ),
                    canonical_id=(
                        _mint_identity(
                            self.domain
                        )
                    ),
                )
            )

        return (
            CanonicalIdentityResolution(
                domain=self.domain,
                action=(
                    IdentityResolutionAction
                    .AMBIGUOUS
                ),
                confidence=(
                    selection.confidence
                ),
                canonical_id=None,
            )
        )


def resolve_with_matcher(
    *,
    catalog: CandidateCatalog,
    matcher: SemanticIdentityMatcher,
    semantic_labels: tuple[str, ...],
    semantic_type: str,
) -> CanonicalIdentityResolution:
    if not isinstance(
        catalog,
        CandidateCatalog,
    ):
        raise MemoryValidationError(
            "catalog must be CandidateCatalog"
        )

    if not callable(
        getattr(
            matcher,
            "select_identity",
            None,
        )
    ):
        raise MemoryValidationError(
            "matcher must expose "
            "select_identity()"
        )

    checked_labels = (
        _checked_labels(
            semantic_labels,
            name="semantic_labels",
        )
    )

    require_text(
        semantic_type,
        "semantic_type",
    )

    selection = (
        matcher.select_identity(
            domain=catalog.domain,
            semantic_labels=(
                checked_labels
            ),
            semantic_type=(
                semantic_type
            ),
            candidates=(
                catalog.model_views()
            ),
        )
    )

    return (
        catalog.resolve_selection(
            selection
        )
    )


__all__ = [
    "PROPERTY_ID_PREFIX",
    "CanonicalIdentityCandidate",
    "CanonicalIdentityDomain",
    "CanonicalIdentityResolution",
    "CandidateCatalog",
    "IdentityResolutionAction",
    "IdentitySelection",
    "ModelCandidateView",
    "SemanticIdentityMatcher",
    "resolve_with_matcher",
]
