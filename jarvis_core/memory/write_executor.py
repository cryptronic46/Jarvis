from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from .canonical_store import (
    CanonicalMemoryStore,
)
from .enums import (
    Cardinality,
    MemoryAuthority,
    MemoryStatus,
    PropertyKind,
    SourceType,
    ValueType,
)
from .errors import (
    MemoryIntegrityError,
    MemoryValidationError,
)
from .ids import (
    new_memory_id,
)
from .interpreter import (
    MemoryOperation,
)
from .models import (
    CanonicalProperty,
    Entity,
    MemoryCommitReceipt,
    MemoryEpisode,
    MemoryFact,
    MemoryRelation,
    MemoryValue,
)
from .resolution import (
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
)
from .resolution_plan import (
    MemoryResolutionPlan,
    RememberEntityReferenceResolution,
    RememberPropertyResolution,
)


@dataclass(
    frozen=True,
    slots=True,
)
class TrustedWriteExecutionContext:
    raw_text: str
    source_type: SourceType
    authority: MemoryAuthority
    occurred_at: datetime
    recorded_at: datetime
    actor_entity_id: str | None = None
    speaker_entity_id: str | None = None
    conversation_id: str | None = None
    sequence: int | None = None

    def __post_init__(
        self,
    ) -> None:
        _require_text(
            self.raw_text,
            "context.raw_text",
        )

        if not isinstance(
            self.source_type,
            SourceType,
        ):
            raise MemoryValidationError(
                "context.source_type must "
                "be SourceType"
            )

        if not isinstance(
            self.authority,
            MemoryAuthority,
        ):
            raise MemoryValidationError(
                "context.authority must "
                "be MemoryAuthority"
            )

        _require_aware(
            self.occurred_at,
            "context.occurred_at",
        )

        _require_aware(
            self.recorded_at,
            "context.recorded_at",
        )

        _require_optional_text(
            self.actor_entity_id,
            "context.actor_entity_id",
        )

        _require_optional_text(
            self.speaker_entity_id,
            "context.speaker_entity_id",
        )

        _require_optional_text(
            self.conversation_id,
            "context.conversation_id",
        )

        if (
            self.sequence is not None
            and type(self.sequence)
            is not int
        ):
            raise MemoryValidationError(
                "context.sequence must "
                "be int or None"
            )


def _require_text(
    value: object,
    name: str,
) -> str:
    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise MemoryValidationError(
            f"{name} must be "
            "non-empty text"
        )

    return value


def _require_optional_text(
    value: str | None,
    name: str,
) -> None:
    if value is None:
        return

    _require_text(
        value,
        name,
    )


def _require_aware(
    value: object,
    name: str,
) -> datetime:
    if not isinstance(
        value,
        datetime,
    ):
        raise MemoryValidationError(
            f"{name} must be datetime"
        )

    if (
        value.tzinfo is None
        or value.utcoffset()
        is None
    ):
        raise MemoryValidationError(
            f"{name} must be "
            "timezone-aware"
        )

    return value


def _parse_temporal(
    value: str | None,
    name: str,
) -> datetime | None:
    if value is None:
        return None

    _require_text(
        value,
        name,
    )

    if value != value.strip():
        raise MemoryValidationError(
            f"{name} must not contain "
            "surrounding whitespace"
        )

    try:
        parsed = datetime.fromisoformat(
            value
        )

    except ValueError as exc:
        raise MemoryValidationError(
            f"{name} must be a strict "
            "ISO-8601 datetime"
        ) from exc

    return _require_aware(
        parsed,
        name,
    )


def _require_context_entity(
    *,
    store: CanonicalMemoryStore,
    entity_id: str | None,
    name: str,
) -> None:
    if entity_id is None:
        return

    if (
        store.get_entity(
            entity_id
        )
        is None
    ):
        raise MemoryValidationError(
            f"{name} must reference "
            "an existing canonical entity"
        )


def _canonical_id(
    resolution: CanonicalIdentityResolution,
    *,
    expected_domain: CanonicalIdentityDomain,
    name: str,
) -> str:
    if not isinstance(
        resolution,
        CanonicalIdentityResolution,
    ):
        raise MemoryValidationError(
            f"{name}.resolution must be "
            "CanonicalIdentityResolution"
        )

    if (
        resolution.domain
        is not expected_domain
    ):
        raise MemoryValidationError(
            f"{name}.resolution has "
            "wrong canonical domain"
        )

    if (
        resolution.action
        is IdentityResolutionAction.AMBIGUOUS
    ):
        raise MemoryValidationError(
            f"{name}.resolution is "
            "ambiguous"
        )

    canonical_id = (
        resolution.canonical_id
    )

    _require_text(
        canonical_id,
        f"{name}.canonical_id",
    )

    return canonical_id


def _entity_index(
    *,
    plan: MemoryResolutionPlan,
    store: CanonicalMemoryStore,
) -> tuple[
    dict[str, str],
    tuple[
        RememberEntityReferenceResolution,
        ...,
    ],
    tuple[str, ...],
]:
    by_ref: dict[str, str] = {}

    new_rows = []

    existing_ids = []

    new_ids = set()

    for row in (
        plan.remember_entities
    ):
        if (
            row.local_ref
            in by_ref
        ):
            raise MemoryValidationError(
                "duplicate remember "
                "entity local_ref"
            )

        canonical_id = _canonical_id(
            row.resolution,
            expected_domain=(
                CanonicalIdentityDomain
                .ENTITY
            ),
            name=(
                "remember entity "
                + row.local_ref
            ),
        )

        if (
            row.proposal is not None
            and row.proposal.local_ref
            != row.local_ref
        ):
            raise MemoryValidationError(
                "remember entity "
                "proposal local_ref "
                "does not match row"
            )

        if (
            row.resolution.action
            is IdentityResolutionAction
            .EXISTING
        ):
            if (
                store.get_entity(
                    canonical_id
                )
                is None
            ):
                raise MemoryValidationError(
                    "resolved existing "
                    "entity does not exist"
                )

            existing_ids.append(
                canonical_id
            )

        elif (
            row.resolution.action
            is IdentityResolutionAction
            .NEW
        ):
            if row.proposal is None:
                raise MemoryValidationError(
                    "NEW entity resolution "
                    "requires proposal"
                )

            if (
                row.proposal.namespace_hint
                is None
            ):
                raise MemoryValidationError(
                    "NEW entity requires "
                    "namespace_hint"
                )

            if (
                store.get_entity(
                    canonical_id
                )
                is not None
            ):
                raise MemoryValidationError(
                    "NEW entity canonical_id "
                    "already exists"
                )

            if (
                canonical_id
                in new_ids
            ):
                raise MemoryValidationError(
                    "duplicate NEW entity "
                    "canonical_id"
                )

            new_ids.add(
                canonical_id
            )

            new_rows.append(
                row
            )

        else:
            raise MemoryValidationError(
                "unsupported entity "
                "resolution action"
            )

        by_ref[
            row.local_ref
        ] = canonical_id

    return (
        by_ref,
        tuple(
            new_rows
        ),
        tuple(
            dict.fromkeys(
                existing_ids
            )
        ),
    )


def _property_index(
    rows: tuple[
        RememberPropertyResolution,
        ...,
    ],
    *,
    expected_kind: PropertyKind,
    store: CanonicalMemoryStore,
    recorded_at: datetime,
) -> tuple[
    dict[str, CanonicalProperty],
    tuple[CanonicalProperty, ...],
]:
    by_ref: dict[
        str,
        CanonicalProperty,
    ] = {}

    new_properties = []

    new_ids = set()

    for row in rows:
        if (
            row.local_ref
            in by_ref
        ):
            raise MemoryValidationError(
                "duplicate remember "
                "property local_ref"
            )

        if (
            row.kind
            is not expected_kind
        ):
            raise MemoryValidationError(
                "remember property kind "
                "does not match lane"
            )

        if (
            row.proposal.local_ref
            != row.local_ref
        ):
            raise MemoryValidationError(
                "remember property "
                "proposal local_ref "
                "does not match row"
            )

        canonical_id = _canonical_id(
            row.resolution,
            expected_domain=(
                CanonicalIdentityDomain
                .PROPERTY
            ),
            name=(
                "remember property "
                + row.local_ref
            ),
        )

        if (
            row.resolution.action
            is IdentityResolutionAction
            .EXISTING
        ):
            canonical_property = (
                store.get_property(
                    canonical_id
                )
            )

            if (
                canonical_property
                is None
            ):
                raise MemoryValidationError(
                    "resolved existing "
                    "property does not exist"
                )

            if (
                canonical_property.kind
                is not expected_kind
            ):
                raise MemoryValidationError(
                    "resolved existing "
                    "property has wrong kind"
                )

        elif (
            row.resolution.action
            is IdentityResolutionAction
            .NEW
        ):
            if (
                store.get_property(
                    canonical_id
                )
                is not None
            ):
                raise MemoryValidationError(
                    "NEW property canonical_id "
                    "already exists"
                )

            if (
                canonical_id
                in new_ids
            ):
                raise MemoryValidationError(
                    "duplicate NEW property "
                    "canonical_id"
                )

            new_ids.add(
                canonical_id
            )

            canonical_property = (
                CanonicalProperty(
                    id=canonical_id,
                    kind=row.kind,
                    semantic_labels=(
                        row.proposal
                        .semantic_labels
                    ),
                    semantic_type=(
                        row.proposal
                        .semantic_type
                    ),
                    cardinality=(
                        row.proposal
                        .cardinality
                    ),
                    value_type=(
                        row.proposal
                        .value_type
                    ),
                    status=(
                        MemoryStatus.ACTIVE
                    ),
                    created_at=(
                        recorded_at
                    ),
                )
            )

            new_properties.append(
                canonical_property
            )

        else:
            raise MemoryValidationError(
                "unsupported property "
                "resolution action"
            )

        by_ref[
            row.local_ref
        ] = canonical_property

    return (
        by_ref,
        tuple(
            new_properties
        ),
    )


def _resolved_entity_id(
    entity_ids: dict[str, str],
    local_ref: str,
    *,
    name: str,
) -> str:
    try:
        return entity_ids[
            local_ref
        ]

    except KeyError as exc:
        raise MemoryValidationError(
            f"{name} references "
            "unresolved entity local_ref"
        ) from exc


def _resolved_property(
    properties: dict[
        str,
        CanonicalProperty,
    ],
    local_ref: str,
    *,
    name: str,
) -> CanonicalProperty:
    try:
        return properties[
            local_ref
        ]

    except KeyError as exc:
        raise MemoryValidationError(
            f"{name} references "
            "unresolved property local_ref"
        ) from exc



def _fact_is_semantically_identical(
    existing: MemoryFact,
    *,
    subject_entity_id: str,
    property_id: str,
    value: object,
    unit: str | None,
    value_entity_id: str | None,
    memory_class: object,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> bool:
    return (
        existing.subject_entity_id == subject_entity_id
        and existing.property_id == property_id
        and existing.value.value == value
        and existing.value.unit == unit
        and existing.value.entity_id == value_entity_id
        and existing.memory_class is memory_class
        and existing.valid_from == valid_from
        and existing.valid_until == valid_until
    )


def _relation_is_semantically_identical(
    existing: MemoryRelation,
    *,
    source_entity_id: str,
    property_id: str,
    target_entity_id: str,
    memory_class: object,
    valid_from: datetime | None,
    valid_until: datetime | None,
) -> bool:
    return (
        existing.source_entity_id == source_entity_id
        and existing.property_id == property_id
        and existing.target_entity_id == target_entity_id
        and existing.memory_class is memory_class
        and existing.valid_from == valid_from
        and existing.valid_until == valid_until
    )


def execute_memory_resolution_plan(
    plan: MemoryResolutionPlan,
    *,
    store: CanonicalMemoryStore,
    context: TrustedWriteExecutionContext,
) -> MemoryCommitReceipt:
    if not isinstance(
        plan,
        MemoryResolutionPlan,
    ):
        raise MemoryValidationError(
            "plan must be "
            "MemoryResolutionPlan"
        )

    if not isinstance(
        store,
        CanonicalMemoryStore,
    ):
        raise MemoryValidationError(
            "store must be "
            "CanonicalMemoryStore"
        )

    if not isinstance(
        context,
        TrustedWriteExecutionContext,
    ):
        raise MemoryValidationError(
            "context must be "
            "TrustedWriteExecutionContext"
        )

    interpretation = (
        plan.interpretation
    )

    if (
        interpretation.operation
        is not MemoryOperation.REMEMBER
    ):
        raise MemoryValidationError(
            "write executor only accepts "
            "REMEMBER plans"
        )

    if interpretation.needs_confirmation:
        raise MemoryValidationError(
            "REMEMBER plan requiring "
            "confirmation cannot execute"
        )

    if interpretation.ambiguities:
        raise MemoryValidationError(
            "REMEMBER plan with "
            "ambiguities cannot execute"
        )

    _require_context_entity(
        store=store,
        entity_id=(
            context.actor_entity_id
        ),
        name=(
            "context.actor_entity_id"
        ),
    )

    _require_context_entity(
        store=store,
        entity_id=(
            context.speaker_entity_id
        ),
        name=(
            "context.speaker_entity_id"
        ),
    )

    (
        entity_ids,
        new_entity_rows,
        existing_entity_ids,
    ) = _entity_index(
        plan=plan,
        store=store,
    )

    from .enums import MemoryClass

    from .proposal_validation import (
        validate_new_entity_literal_wrappers,
        validate_remember_property_control_plane_separation,
    )

    validate_remember_property_control_plane_separation(
        interpretation
    )

    validate_new_entity_literal_wrappers(
        interpretation,
        new_entity_refs=tuple(
            row.local_ref
            for row
            in new_entity_rows
        ),
    )

    (
        fact_properties,
        new_fact_properties,
    ) = _property_index(
        plan.remember_fact_properties,
        expected_kind=(
            PropertyKind.FACT
        ),
        store=store,
        recorded_at=(
            context.recorded_at
        ),
    )

    (
        relation_properties,
        new_relation_properties,
    ) = _property_index(
        plan.remember_relation_properties,
        expected_kind=(
            PropertyKind.RELATION
        ),
        store=store,
        recorded_at=(
            context.recorded_at
        ),
    )

    episode = MemoryEpisode(
        id=new_memory_id(),
        occurred_at=(
            context.occurred_at
        ),
        recorded_at=(
            context.recorded_at
        ),
        source_type=(
            context.source_type
        ),
        raw_text=(
            context.raw_text
        ),
        content_hash=(
            hashlib.sha256(
                context.raw_text.encode(
                    "utf-8"
                )
            ).hexdigest()
        ),
        conversation_id=(
            context.conversation_id
        ),
        sequence=(
            context.sequence
        ),
        speaker_entity_id=(
            context.speaker_entity_id
        ),
        normalized_text=None,
        explicit_memory_request=(
            interpretation
            .explicit_memory_request
        ),
        subject_hints=(
            existing_entity_ids
        ),
        metadata={},
    )

    new_entities = []

    for row in new_entity_rows:
        proposal = row.proposal

        if proposal is None:
            raise MemoryValidationError(
                "NEW entity lost proposal "
                "before execution"
            )

        namespace = (
            proposal.namespace_hint
        )

        if namespace is None:
            raise MemoryValidationError(
                "NEW entity lost namespace "
                "before execution"
            )

        canonical_id = (
            entity_ids[
                row.local_ref
            ]
        )

        new_entities.append(
            Entity(
                id=canonical_id,
                namespace=namespace,
                canonical_name=(
                    proposal
                    .canonical_name
                ),
                entity_type=(
                    proposal
                    .entity_type
                ),
                aliases=(
                    proposal.aliases
                ),
                status=(
                    MemoryStatus.ACTIVE
                ),
                created_at=(
                    context.recorded_at
                ),
                updated_at=(
                    context.recorded_at
                ),
                source_episode_ids=(
                    episode.id,
                ),
                confidence=(
                    row.resolution
                    .confidence
                ),
                metadata={},
            )
        )

    facts = []
    idempotent_fact_ids = []

    for proposal in (
        interpretation.facts
    ):
        subject_entity_id = (
            _resolved_entity_id(
                entity_ids,
                proposal.subject_ref,
                name="fact.subject_ref",
            )
        )

        canonical_property = (
            _resolved_property(
                fact_properties,
                proposal.property_ref,
                name="fact.property_ref",
            )
        )

        value_type = (
            canonical_property.value_type
        )

        if value_type is None:
            raise MemoryValidationError(
                "FACT canonical property "
                "must declare value_type"
            )

        if (
            (
                value_type
                is ValueType.ENTITY_REF
            )
            and (
                proposal.memory_class
                is not MemoryClass.RELATIONAL
            )
        ):
            raise MemoryValidationError(
                "ENTITY_REF fact property requires "
                "RELATIONAL memory_class"
            )

        if (
            (
                proposal.memory_class
                is MemoryClass.RELATIONAL
            )
            and (
                value_type
                is not ValueType.ENTITY_REF
            )
        ):
            raise MemoryValidationError(
                "RELATIONAL fact requires "
                "ENTITY_REF fact property"
            )

        value_entity_id = None

        if (
            proposal.value_entity_ref
            is not None
        ):
            value_entity_id = (
                _resolved_entity_id(
                    entity_ids,
                    proposal
                    .value_entity_ref,
                    name=(
                        "fact."
                        "value_entity_ref"
                    ),
                )
            )

        if (
            value_type
            is ValueType.ENTITY_REF
            and value_entity_id
            is None
        ):
            raise MemoryValidationError(
                "ENTITY_REF fact requires "
                "value_entity_ref"
            )

        if (
            value_type
            is not ValueType.ENTITY_REF
            and value_entity_id
            is not None
        ):
            raise MemoryValidationError(
                "value_entity_ref requires "
                "ENTITY_REF property"
            )

        valid_from = _parse_temporal(
            proposal.valid_from,
            "fact.valid_from",
        )
        valid_until = _parse_temporal(
            proposal.valid_until,
            "fact.valid_until",
        )

        current_facts = (
            store.query_current_facts(
                subject_entity_ids=(
                    subject_entity_id,
                ),
                property_ids=(
                    canonical_property.id,
                ),
            )
        )

        if (
            canonical_property.cardinality
            is Cardinality.SINGLE_CURRENT
            and len(current_facts) > 1
        ):
            raise MemoryIntegrityError(
                "SINGLE_CURRENT fact property "
                "has multiple current rows"
            )

        identical = tuple(
            existing
            for existing in current_facts
            if _fact_is_semantically_identical(
                existing,
                subject_entity_id=subject_entity_id,
                property_id=canonical_property.id,
                value=proposal.value,
                unit=proposal.unit,
                value_entity_id=value_entity_id,
                memory_class=proposal.memory_class,
                valid_from=valid_from,
                valid_until=valid_until,
            )
        )

        if identical:
            idempotent_fact_ids.append(
                identical[0].id
            )
            continue

        supersedes_fact_ids = ()
        if (
            canonical_property.cardinality
            is Cardinality.SINGLE_CURRENT
        ):
            supersedes_fact_ids = tuple(
                item.id
                for item in current_facts
            )

        facts.append(
            MemoryFact(
                id=new_memory_id(),
                subject_entity_id=(
                    subject_entity_id
                ),
                property_id=(
                    canonical_property.id
                ),
                value=MemoryValue(
                    value_type=(
                        value_type
                    ),
                    value=(
                        proposal.value
                    ),
                    unit=(
                        proposal.unit
                    ),
                    entity_id=(
                        value_entity_id
                    ),
                    raw_representation=(
                        proposal
                        .raw_representation
                    ),
                ),
                memory_class=(
                    proposal.memory_class
                ),
                authority=(
                    context.authority
                ),
                confidence=(
                    proposal.confidence
                ),
                status=(
                    MemoryStatus.ACTIVE
                ),
                recorded_at=(
                    context.recorded_at
                ),
                canonical_key=(
                    f"{subject_entity_id}"
                    f"|{canonical_property.id}"
                ),
                valid_from=valid_from,
                valid_until=valid_until,
                source_episode_ids=(
                    episode.id,
                ),
                source_fact_ids=(),
                supersedes_fact_ids=(
                    supersedes_fact_ids
                ),
                contradicts_fact_ids=(),
                metadata={},
            )
        )

    relations = []
    idempotent_relation_ids = []

    for proposal in (
        interpretation.relations
    ):
        source_entity_id = (
            _resolved_entity_id(
                entity_ids,
                proposal.source_ref,
                name=(
                    "relation.source_ref"
                ),
            )
        )

        target_entity_id = (
            _resolved_entity_id(
                entity_ids,
                proposal.target_ref,
                name=(
                    "relation.target_ref"
                ),
            )
        )

        canonical_property = (
            _resolved_property(
                relation_properties,
                proposal.property_ref,
                name=(
                    "relation.property_ref"
                ),
            )
        )

        valid_from = _parse_temporal(
            proposal.valid_from,
            "relation.valid_from",
        )
        valid_until = _parse_temporal(
            proposal.valid_until,
            "relation.valid_until",
        )

        current_relations = (
            store.query_current_relations(
                source_entity_ids=(
                    source_entity_id,
                ),
                property_ids=(
                    canonical_property.id,
                ),
            )
        )

        if (
            canonical_property.cardinality
            is Cardinality.SINGLE_CURRENT
            and len(current_relations) > 1
        ):
            raise MemoryIntegrityError(
                "SINGLE_CURRENT relation property "
                "has multiple current rows"
            )

        identical = tuple(
            existing
            for existing in current_relations
            if _relation_is_semantically_identical(
                existing,
                source_entity_id=source_entity_id,
                property_id=canonical_property.id,
                target_entity_id=target_entity_id,
                memory_class=proposal.memory_class,
                valid_from=valid_from,
                valid_until=valid_until,
            )
        )

        if identical:
            idempotent_relation_ids.append(
                identical[0].id
            )
            continue

        supersedes_relation_ids = ()
        if (
            canonical_property.cardinality
            is Cardinality.SINGLE_CURRENT
        ):
            supersedes_relation_ids = tuple(
                item.id
                for item in current_relations
            )

        relations.append(
            MemoryRelation(
                id=new_memory_id(),
                source_entity_id=(
                    source_entity_id
                ),
                property_id=(
                    canonical_property.id
                ),
                target_entity_id=(
                    target_entity_id
                ),
                memory_class=(
                    proposal.memory_class
                ),
                authority=(
                    context.authority
                ),
                confidence=(
                    proposal.confidence
                ),
                status=(
                    MemoryStatus.ACTIVE
                ),
                recorded_at=(
                    context.recorded_at
                ),
                canonical_key=(
                    f"{source_entity_id}"
                    f"|{canonical_property.id}"
                ),
                valid_from=valid_from,
                valid_until=valid_until,
                source_episode_ids=(
                    episode.id,
                ),
                supersedes_relation_ids=(
                    supersedes_relation_ids
                ),
                contradicts_relation_ids=(),
                metadata={},
            )
        )

    has_mutation = bool(
        new_fact_properties
        or new_relation_properties
        or new_entities
        or facts
        or relations
    )

    if (
        not has_mutation
        and (
            idempotent_fact_ids
            or idempotent_relation_ids
        )
    ):
        return store.idempotent_no_change_receipt(
            fact_ids=tuple(
                dict.fromkeys(
                    idempotent_fact_ids
                )
            ),
            relation_ids=tuple(
                dict.fromkeys(
                    idempotent_relation_ids
                )
            ),
            recorded_at=context.recorded_at,
        )

    with store.begin_transaction(
        actor_entity_id=(
            context.actor_entity_id
        )
    ) as transaction:
        transaction.append_episode(
            episode
        )

        for canonical_property in (
            new_fact_properties
            + new_relation_properties
        ):
            transaction.create_property(
                canonical_property
            )

        for entity in (
            new_entities
        ):
            transaction.create_entity(
                entity
            )

        for fact in facts:
            transaction.create_fact(
                fact
            )

        for relation in relations:
            transaction.create_relation(
                relation
            )

        return transaction.commit()
