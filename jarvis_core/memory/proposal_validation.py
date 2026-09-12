from __future__ import annotations

from .enums import (
    MemoryClass,
    ValueType,
)

from .errors import (
    MemoryValidationError,
)

from .interpreter import (
    MemoryInterpretation,
    MemoryOperation,
)


def _normalized_semantic_shape(
    value: str,
) -> str:
    return value.strip().casefold()


def validate_remember_property_control_plane_separation(
    interpretation: MemoryInterpretation,
) -> None:
    """
    Reject structural leakage from MemoryOperation control metadata into
    property semantic identity.

    Rejection is deliberately narrow: it occurs only when all semantic
    identity content collapses to the selected MemoryOperation token itself.
    No domain vocabulary, synonyms or fuzzy matching are used.
    """

    if not isinstance(
        interpretation,
        MemoryInterpretation,
    ):
        raise MemoryValidationError(
            "interpretation must be MemoryInterpretation"
        )

    if (
        interpretation.operation
        is not MemoryOperation.REMEMBER
    ):
        return

    control_token = (
        _normalized_semantic_shape(
            interpretation.operation.value
        )
    )

    proposals = (
        tuple(
            interpretation.fact_properties
        )
        + tuple(
            interpretation.relation_properties
        )
    )

    for proposal in proposals:
        semantic_components = (
            proposal.semantic_type,
            *proposal.semantic_labels,
        )

        normalized_components = {
            _normalized_semantic_shape(
                component
            )
            for component
            in semantic_components
            if (
                isinstance(
                    component,
                    str,
                )
                and component.strip()
            )
        }

        if (
            normalized_components
            and normalized_components
            == {
                control_token
            }
        ):
            raise MemoryValidationError(
                "property semantic identity must not "
                "collapse exclusively to the "
                "MemoryOperation control token"
            )


def validate_remember_entity_proposal_usage(
    interpretation: MemoryInterpretation,
) -> None:
    """
    Validate structural REMEMBER proposal semantics before resolution.

    Canonical identity resolution, trusted bindings, semantic matching,
    persistence and transaction ownership remain outside this module.
    """

    if not isinstance(
        interpretation,
        MemoryInterpretation,
    ):
        raise MemoryValidationError(
            "interpretation must be MemoryInterpretation"
        )

    if (
        interpretation.operation
        is not MemoryOperation.REMEMBER
    ):
        return

    validate_remember_property_control_plane_separation(
        interpretation
    )

    fact_property_map = {
        proposal.local_ref:
            proposal

        for proposal
        in interpretation.fact_properties
    }

    for fact in interpretation.facts:
        property_proposal = (
            fact_property_map.get(
                fact.property_ref
            )
        )

        if property_proposal is None:
            raise MemoryValidationError(
                "fact property_ref does not resolve"
            )

        entity_ref_value = (
            property_proposal.value_type
            is ValueType.ENTITY_REF
        )

        relational_memory = (
            fact.memory_class
            is MemoryClass.RELATIONAL
        )

        if (
            entity_ref_value
            and not relational_memory
        ):
            raise MemoryValidationError(
                "ENTITY_REF fact property requires "
                "RELATIONAL memory_class"
            )

        if (
            relational_memory
            and not entity_ref_value
        ):
            raise MemoryValidationError(
                "RELATIONAL fact requires "
                "ENTITY_REF fact property"
            )

    used_entity_refs = {
        fact.subject_ref
        for fact
        in interpretation.facts
    }

    used_entity_refs.update(
        fact.value_entity_ref
        for fact
        in interpretation.facts
        if (
            fact.value_entity_ref
            is not None
        )
    )

    for relation in interpretation.relations:
        used_entity_refs.add(
            relation.source_ref
        )

        used_entity_refs.add(
            relation.target_ref
        )

    proposed_entity_refs = {
        entity.local_ref
        for entity
        in interpretation.entities
    }

    if (
        proposed_entity_refs
        - used_entity_refs
    ):
        raise MemoryValidationError(
            "unused entity proposal"
        )


def validate_new_entity_literal_wrappers(
    interpretation: MemoryInterpretation,
    *,
    new_entity_refs: tuple[str, ...],
) -> None:
    """
    Reject resolved NEW entities whose only structural role is wrapping
    one fact value and whose type mirrors that fact property's semantics.
    """

    if not isinstance(
        interpretation,
        MemoryInterpretation,
    ):
        raise MemoryValidationError(
            "interpretation must be MemoryInterpretation"
        )

    if (
        interpretation.operation
        is not MemoryOperation.REMEMBER
    ):
        return

    if not isinstance(
        new_entity_refs,
        tuple,
    ):
        raise MemoryValidationError(
            "new_entity_refs must be tuple"
        )

    if (
        len(set(new_entity_refs))
        != len(new_entity_refs)
    ):
        raise MemoryValidationError(
            "new_entity_refs must be unique"
        )

    proposed_entities = {
        entity.local_ref:
            entity

        for entity
        in interpretation.entities
    }

    fact_properties = {
        proposal.local_ref:
            proposal

        for proposal
        in interpretation.fact_properties
    }

    for entity_ref in new_entity_refs:
        if (
            not isinstance(
                entity_ref,
                str,
            )
            or not entity_ref.strip()
            or entity_ref
            != entity_ref.strip()
        ):
            raise MemoryValidationError(
                "new_entity_refs must contain "
                "non-empty trimmed text"
            )

        entity = (
            proposed_entities.get(
                entity_ref
            )
        )

        if entity is None:
            raise MemoryValidationError(
                "NEW entity ref has no "
                "entity proposal"
            )

        value_facts = tuple(
            fact
            for fact
            in interpretation.facts
            if (
                fact.value_entity_ref
                == entity_ref
            )
        )

        if len(value_facts) != 1:
            continue

        if any(
            fact.subject_ref
            == entity_ref

            for fact
            in interpretation.facts
        ):
            continue

        if any(
            (
                relation.source_ref
                == entity_ref
            )
            or (
                relation.target_ref
                == entity_ref
            )

            for relation
            in interpretation.relations
        ):
            continue

        fact = value_facts[0]

        property_proposal = (
            fact_properties.get(
                fact.property_ref
            )
        )

        if property_proposal is None:
            raise MemoryValidationError(
                "fact property_ref does not resolve"
            )

        entity_shape = (
            _normalized_semantic_shape(
                entity.entity_type
            )
        )

        property_shapes = {
            _normalized_semantic_shape(
                property_proposal
                .semantic_type
            ),
            *(
                _normalized_semantic_shape(
                    label
                )
                for label
                in property_proposal
                .semantic_labels
            ),
        }

        if entity_shape in property_shapes:
            raise MemoryValidationError(
                "NEW entity proposal appears "
                "to wrap a literal fact value"
            )
