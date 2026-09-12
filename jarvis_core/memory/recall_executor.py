from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sqlite3

from .availability import is_sqlite_availability_error
from .canonical_store import CanonicalMemoryStore
from .entity_resolution import RecallEntityResolutionAction
from .enums import PropertyKind
from .errors import MemoryAvailabilityError, MemoryValidationError
from .interpreter import MemoryOperation, PropertyQueryProposal, QueryTemporalMode
from .models import MemoryFact, MemoryRelation
from .property_resolution import RecallPropertyResolutionAction
from .resolution_plan import (
    MemoryResolutionPlan,
    RecallEntityRole,
    RecallPropertyRef,
)


class RecallItemOutcome(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    UNCERTAIN = "UNCERTAIN"
    UNAVAILABLE = "UNAVAILABLE"


class RecallAggregateOutcome(StrEnum):
    ALL_AVAILABLE = "ALL_AVAILABLE"
    PARTIAL = "PARTIAL"
    NONE_AVAILABLE = "NONE_AVAILABLE"


@dataclass(frozen=True, slots=True, order=True)
class FactRecallKey:
    subject_ref: str
    property_ref: RecallPropertyRef


@dataclass(frozen=True, slots=True, order=True)
class RelationRecallKey:
    source_ref: str
    property_ref: RecallPropertyRef
    target_ref: str | None


@dataclass(frozen=True, slots=True)
class RecallItemResult:
    key: FactRecallKey | RelationRecallKey
    outcome: RecallItemOutcome
    facts: tuple[MemoryFact, ...] = ()
    relations: tuple[MemoryRelation, ...] = ()

    def __post_init__(self) -> None:
        if self.outcome is RecallItemOutcome.AVAILABLE:
            if not self.facts and not self.relations:
                raise MemoryValidationError(
                    "AVAILABLE recall item requires canonical evidence"
                )
            return

        if self.facts or self.relations:
            raise MemoryValidationError(
                "non-AVAILABLE recall item cannot carry evidence"
            )


@dataclass(frozen=True, slots=True)
class MemoryRecallReadResult:
    """Immutable canonical evidence plus typed outcomes for one RECALL plan."""

    plan: MemoryResolutionPlan
    facts: tuple[MemoryFact, ...]
    relations: tuple[MemoryRelation, ...]
    items: tuple[RecallItemResult, ...] = ()
    aggregate: RecallAggregateOutcome = RecallAggregateOutcome.NONE_AVAILABLE
    relation_query_shape_ambiguous: bool = False
    interpretation_uncertain: bool = False
    infrastructure_unavailable: bool = False


def _stable_unique_rows(rows):
    result = []
    seen = set()
    for row in rows:
        identity = getattr(row, "id", None)
        key = (type(row), identity if identity is not None else id(row))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return tuple(result)


def _derive_aggregate(
    items: tuple[RecallItemResult, ...],
    *,
    relation_query_shape_ambiguous: bool,
    interpretation_uncertain: bool,
) -> RecallAggregateOutcome:
    available = sum(
        item.outcome is RecallItemOutcome.AVAILABLE
        for item in items
    )
    unresolved = (
        relation_query_shape_ambiguous
        or interpretation_uncertain
        or any(
            item.outcome is not RecallItemOutcome.AVAILABLE
            for item in items
        )
    )

    if available == 0:
        return RecallAggregateOutcome.NONE_AVAILABLE

    if unresolved:
        return RecallAggregateOutcome.PARTIAL

    return RecallAggregateOutcome.ALL_AVAILABLE


def _property_ref(query: PropertyQueryProposal) -> RecallPropertyRef:
    return RecallPropertyRef.from_query(query)


def _entity_resolution_state(plan: MemoryResolutionPlan):
    rows = {}
    for row in plan.recall_entities:
        if row.local_ref in rows:
            raise MemoryValidationError(
                "duplicate RECALL entity resolution"
            )
        rows[row.local_ref] = row.resolution

    failures = {}
    for failure in plan.recall_entity_resolution_failures:
        failures.setdefault(failure.local_ref, set()).add(failure.role)

    return rows, failures


def _property_resolution_state(plan: MemoryResolutionPlan):
    rows = {}
    for row in (
        plan.recall_fact_properties
        + plan.recall_relation_properties
    ):
        ref = _property_ref(row.query)
        key = (row.kind, ref)
        existing = rows.get(key)
        if existing is not None and existing != row.resolution:
            raise MemoryValidationError(
                "conflicting duplicate RECALL property resolution"
            )
        rows[key] = row.resolution

    failures = {
        (failure.kind, failure.property_ref)
        for failure in plan.recall_property_resolution_failures
    }
    return rows, failures


def _validate_resolution_coverage(
    plan: MemoryResolutionPlan,
    *,
    entity_rows,
    entity_failures,
    property_rows,
    property_failures,
) -> None:
    query = plan.interpretation.query
    if query is None:
        raise MemoryValidationError("RECALL requires query")

    for local_ref in tuple(dict.fromkeys(query.subject_refs + query.target_refs)):
        if local_ref not in entity_rows and local_ref not in entity_failures:
            raise MemoryValidationError(
                "RECALL entity reference has no resolution or availability failure"
            )

    for kind, proposals in (
        (PropertyKind.FACT, query.fact_properties),
        (PropertyKind.RELATION, query.relation_properties),
    ):
        for proposal in proposals:
            key = (kind, _property_ref(proposal))
            if key not in property_rows and key not in property_failures:
                raise MemoryValidationError(
                    "RECALL property query has no resolution or availability failure"
                )


def _entity_outcome(
    local_ref: str,
    *,
    role: RecallEntityRole,
    rows,
    failures,
):
    if role in failures.get(local_ref, set()):
        return RecallItemOutcome.UNAVAILABLE, None

    resolution = rows.get(local_ref)
    if resolution is None:
        raise MemoryValidationError(
            "RECALL entity role has no resolution"
        )

    if resolution.action is RecallEntityResolutionAction.MISS:
        return RecallItemOutcome.NOT_FOUND, None

    if resolution.action is RecallEntityResolutionAction.AMBIGUOUS:
        return RecallItemOutcome.UNCERTAIN, None

    if resolution.action is not RecallEntityResolutionAction.EXISTING:
        raise MemoryValidationError(
            "unsupported RECALL entity resolution action"
        )

    if not resolution.canonical_id:
        raise MemoryValidationError(
            "EXISTING RECALL entity requires canonical_id"
        )

    return None, resolution.canonical_id


def _property_outcome(
    kind: PropertyKind,
    ref: RecallPropertyRef,
    *,
    rows,
    failures,
):
    key = (kind, ref)
    if key in failures:
        return RecallItemOutcome.UNAVAILABLE, None

    resolution = rows.get(key)
    if resolution is None:
        raise MemoryValidationError(
            "RECALL property has no resolution"
        )

    if resolution.action is RecallPropertyResolutionAction.MISS:
        return RecallItemOutcome.NOT_FOUND, None

    if resolution.action is RecallPropertyResolutionAction.AMBIGUOUS:
        return RecallItemOutcome.UNCERTAIN, None

    if resolution.action is not RecallPropertyResolutionAction.EXISTING:
        raise MemoryValidationError(
            "unsupported RECALL property resolution action"
        )

    if not resolution.canonical_id:
        raise MemoryValidationError(
            "EXISTING RECALL property requires canonical_id"
        )

    return None, resolution.canonical_id


def _availability_read(call):
    try:
        return tuple(call())
    except MemoryAvailabilityError:
        raise
    except sqlite3.OperationalError as exc:
        if is_sqlite_availability_error(exc):
            raise MemoryAvailabilityError(
                "canonical memory read unavailable"
            ) from exc
        raise


def _query_fact_item(
    *,
    store: CanonicalMemoryStore,
    temporal_mode: QueryTemporalMode,
    as_of_revision: int | None,
    subject_id: str,
    property_id: str,
) -> tuple[MemoryFact, ...]:
    if temporal_mode is QueryTemporalMode.CURRENT:
        return _availability_read(
            lambda: store.query_current_facts(
                subject_entity_ids=(subject_id,),
                property_ids=(property_id,),
            )
        )

    if temporal_mode is QueryTemporalMode.HISTORICAL:
        return _availability_read(
            lambda: store.query_historical_facts(
                subject_entity_ids=(subject_id,),
                property_ids=(property_id,),
            )
        )

    if temporal_mode is QueryTemporalMode.AS_OF_REVISION:
        if as_of_revision is None:
            raise MemoryValidationError(
                "AS_OF_REVISION requires revision"
            )
        return _availability_read(
            lambda: store.query_facts_as_of_revision(
                revision=as_of_revision,
                subject_entity_ids=(subject_id,),
                property_ids=(property_id,),
            )
        )

    raise MemoryValidationError("unsupported RECALL temporal mode")


def _query_relation_item(
    *,
    store: CanonicalMemoryStore,
    temporal_mode: QueryTemporalMode,
    as_of_revision: int | None,
    source_id: str,
    property_id: str,
    target_id: str | None,
) -> tuple[MemoryRelation, ...]:
    if temporal_mode is QueryTemporalMode.CURRENT:
        rows = _availability_read(
            lambda: store.query_current_relations(
                source_entity_ids=(source_id,),
                property_ids=(property_id,),
            )
        )
    elif temporal_mode is QueryTemporalMode.HISTORICAL:
        rows = _availability_read(
            lambda: store.query_historical_relations(
                source_entity_ids=(source_id,),
                property_ids=(property_id,),
            )
        )
    elif temporal_mode is QueryTemporalMode.AS_OF_REVISION:
        if as_of_revision is None:
            raise MemoryValidationError(
                "AS_OF_REVISION requires revision"
            )
        rows = _availability_read(
            lambda: store.query_relations_as_of_revision(
                revision=as_of_revision,
                source_entity_ids=(source_id,),
                property_ids=(property_id,),
            )
        )
    else:
        raise MemoryValidationError("unsupported RECALL temporal mode")

    if target_id is None:
        return rows

    return tuple(
        row for row in rows
        if row.target_entity_id == target_id
    )


def _requested_item_keys(query):
    subject_ref = query.subject_refs[0]
    fact_keys = tuple(
        FactRecallKey(subject_ref, _property_ref(prop))
        for prop in query.fact_properties
    )

    relation_shape_ambiguous = (
        len(query.relation_properties) > 1
        and len(query.target_refs) > 1
    )

    relation_keys = []
    if not relation_shape_ambiguous:
        targets = query.target_refs or (None,)
        for prop in query.relation_properties:
            prop_ref = _property_ref(prop)
            for target_ref in targets:
                relation_keys.append(
                    RelationRecallKey(
                        subject_ref,
                        prop_ref,
                        target_ref,
                    )
                )

    # Same semantic request-local item collapses deterministically.
    return (
        tuple(dict.fromkeys(fact_keys)),
        tuple(dict.fromkeys(relation_keys)),
        relation_shape_ambiguous,
    )


def execute_memory_recall_plan(
    plan: MemoryResolutionPlan,
    *,
    store: CanonicalMemoryStore,
) -> MemoryRecallReadResult:
    """Execute RECALL item-by-item against canonical reads only."""

    if not isinstance(plan, MemoryResolutionPlan):
        raise MemoryValidationError("plan must be MemoryResolutionPlan")

    interpretation = plan.interpretation
    if interpretation.operation is not MemoryOperation.RECALL:
        raise MemoryValidationError("recall executor supports RECALL only")

    query = interpretation.query
    if query is None:
        raise MemoryValidationError("RECALL requires query")

    if not query.subject_refs:
        raise MemoryValidationError(
            "RECALL canonical read requires subject_refs"
        )

    if len(query.subject_refs) > 1:
        raise MemoryValidationError(
            "Memory1.0 RECALL supports one subject_ref per turn"
        )

    if not query.fact_properties and not query.relation_properties:
        raise MemoryValidationError(
            "RECALL canonical read requires an explicit property query"
        )

    fact_keys, relation_keys, relation_shape_ambiguous = (
        _requested_item_keys(query)
    )

    if interpretation.needs_confirmation or interpretation.ambiguities:
        return MemoryRecallReadResult(
            plan=plan,
            facts=(),
            relations=(),
            items=(),
            aggregate=RecallAggregateOutcome.NONE_AVAILABLE,
            relation_query_shape_ambiguous=relation_shape_ambiguous,
            interpretation_uncertain=True,
        )

    entity_rows, entity_failures = _entity_resolution_state(plan)
    property_rows, property_failures = _property_resolution_state(plan)
    _validate_resolution_coverage(
        plan,
        entity_rows=entity_rows,
        entity_failures=entity_failures,
        property_rows=property_rows,
        property_failures=property_failures,
    )

    try:
        store.assert_readable()
    except MemoryAvailabilityError:
        items = tuple(
            RecallItemResult(key, RecallItemOutcome.UNAVAILABLE)
            for key in (*fact_keys, *relation_keys)
        )
        return MemoryRecallReadResult(
            plan=plan,
            facts=(),
            relations=(),
            items=items,
            aggregate=_derive_aggregate(
                items,
                relation_query_shape_ambiguous=relation_shape_ambiguous,
                interpretation_uncertain=False,
            ),
            relation_query_shape_ambiguous=relation_shape_ambiguous,
            infrastructure_unavailable=True,
        )

    subject_ref = query.subject_refs[0]
    subject_outcome, subject_id = _entity_outcome(
        subject_ref,
        role=RecallEntityRole.SUBJECT,
        rows=entity_rows,
        failures=entity_failures,
    )

    items = []

    for key in fact_keys:
        prop_outcome, property_id = _property_outcome(
            PropertyKind.FACT,
            key.property_ref,
            rows=property_rows,
            failures=property_failures,
        )

        outcome = subject_outcome or prop_outcome
        if outcome is not None:
            items.append(RecallItemResult(key, outcome))
            continue

        try:
            facts = _query_fact_item(
                store=store,
                temporal_mode=query.temporal_mode,
                as_of_revision=query.as_of_revision,
                subject_id=subject_id,
                property_id=property_id,
            )
        except MemoryAvailabilityError:
            items.append(
                RecallItemResult(key, RecallItemOutcome.UNAVAILABLE)
            )
            continue

        if facts:
            items.append(
                RecallItemResult(
                    key,
                    RecallItemOutcome.AVAILABLE,
                    facts=facts,
                )
            )
        else:
            items.append(
                RecallItemResult(key, RecallItemOutcome.NOT_FOUND)
            )

    for key in relation_keys:
        prop_outcome, property_id = _property_outcome(
            PropertyKind.RELATION,
            key.property_ref,
            rows=property_rows,
            failures=property_failures,
        )

        target_outcome = None
        target_id = None
        if key.target_ref is not None:
            target_outcome, target_id = _entity_outcome(
                key.target_ref,
                role=RecallEntityRole.TARGET,
                rows=entity_rows,
                failures=entity_failures,
            )

        outcome = subject_outcome or prop_outcome or target_outcome
        if outcome is not None:
            items.append(RecallItemResult(key, outcome))
            continue

        try:
            relations = _query_relation_item(
                store=store,
                temporal_mode=query.temporal_mode,
                as_of_revision=query.as_of_revision,
                source_id=subject_id,
                property_id=property_id,
                target_id=target_id,
            )
        except MemoryAvailabilityError:
            items.append(
                RecallItemResult(key, RecallItemOutcome.UNAVAILABLE)
            )
            continue

        if relations:
            items.append(
                RecallItemResult(
                    key,
                    RecallItemOutcome.AVAILABLE,
                    relations=relations,
                )
            )
        else:
            items.append(
                RecallItemResult(key, RecallItemOutcome.NOT_FOUND)
            )

    items_tuple = tuple(items)
    facts = _stable_unique_rows(
        tuple(
            fact
            for item in items_tuple
            for fact in item.facts
        )
    )
    relations = _stable_unique_rows(
        tuple(
            relation
            for item in items_tuple
            for relation in item.relations
        )
    )

    return MemoryRecallReadResult(
        plan=plan,
        facts=facts,
        relations=relations,
        items=items_tuple,
        aggregate=_derive_aggregate(
            items_tuple,
            relation_query_shape_ambiguous=relation_shape_ambiguous,
            interpretation_uncertain=False,
        ),
        relation_query_shape_ambiguous=relation_shape_ambiguous,
    )


__all__ = [
    "FactRecallKey",
    "MemoryRecallReadResult",
    "RecallAggregateOutcome",
    "RecallItemOutcome",
    "RecallItemResult",
    "RelationRecallKey",
    "execute_memory_recall_plan",
]
