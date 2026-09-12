from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sqlite3

from .entity_bindings import (
    TrustedEntityBindings,
)
from .entity_resolution import (
    CanonicalEntityCatalogReader,
    CanonicalEntityRegistryReader,
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from .enums import (
    PropertyKind,
)
from .availability import is_sqlite_availability_error
from .errors import (
    MemoryAvailabilityError,
    MemoryValidationError,
)
from .interpreter import (
    EntityProposal,
    EntityQueryProposal,
    MemoryInterpretation,
    MemoryOperation,
    PropertyProposal,
    PropertyQueryProposal,
)
from .property_resolution import (
    CanonicalPropertyCatalogReader,
    CanonicalPropertyRegistryReader,
    RecallPropertyResolution,
)
from .resolution import (
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
    SemanticIdentityMatcher,
)


@dataclass(frozen=True, slots=True)
class RememberEntityReferenceResolution:
    local_ref: str
    proposal: EntityProposal | None
    resolution: CanonicalIdentityResolution
    trusted_binding: bool


@dataclass(frozen=True, slots=True)
class RememberPropertyResolution:
    local_ref: str
    kind: PropertyKind
    proposal: PropertyProposal
    resolution: CanonicalIdentityResolution


@dataclass(frozen=True, slots=True)
class RecallEntityReferenceResolution:
    local_ref: str
    query: EntityQueryProposal | None
    resolution: RecallEntityResolution
    trusted_binding: bool


@dataclass(frozen=True, slots=True)
class RecallPropertyQueryResolution:
    kind: PropertyKind
    query: PropertyQueryProposal
    resolution: RecallPropertyResolution


class RecallEntityRole(StrEnum):
    SUBJECT = "SUBJECT"
    TARGET = "TARGET"


@dataclass(frozen=True, slots=True, order=True)
class RecallPropertyRef:
    semantic_labels: tuple[str, ...]
    semantic_type: str

    @classmethod
    def from_query(
        cls,
        query: PropertyQueryProposal,
    ) -> "RecallPropertyRef":
        return cls(
            semantic_labels=tuple(sorted(query.semantic_labels)),
            semantic_type=query.semantic_type,
        )


@dataclass(frozen=True, slots=True)
class RecallEntityResolutionFailure:
    local_ref: str
    role: RecallEntityRole


@dataclass(frozen=True, slots=True)
class RecallPropertyResolutionFailure:
    property_ref: RecallPropertyRef
    kind: PropertyKind


@dataclass(frozen=True, slots=True)
class MemoryResolutionPlan:
    interpretation: MemoryInterpretation
    remember_entities: tuple[
        RememberEntityReferenceResolution,
        ...,
    ] = ()
    remember_fact_properties: tuple[
        RememberPropertyResolution,
        ...,
    ] = ()
    remember_relation_properties: tuple[
        RememberPropertyResolution,
        ...,
    ] = ()
    recall_entities: tuple[
        RecallEntityReferenceResolution,
        ...,
    ] = ()
    recall_fact_properties: tuple[
        RecallPropertyQueryResolution,
        ...,
    ] = ()
    recall_relation_properties: tuple[
        RecallPropertyQueryResolution,
        ...,
    ] = ()
    recall_entity_resolution_failures: tuple[
        RecallEntityResolutionFailure,
        ...,
    ] = ()
    recall_property_resolution_failures: tuple[
        RecallPropertyResolutionFailure,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.interpretation,
            MemoryInterpretation,
        ):
            raise MemoryValidationError(
                "MemoryResolutionPlan.interpretation "
                "must be MemoryInterpretation"
            )

        operation = (
            self.interpretation.operation
        )

        remember_rows = (
            self.remember_entities
            or self.remember_fact_properties
            or self.remember_relation_properties
        )

        recall_rows = (
            self.recall_entities
            or self.recall_fact_properties
            or self.recall_relation_properties
            or self.recall_entity_resolution_failures
            or self.recall_property_resolution_failures
        )

        if (
            operation
            is MemoryOperation.NONE
            and (
                remember_rows
                or recall_rows
            )
        ):
            raise MemoryValidationError(
                "NONE resolution plan "
                "must be empty"
            )

        if (
            operation
            is MemoryOperation.REMEMBER
            and recall_rows
        ):
            raise MemoryValidationError(
                "REMEMBER resolution plan "
                "cannot contain recall rows"
            )

        if (
            operation
            is MemoryOperation.RECALL
            and remember_rows
        ):
            raise MemoryValidationError(
                "RECALL resolution plan "
                "cannot contain remember rows"
            )


def _stable_unique(
    values: tuple[str, ...],
) -> tuple[str, ...]:
    result = []
    seen = set()

    for value in values:
        if value in seen:
            continue

        seen.add(
            value
        )
        result.append(
            value
        )

    return tuple(
        result
    )


def _remember_entity_references(
    interpretation: MemoryInterpretation,
) -> tuple[str, ...]:
    refs = []

    for fact in interpretation.facts:
        refs.append(
            fact.subject_ref
        )

        if (
            fact.value_entity_ref
            is not None
        ):
            refs.append(
                fact.value_entity_ref
            )

    for relation in (
        interpretation.relations
    ):
        refs.append(
            relation.source_ref
        )
        refs.append(
            relation.target_ref
        )

    return _stable_unique(
        tuple(refs)
    )


def _recall_entity_references(
    interpretation: MemoryInterpretation,
) -> tuple[str, ...]:
    query = interpretation.query

    if query is None:
        raise MemoryValidationError(
            "RECALL interpretation "
            "requires query"
        )

    return _stable_unique(
        (
            *query.subject_refs,
            *query.target_refs,
        )
    )


def _entity_proposal_index(
    interpretation: MemoryInterpretation,
) -> dict[str, EntityProposal]:
    result = {}

    for proposal in (
        interpretation.entities
    ):
        if (
            proposal.local_ref
            in result
        ):
            raise MemoryValidationError(
                "duplicate entity proposal "
                "local_ref"
            )

        result[
            proposal.local_ref
        ] = proposal

    return result


def _entity_query_index(
    interpretation: MemoryInterpretation,
) -> dict[str, EntityQueryProposal]:
    query = interpretation.query

    if query is None:
        raise MemoryValidationError(
            "RECALL interpretation "
            "requires query"
        )

    result = {}

    for proposal in (
        query.entity_queries
    ):
        if (
            proposal.local_ref
            in result
        ):
            raise MemoryValidationError(
                "duplicate entity query "
                "local_ref"
            )

        result[
            proposal.local_ref
        ] = proposal

    return result


def _trusted_remember_entity_resolution(
    reader: CanonicalEntityCatalogReader,
    canonical_id: str,
) -> CanonicalIdentityResolution:
    entity = (
        reader
        .validate_existing_entity_contract(
            canonical_id
        )
    )

    return CanonicalIdentityResolution(
        domain=(
            CanonicalIdentityDomain
            .ENTITY
        ),
        action=(
            IdentityResolutionAction
            .EXISTING
        ),
        confidence=1.0,
        canonical_id=entity.id,
    )


def _trusted_recall_entity_resolution(
    reader: CanonicalEntityCatalogReader,
    canonical_id: str,
) -> RecallEntityResolution:
    entity = (
        reader
        .validate_existing_recall_entity_contract(
            canonical_id
        )
    )

    return RecallEntityResolution(
        action=(
            RecallEntityResolutionAction
            .EXISTING
        ),
        confidence=1.0,
        canonical_id=entity.id,
    )


def _build_remember_entities(
    interpretation: MemoryInterpretation,
    *,
    matcher: SemanticIdentityMatcher,
    reader: CanonicalEntityCatalogReader,
    trusted_entity_bindings: TrustedEntityBindings,
) -> tuple[
    RememberEntityReferenceResolution,
    ...,
]:
    proposal_index = (
        _entity_proposal_index(
            interpretation
        )
    )

    used_proposals = set()
    rows = []

    for local_ref in (
        _remember_entity_references(
            interpretation
        )
    ):
        proposal = (
            proposal_index.get(
                local_ref
            )
        )

        if (
            trusted_entity_bindings
            .contains(
                local_ref
            )
        ):
            if proposal is not None:
                used_proposals.add(
                    local_ref
                )

            canonical_id = (
                trusted_entity_bindings
                .canonical_id_for(
                    local_ref
                )
            )

            rows.append(
                RememberEntityReferenceResolution(
                    local_ref=local_ref,
                    proposal=proposal,
                    resolution=(
                        _trusted_remember_entity_resolution(
                            reader,
                            canonical_id,
                        )
                    ),
                    trusted_binding=True,
                )
            )

            continue

        if proposal is None:
            raise MemoryValidationError(
                "unbound REMEMBER entity "
                "reference requires "
                "EntityProposal"
            )

        used_proposals.add(
            local_ref
        )

        semantic_labels = (
            proposal.canonical_name,
            *proposal.aliases,
        )

        rows.append(
            RememberEntityReferenceResolution(
                local_ref=local_ref,
                proposal=proposal,
                resolution=(
                    reader
                    .resolve_entity_identity(
                        matcher,
                        semantic_labels,
                        proposal.entity_type,
                    )
                ),
                trusted_binding=False,
            )
        )

    return tuple(
        rows
    )


def _build_remember_properties(
    proposals: tuple[
        PropertyProposal,
        ...,
    ],
    *,
    kind: PropertyKind,
    matcher: SemanticIdentityMatcher,
    reader: CanonicalPropertyCatalogReader,
) -> tuple[
    RememberPropertyResolution,
    ...,
]:
    rows = []

    for proposal in proposals:
        resolution = (
            reader
            .resolve_property_identity(
                matcher,
                proposal.semantic_labels,
                proposal.semantic_type,
                kind,
                proposal.cardinality,
                (
                    proposal.value_type
                    if (
                        kind
                        is PropertyKind.FACT
                    )
                    else None
                ),
            )
        )

        rows.append(
            RememberPropertyResolution(
                local_ref=(
                    proposal.local_ref
                ),
                kind=kind,
                proposal=proposal,
                resolution=resolution,
            )
        )

    return tuple(
        rows
    )


def _validate_remember_property_links(
    interpretation: MemoryInterpretation,
    *,
    fact_rows: tuple[
        RememberPropertyResolution,
        ...,
    ],
    relation_rows: tuple[
        RememberPropertyResolution,
        ...,
    ],
) -> None:
    fact_refs = {
        row.local_ref
        for row in fact_rows
    }

    relation_refs = {
        row.local_ref
        for row in relation_rows
    }

    for fact in interpretation.facts:
        if (
            fact.property_ref
            not in fact_refs
        ):
            raise MemoryValidationError(
                "FactProposal.property_ref "
                "has no resolved FACT property"
            )

    for relation in (
        interpretation.relations
    ):
        if (
            relation.property_ref
            not in relation_refs
        ):
            raise MemoryValidationError(
                "RelationProposal.property_ref "
                "has no resolved RELATION property"
            )


def _entity_failure_roles(
    local_ref: str,
    *,
    subject_refs: tuple[str, ...],
    target_refs: tuple[str, ...],
) -> tuple[RecallEntityRole, ...]:
    roles = []

    if local_ref in subject_refs:
        roles.append(RecallEntityRole.SUBJECT)

    if local_ref in target_refs:
        roles.append(RecallEntityRole.TARGET)

    return tuple(roles)


def _build_recall_entities(
    interpretation: MemoryInterpretation,
    *,
    matcher: SemanticIdentityMatcher,
    reader: CanonicalEntityCatalogReader,
    trusted_entity_bindings: TrustedEntityBindings,
) -> tuple[
    tuple[RecallEntityReferenceResolution, ...],
    tuple[RecallEntityResolutionFailure, ...],
]:
    query = interpretation.query

    if query is None:
        raise MemoryValidationError(
            "RECALL interpretation requires query"
        )

    query_index = _entity_query_index(interpretation)
    used_queries = set()
    rows = []
    failures = []

    for local_ref in _recall_entity_references(interpretation):
        query_proposal = query_index.get(local_ref)

        if trusted_entity_bindings.contains(local_ref):
            if query_proposal is not None:
                used_queries.add(local_ref)

            canonical_id = trusted_entity_bindings.canonical_id_for(local_ref)

            try:
                resolution = _trusted_recall_entity_resolution(
                    reader, canonical_id
                )
            except MemoryAvailabilityError:
                for role in _entity_failure_roles(
                    local_ref,
                    subject_refs=query.subject_refs,
                    target_refs=query.target_refs,
                ):
                    failures.append(
                        RecallEntityResolutionFailure(
                            local_ref=local_ref,
                            role=role,
                        )
                    )
                continue
            except sqlite3.OperationalError as exc:
                if not is_sqlite_availability_error(exc):
                    raise
                for role in _entity_failure_roles(
                    local_ref,
                    subject_refs=query.subject_refs,
                    target_refs=query.target_refs,
                ):
                    failures.append(
                        RecallEntityResolutionFailure(
                            local_ref=local_ref,
                            role=role,
                        )
                    )
                continue

            rows.append(
                RecallEntityReferenceResolution(
                    local_ref=local_ref,
                    query=query_proposal,
                    resolution=resolution,
                    trusted_binding=True,
                )
            )
            continue

        if query_proposal is None:
            raise MemoryValidationError(
                "unbound RECALL entity reference requires EntityQueryProposal"
            )

        used_queries.add(local_ref)

        try:
            resolution = reader.resolve_recall_entity_identity(
                matcher,
                query_proposal.semantic_labels,
                query_proposal.semantic_type,
            )
        except MemoryAvailabilityError:
            for role in _entity_failure_roles(
                local_ref,
                subject_refs=query.subject_refs,
                target_refs=query.target_refs,
            ):
                failures.append(
                    RecallEntityResolutionFailure(
                        local_ref=local_ref,
                        role=role,
                    )
                )
            continue
        except sqlite3.OperationalError as exc:
            if not is_sqlite_availability_error(exc):
                raise
            for role in _entity_failure_roles(
                local_ref,
                subject_refs=query.subject_refs,
                target_refs=query.target_refs,
            ):
                failures.append(
                    RecallEntityResolutionFailure(
                        local_ref=local_ref,
                        role=role,
                    )
                )
            continue

        rows.append(
            RecallEntityReferenceResolution(
                local_ref=local_ref,
                query=query_proposal,
                resolution=resolution,
                trusted_binding=False,
            )
        )

    unused = set(query_index) - used_queries
    if unused:
        raise MemoryValidationError("unused entity query")

    return tuple(rows), tuple(failures)


def _build_recall_properties(
    proposals: tuple[PropertyQueryProposal, ...],
    *,
    kind: PropertyKind,
    matcher: SemanticIdentityMatcher,
    reader: CanonicalPropertyCatalogReader,
) -> tuple[
    tuple[RecallPropertyQueryResolution, ...],
    tuple[RecallPropertyResolutionFailure, ...],
]:
    rows = []
    failures = []

    for proposal in proposals:
        try:
            resolution = reader.resolve_recall_property_identity(
                matcher,
                proposal.semantic_labels,
                proposal.semantic_type,
                kind,
            )
        except MemoryAvailabilityError:
            failures.append(
                RecallPropertyResolutionFailure(
                    property_ref=RecallPropertyRef.from_query(proposal),
                    kind=kind,
                )
            )
            continue
        except sqlite3.OperationalError as exc:
            if not is_sqlite_availability_error(exc):
                raise
            failures.append(
                RecallPropertyResolutionFailure(
                    property_ref=RecallPropertyRef.from_query(proposal),
                    kind=kind,
                )
            )
            continue

        rows.append(
            RecallPropertyQueryResolution(
                kind=kind,
                query=proposal,
                resolution=resolution,
            )
        )

    return tuple(rows), tuple(failures)



def remember_plan_has_ambiguous_identity(
    plan: MemoryResolutionPlan,
) -> bool:
    """Return whether a REMEMBER plan contains any unresolved ambiguous identity."""

    if not isinstance(plan, MemoryResolutionPlan):
        raise MemoryValidationError(
            "plan must be MemoryResolutionPlan"
        )

    if plan.interpretation.operation is not MemoryOperation.REMEMBER:
        raise MemoryValidationError(
            "remember ambiguity inspection requires a REMEMBER plan"
        )

    rows = (
        plan.remember_entities
        + plan.remember_fact_properties
        + plan.remember_relation_properties
    )

    return any(
        row.resolution.action is IdentityResolutionAction.AMBIGUOUS
        for row in rows
    )

def build_memory_resolution_plan(
    interpretation: MemoryInterpretation,
    *,
    matcher: SemanticIdentityMatcher,
    entity_registry: CanonicalEntityRegistryReader,
    property_registry: CanonicalPropertyRegistryReader,
    trusted_entity_bindings: TrustedEntityBindings,
) -> MemoryResolutionPlan:
    if not isinstance(
        interpretation,
        MemoryInterpretation,
    ):
        raise MemoryValidationError(
            "interpretation must be "
            "MemoryInterpretation"
        )

    if not isinstance(
        trusted_entity_bindings,
        TrustedEntityBindings,
    ):
        raise MemoryValidationError(
            "trusted_entity_bindings "
            "must be TrustedEntityBindings"
        )

    operation = (
        interpretation.operation
    )

    if (
        operation
        is MemoryOperation.NONE
    ):
        return MemoryResolutionPlan(
            interpretation=interpretation
        )

    if operation not in {
        MemoryOperation.REMEMBER,
        MemoryOperation.RECALL,
    }:
        raise MemoryValidationError(
            "resolution planning does "
            "not support this operation"
        )

    entity_reader = (
        CanonicalEntityCatalogReader(
            entity_registry
        )
    )

    property_reader = (
        CanonicalPropertyCatalogReader(
            property_registry
        )
    )

    if (
        operation
        is MemoryOperation.REMEMBER
    ):
        from .proposal_validation import (
            validate_new_entity_literal_wrappers,
            validate_remember_entity_proposal_usage,
        )

        validate_remember_entity_proposal_usage(
            interpretation
        )

        remember_entities = (
            _build_remember_entities(
                interpretation,
                matcher=matcher,
                reader=entity_reader,
                trusted_entity_bindings=(
                    trusted_entity_bindings
                ),
            )
        )

        validate_new_entity_literal_wrappers(
            interpretation,
            new_entity_refs=tuple(
                row.local_ref
                for row in remember_entities
                if (
                    row.resolution.action
                    is IdentityResolutionAction.NEW
                )
            ),
        )

        remember_fact_properties = (
            _build_remember_properties(
                interpretation
                .fact_properties,
                kind=PropertyKind.FACT,
                matcher=matcher,
                reader=property_reader,
            )
        )

        remember_relation_properties = (
            _build_remember_properties(
                interpretation
                .relation_properties,
                kind=(
                    PropertyKind.RELATION
                ),
                matcher=matcher,
                reader=property_reader,
            )
        )

        _validate_remember_property_links(
            interpretation,
            fact_rows=(
                remember_fact_properties
            ),
            relation_rows=(
                remember_relation_properties
            ),
        )

        return MemoryResolutionPlan(
            interpretation=interpretation,
            remember_entities=(
                remember_entities
            ),
            remember_fact_properties=(
                remember_fact_properties
            ),
            remember_relation_properties=(
                remember_relation_properties
            ),
        )

    query = interpretation.query

    if query is None:
        raise MemoryValidationError(
            "RECALL interpretation "
            "requires query"
        )

    (
        recall_entities,
        recall_entity_resolution_failures,
    ) = _build_recall_entities(
        interpretation,
        matcher=matcher,
        reader=entity_reader,
        trusted_entity_bindings=trusted_entity_bindings,
    )

    (
        recall_fact_properties,
        fact_property_resolution_failures,
    ) = _build_recall_properties(
        query.fact_properties,
        kind=PropertyKind.FACT,
        matcher=matcher,
        reader=property_reader,
    )

    (
        recall_relation_properties,
        relation_property_resolution_failures,
    ) = _build_recall_properties(
        query.relation_properties,
        kind=PropertyKind.RELATION,
        matcher=matcher,
        reader=property_reader,
    )

    recall_property_resolution_failures = (
        fact_property_resolution_failures
        + relation_property_resolution_failures
    )

    return MemoryResolutionPlan(
        interpretation=interpretation,
        recall_entities=(
            recall_entities
        ),
        recall_fact_properties=(
            recall_fact_properties
        ),
        recall_relation_properties=(
            recall_relation_properties
        ),
        recall_entity_resolution_failures=(
            recall_entity_resolution_failures
        ),
        recall_property_resolution_failures=(
            recall_property_resolution_failures
        ),
    )
