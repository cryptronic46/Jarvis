from __future__ import annotations
from enum import StrEnum
from .resolution import IdentitySelection
from .validation import require_confidence


from dataclasses import dataclass
from typing import Protocol

from .enums import MemoryStatus
from .errors import MemoryValidationError
from .models import Entity
from .resolution import (
    CandidateCatalog,
    CanonicalIdentityCandidate,
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
    SemanticIdentityMatcher,
    resolve_with_matcher,
)
from .validation import require_text


@dataclass(
    frozen=True,
    slots=True,
)
class EntitySemanticContext:
    semantic_labels: tuple[str, ...]
    semantic_type: str

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.semantic_labels,
            tuple,
        ):
            raise MemoryValidationError(
                "EntitySemanticContext.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise MemoryValidationError(
                "EntitySemanticContext.semantic_labels "
                "must not be empty"
            )

        checked_labels = []

        for label in (
            self.semantic_labels
        ):
            if not isinstance(
                label,
                str,
            ):
                raise MemoryValidationError(
                    "EntitySemanticContext.semantic_labels "
                    "values must be text"
                )

            require_text(
                label,
                (
                    "EntitySemanticContext."
                    "semantic_labels"
                ),
            )

            if (
                label
                != label.strip()
            ):
                raise MemoryValidationError(
                    "EntitySemanticContext.semantic_labels "
                    "must not contain surrounding whitespace"
                )

            checked_labels.append(
                label
            )

        if (
            len(
                set(
                    checked_labels
                )
            )
            != len(
                checked_labels
            )
        ):
            raise MemoryValidationError(
                "EntitySemanticContext.semantic_labels "
                "must be unique"
            )

        require_text(
            self.semantic_type,
            (
                "EntitySemanticContext."
                "semantic_type"
            ),
        )

        if (
            self.semantic_type
            != self.semantic_type.strip()
        ):
            raise MemoryValidationError(
                "EntitySemanticContext.semantic_type "
                "must not contain surrounding whitespace"
            )


class CanonicalEntityRegistryReader(
    Protocol,
):
    def get_entity(
        self,
        entity_id: str,
    ) -> Entity | None:
        ...

    def list_entities(
        self,
    ) -> tuple[
        Entity,
        ...,
    ]:
        ...



class RecallEntityResolutionAction(
    StrEnum
):
    EXISTING = "EXISTING"
    MISS = "MISS"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(
    frozen=True,
    slots=True,
)
class RecallEntityResolution:
    action: RecallEntityResolutionAction
    confidence: float
    canonical_id: str | None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.action,
            RecallEntityResolutionAction,
        ):
            raise MemoryValidationError(
                "RecallEntityResolution.action "
                "must be RecallEntityResolutionAction"
            )

        require_confidence(
            self.confidence
        )

        if (
            self.action
            is RecallEntityResolutionAction
            .EXISTING
        ):
            require_text(
                self.canonical_id or "",
                (
                    "RecallEntityResolution."
                    "canonical_id"
                ),
            )

            return

        if (
            self.canonical_id
            is not None
        ):
            raise MemoryValidationError(
                "MISS or AMBIGUOUS recall entity "
                "resolution cannot carry canonical_id"
            )


class CanonicalEntityCatalogReader:
    def __init__(
        self,
        registry: CanonicalEntityRegistryReader,
    ) -> None:
        if not callable(
            getattr(
                registry,
                "get_entity",
                None,
            )
        ):
            raise MemoryValidationError(
                "registry must expose "
                "get_entity()"
            )

        if not callable(
            getattr(
                registry,
                "list_entities",
                None,
            )
        ):
            raise MemoryValidationError(
                "registry must expose "
                "list_entities()"
            )

        self._registry = registry

    def build_entity_catalog(
        self,
        semantic_context: EntitySemanticContext,
    ) -> CandidateCatalog:
        if not isinstance(
            semantic_context,
            EntitySemanticContext,
        ):
            raise MemoryValidationError(
                "semantic_context must be "
                "EntitySemanticContext"
            )

        entities = (
            self._registry
            .list_entities()
        )

        if not isinstance(
            entities,
            tuple,
        ):
            raise MemoryValidationError(
                "registry.list_entities() "
                "must return tuple"
            )

        candidates = []

        for entity in entities:
            if not isinstance(
                entity,
                Entity,
            ):
                raise MemoryValidationError(
                    "registry returned invalid "
                    "canonical entity"
                )

            if (
                entity.status
                is not MemoryStatus.ACTIVE
            ):
                continue

            candidates.append(
                CanonicalIdentityCandidate(
                    domain=(
                        CanonicalIdentityDomain
                        .ENTITY
                    ),
                    canonical_id=(
                        entity.id
                    ),
                    semantic_labels=(
                        (
                            entity
                            .canonical_name,
                            *entity.aliases,
                        )
                    ),
                    semantic_type=(
                        entity.entity_type
                    ),
                )
            )

        return CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            candidates=tuple(
                candidates
            ),
        )

    def validate_existing_entity_contract(
        self,
        canonical_id: str,
    ) -> Entity:
        require_text(
            canonical_id,
            "canonical_id",
        )

        entity = (
            self._registry
            .get_entity(
                canonical_id
            )
        )

        if entity is None:
            raise MemoryValidationError(
                "selected canonical entity "
                "does not exist"
            )

        if not isinstance(
            entity,
            Entity,
        ):
            raise MemoryValidationError(
                "registry returned invalid "
                "canonical entity"
            )

        if (
            entity.status
            is not MemoryStatus.ACTIVE
        ):
            raise MemoryValidationError(
                "selected canonical entity "
                "is not ACTIVE"
            )

        return entity

    def validate_existing_recall_entity_contract(
        self,
        canonical_id: str,
    ) -> Entity:
        require_text(
            canonical_id,
            "canonical_id",
        )

        entity = (
            self._registry
            .get_entity(
                canonical_id
            )
        )

        if entity is None:
            raise MemoryValidationError(
                "selected canonical entity "
                "does not exist"
            )

        if not isinstance(
            entity,
            Entity,
        ):
            raise MemoryValidationError(
                "registry returned invalid "
                "canonical entity"
            )

        if (
            entity.status
            is not MemoryStatus.ACTIVE
        ):
            raise MemoryValidationError(
                "selected canonical entity "
                "is not ACTIVE"
            )

        return entity

    def resolve_recall_entity_identity(
        self,
        matcher: SemanticIdentityMatcher,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
    ) -> RecallEntityResolution:
        context = EntitySemanticContext(
            semantic_labels=(
                semantic_labels
            ),
            semantic_type=(
                semantic_type
            ),
        )

        catalog = (
            self.build_entity_catalog(
                context
            )
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

        selection = (
            matcher
            .select_identity(
                domain=(
                    CanonicalIdentityDomain
                    .ENTITY
                ),
                semantic_labels=(
                    context
                    .semantic_labels
                ),
                semantic_type=(
                    context
                    .semantic_type
                ),
                candidates=(
                    catalog
                    .model_views()
                ),
            )
        )

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
            is IdentityResolutionAction
            .EXISTING
        ):
            identity = (
                catalog
                .resolve_selection(
                    selection
                )
            )

            entity = (
                self
                .validate_existing_recall_entity_contract(
                    identity.canonical_id
                    or ""
                )
            )

            return RecallEntityResolution(
                action=(
                    RecallEntityResolutionAction
                    .EXISTING
                ),
                confidence=(
                    selection.confidence
                ),
                canonical_id=(
                    entity.id
                ),
            )

        if (
            selection.action
            is IdentityResolutionAction
            .NEW
        ):
            return RecallEntityResolution(
                action=(
                    RecallEntityResolutionAction
                    .MISS
                ),
                confidence=(
                    selection.confidence
                ),
                canonical_id=None,
            )

        return RecallEntityResolution(
            action=(
                RecallEntityResolutionAction
                .AMBIGUOUS
            ),
            confidence=(
                selection.confidence
            ),
            canonical_id=None,
        )

    def resolve_entity_identity(
        self,
        matcher: SemanticIdentityMatcher,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
    ) -> CanonicalIdentityResolution:
        context = EntitySemanticContext(
            semantic_labels=(
                semantic_labels
            ),
            semantic_type=(
                semantic_type
            ),
        )

        catalog = (
            self.build_entity_catalog(
                context
            )
        )

        resolution = (
            resolve_with_matcher(
                catalog=catalog,
                matcher=matcher,
                semantic_labels=(
                    context
                    .semantic_labels
                ),
                semantic_type=(
                    context
                    .semantic_type
                ),
            )
        )

        if (
            resolution.action
            is IdentityResolutionAction
            .EXISTING
        ):
            (
                self
                .validate_existing_entity_contract(
                    (
                        resolution
                        .canonical_id
                        or ""
                    )
                )
            )

        return resolution


__all__ = [
    "CanonicalEntityCatalogReader",
    "CanonicalEntityRegistryReader",
    "EntitySemanticContext",
]
