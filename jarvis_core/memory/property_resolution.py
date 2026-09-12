from __future__ import annotations
from enum import StrEnum

from .resolution import IdentitySelection
from .validation import require_confidence


from dataclasses import dataclass
from typing import Protocol

from .enums import (
    Cardinality,
    MemoryStatus,
    PropertyKind,
    ValueType,
)
from .errors import (
    MemoryCanonicalContractMismatchError,
    MemoryValidationError,
)
from .models import CanonicalProperty
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
class PropertySemanticContext:
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
                "PropertySemanticContext.semantic_labels "
                "must be tuple"
            )

        if not self.semantic_labels:
            raise MemoryValidationError(
                "PropertySemanticContext.semantic_labels "
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
                    "PropertySemanticContext.semantic_labels "
                    "values must be text"
                )

            require_text(
                label,
                (
                    "PropertySemanticContext."
                    "semantic_labels"
                ),
            )

            if label != label.strip():
                raise MemoryValidationError(
                    "PropertySemanticContext.semantic_labels "
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
                "PropertySemanticContext.semantic_labels "
                "must be unique"
            )

        require_text(
            self.semantic_type,
            (
                "PropertySemanticContext."
                "semantic_type"
            ),
        )

        if (
            self.semantic_type
            != self.semantic_type.strip()
        ):
            raise MemoryValidationError(
                "PropertySemanticContext.semantic_type "
                "must not contain surrounding whitespace"
            )


class CanonicalPropertyRegistryReader(
    Protocol,
):
    def get_property(
        self,
        property_id: str,
    ) -> CanonicalProperty | None:
        ...

    def list_properties(
        self,
        *,
        kind: PropertyKind | None = None,
    ) -> tuple[
        CanonicalProperty,
        ...,
    ]:
        ...



class RecallPropertyResolutionAction(
    StrEnum
):
    EXISTING = "EXISTING"
    MISS = "MISS"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(
    frozen=True,
    slots=True,
)
class RecallPropertyResolution:
    kind: PropertyKind
    action: RecallPropertyResolutionAction
    confidence: float
    canonical_id: str | None

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.kind,
            PropertyKind,
        ):
            raise MemoryValidationError(
                "RecallPropertyResolution.kind "
                "must be PropertyKind"
            )

        if not isinstance(
            self.action,
            RecallPropertyResolutionAction,
        ):
            raise MemoryValidationError(
                "RecallPropertyResolution.action "
                "must be RecallPropertyResolutionAction"
            )

        require_confidence(
            self.confidence
        )

        if (
            self.action
            is RecallPropertyResolutionAction
            .EXISTING
        ):
            require_text(
                self.canonical_id or "",
                (
                    "RecallPropertyResolution."
                    "canonical_id"
                ),
            )

            return

        if (
            self.canonical_id
            is not None
        ):
            raise MemoryValidationError(
                "MISS or AMBIGUOUS recall property "
                "resolution cannot carry canonical_id"
            )


class CanonicalPropertyCatalogReader:
    def __init__(
        self,
        registry: CanonicalPropertyRegistryReader,
    ) -> None:
        if not callable(
            getattr(
                registry,
                "get_property",
                None,
            )
        ):
            raise MemoryValidationError(
                "registry must expose "
                "get_property()"
            )

        if not callable(
            getattr(
                registry,
                "list_properties",
                None,
            )
        ):
            raise MemoryValidationError(
                "registry must expose "
                "list_properties()"
            )

        self._registry = registry

    @staticmethod
    def _validate_kind(
        kind: PropertyKind,
    ) -> None:
        if not isinstance(
            kind,
            PropertyKind,
        ):
            raise MemoryValidationError(
                "kind must be PropertyKind"
            )

    @staticmethod
    def _validate_structural_request(
        *,
        kind: PropertyKind,
        cardinality: Cardinality,
        value_type: ValueType | None,
    ) -> None:
        (
            CanonicalPropertyCatalogReader
            ._validate_kind(
                kind
            )
        )

        if not isinstance(
            cardinality,
            Cardinality,
        ):
            raise MemoryValidationError(
                "cardinality must be "
                "Cardinality"
            )

        if kind is PropertyKind.FACT:
            if not isinstance(
                value_type,
                ValueType,
            ):
                raise MemoryValidationError(
                    "FACT property resolution "
                    "requires ValueType"
                )

        elif value_type is not None:
            raise MemoryValidationError(
                "RELATION property resolution "
                "forbids value_type"
            )

    def build_property_catalog(
        self,
        kind: PropertyKind,
        semantic_context: PropertySemanticContext,
    ) -> CandidateCatalog:
        self._validate_kind(
            kind
        )

        if not isinstance(
            semantic_context,
            PropertySemanticContext,
        ):
            raise MemoryValidationError(
                "semantic_context must be "
                "PropertySemanticContext"
            )

        properties = (
            self._registry
            .list_properties(
                kind=kind
            )
        )

        if not isinstance(
            properties,
            tuple,
        ):
            raise MemoryValidationError(
                "registry.list_properties() "
                "must return tuple"
            )

        candidates = []

        for property in properties:
            if not isinstance(
                property,
                CanonicalProperty,
            ):
                raise MemoryValidationError(
                    "registry returned invalid "
                    "canonical property"
                )

            if (
                property.kind
                is not kind
            ):
                raise MemoryValidationError(
                    "registry returned property "
                    "with wrong kind"
                )

            if (
                property.status
                is not MemoryStatus.ACTIVE
            ):
                continue

            candidates.append(
                CanonicalIdentityCandidate(
                    domain=(
                        CanonicalIdentityDomain
                        .PROPERTY
                    ),
                    canonical_id=(
                        property.id
                    ),
                    semantic_labels=(
                        property
                        .semantic_labels
                    ),
                    semantic_type=(
                        property
                        .semantic_type
                    ),
                )
            )

        return CandidateCatalog(
            domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            candidates=tuple(
                candidates
            ),
        )

    def validate_existing_property_contract(
        self,
        canonical_id: str,
        kind: PropertyKind,
        cardinality: Cardinality,
        value_type: ValueType | None,
    ) -> CanonicalProperty:
        require_text(
            canonical_id,
            "canonical_id",
        )

        self._validate_structural_request(
            kind=kind,
            cardinality=cardinality,
            value_type=value_type,
        )

        property = (
            self._registry
            .get_property(
                canonical_id
            )
        )

        if property is None:
            raise MemoryValidationError(
                "selected canonical property "
                "does not exist"
            )

        if not isinstance(
            property,
            CanonicalProperty,
        ):
            raise MemoryValidationError(
                "registry returned invalid "
                "canonical property"
            )

        if (
            property.status
            is not MemoryStatus.ACTIVE
        ):
            raise MemoryValidationError(
                "selected canonical property "
                "is not ACTIVE"
            )

        if (
            property.kind
            is not kind
        ):
            raise MemoryCanonicalContractMismatchError(
                "selected canonical property "
                "kind mismatch"
            )

        if (
            property.cardinality
            is not cardinality
        ):
            raise MemoryCanonicalContractMismatchError(
                "selected canonical property "
                "cardinality mismatch"
            )

        if kind is PropertyKind.FACT:
            if (
                property.value_type
                is not value_type
            ):
                raise MemoryCanonicalContractMismatchError(
                    "selected canonical property "
                    "value_type mismatch"
                )

        elif (
            property.value_type
            is not None
        ):
            raise MemoryCanonicalContractMismatchError(
                "selected relation property "
                "contains forbidden "
                "value_type"
            )

        return property

    def validate_existing_recall_property_contract(
        self,
        canonical_id: str,
        kind: PropertyKind,
    ) -> CanonicalProperty:
        require_text(
            canonical_id,
            "canonical_id",
        )

        self._validate_kind(
            kind
        )

        property = (
            self._registry
            .get_property(
                canonical_id
            )
        )

        if property is None:
            raise MemoryValidationError(
                "selected canonical property "
                "does not exist"
            )

        if not isinstance(
            property,
            CanonicalProperty,
        ):
            raise MemoryValidationError(
                "registry returned invalid "
                "canonical property"
            )

        if (
            property.status
            is not MemoryStatus.ACTIVE
        ):
            raise MemoryValidationError(
                "selected canonical property "
                "is not ACTIVE"
            )

        if (
            property.kind
            is not kind
        ):
            raise MemoryValidationError(
                "selected canonical property "
                "kind mismatch"
            )

        return property

    def resolve_recall_property_identity(
        self,
        matcher: SemanticIdentityMatcher,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
        kind: PropertyKind,
    ) -> RecallPropertyResolution:
        self._validate_kind(
            kind
        )

        context = PropertySemanticContext(
            semantic_labels=(
                semantic_labels
            ),
            semantic_type=(
                semantic_type
            ),
        )

        catalog = (
            self.build_property_catalog(
                kind,
                context,
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
                    .PROPERTY
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

            property = (
                self
                .validate_existing_recall_property_contract(
                    identity.canonical_id
                    or "",
                    kind,
                )
            )

            return RecallPropertyResolution(
                kind=kind,
                action=(
                    RecallPropertyResolutionAction
                    .EXISTING
                ),
                confidence=(
                    selection.confidence
                ),
                canonical_id=(
                    property.id
                ),
            )

        if (
            selection.action
            is IdentityResolutionAction
            .NEW
        ):
            return RecallPropertyResolution(
                kind=kind,
                action=(
                    RecallPropertyResolutionAction
                    .MISS
                ),
                confidence=(
                    selection.confidence
                ),
                canonical_id=None,
            )

        return RecallPropertyResolution(
            kind=kind,
            action=(
                RecallPropertyResolutionAction
                .AMBIGUOUS
            ),
            confidence=(
                selection.confidence
            ),
            canonical_id=None,
        )

    def resolve_property_identity(
        self,
        matcher: SemanticIdentityMatcher,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
        kind: PropertyKind,
        cardinality: Cardinality,
        value_type: ValueType | None,
    ) -> CanonicalIdentityResolution:
        self._validate_structural_request(
            kind=kind,
            cardinality=cardinality,
            value_type=value_type,
        )

        context = PropertySemanticContext(
            semantic_labels=(
                semantic_labels
            ),
            semantic_type=(
                semantic_type
            ),
        )

        catalog = (
            self.build_property_catalog(
                kind,
                context,
            )
        )

        # D417E2K6E1C3B4D_R2_F3B_EMPTY_REMEMBER_PROPERTY_CATALOG_IS_NEW
        if not catalog.candidates:
            return (
                catalog.resolve_selection(
                    IdentitySelection(
                        action=(
                            IdentityResolutionAction.NEW
                        ),
                        confidence=1.0,
                        selected_handle=None,
                    )
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
                .validate_existing_property_contract(
                    (
                        resolution
                        .canonical_id
                        or ""
                    ),
                    kind,
                    cardinality,
                    value_type,
                )
            )

        return resolution


__all__ = [
    'CanonicalPropertyCatalogReader',
    'CanonicalPropertyRegistryReader',
    'PropertySemanticContext',
    'RecallPropertyResolution',
    'RecallPropertyResolutionAction',
]
