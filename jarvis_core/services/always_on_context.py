from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


DEFAULT_ALWAYS_ON_MAX_CHARS = 512

RESERVED_INTERACTION_SLOT_PRIORITY = (
    "interaction.language",
    "interaction.address_form",
    "interaction.verbosity",
)

_EXPECTED_PROPERTY_CONTRACT = {
    "interaction.language": (
        "FACT",
        "SINGLE_CURRENT",
        "STRING",
    ),
    "interaction.address_form": (
        "FACT",
        "SINGLE_CURRENT",
        "STRING",
    ),
    "interaction.verbosity": (
        "FACT",
        "SINGLE_CURRENT",
        "STRING",
    ),
}

_HEADER_LINES = (
    "JARVIS_ALWAYS_ON_INTERACTION:",
    (
        "Authoritative OWNER-confirmed global interaction "
        "settings from Memory 1.0. Apply only listed slots; "
        "never infer missing slots."
    ),
)


class AlwaysOnContextIntegrityError(
    RuntimeError
):
    pass


@dataclass(
    frozen=True
)
class AlwaysOnContextBuild:
    context: str
    bound_slots: tuple[str, ...]
    included_slots: tuple[str, ...]
    dropped_slots: tuple[str, ...]
    max_chars: int

    @property
    def char_count(
        self,
    ) -> int:
        return len(
            self.context
        )


def _enum_value(
    value: Any,
) -> str:
    raw = getattr(
        value,
        "value",
        value,
    )

    return str(
        raw
    )


def _property_status(
    property_row: Any,
) -> str:
    status = getattr(
        property_row,
        "status",
        None,
    )

    if status is None:
        status = getattr(
            property_row,
            "initial_status",
            None,
        )

    return _enum_value(
        status
    )


def _fact_status(
    fact: Any,
) -> str:
    status = getattr(
        fact,
        "status",
        None,
    )

    if status is None:
        status = getattr(
            fact,
            "initial_status",
            None,
        )

    return _enum_value(
        status
    )


def _validate_property(
    slot_name: str,
    property_row: Any,
) -> None:
    expected = (
        _EXPECTED_PROPERTY_CONTRACT[
            slot_name
        ]
    )

    actual = (
        _enum_value(
            getattr(
                property_row,
                "kind",
                "",
            )
        ),
        _enum_value(
            getattr(
                property_row,
                "cardinality",
                "",
            )
        ),
        _enum_value(
            getattr(
                property_row,
                "value_type",
                "",
            )
        ),
    )

    if actual != expected:
        raise AlwaysOnContextIntegrityError(
            "reserved interaction property "
            f"contract mismatch for {slot_name}: "
            f"expected={expected!r}, "
            f"actual={actual!r}"
        )

    if (
        _property_status(
            property_row
        )
        != "ACTIVE"
    ):
        raise AlwaysOnContextIntegrityError(
            "reserved interaction property "
            f"is not ACTIVE: {slot_name}"
        )


def _fact_string_value(
    slot_name: str,
    fact: Any,
) -> str:
    if (
        _fact_status(
            fact
        )
        != "ACTIVE"
    ):
        raise AlwaysOnContextIntegrityError(
            "current interaction fact "
            f"is not ACTIVE: {slot_name}"
        )

    memory_value = getattr(
        fact,
        "value",
        None,
    )

    if memory_value is None:
        raise AlwaysOnContextIntegrityError(
            "current interaction fact "
            f"has no value: {slot_name}"
        )

    value_type = _enum_value(
        getattr(
            memory_value,
            "value_type",
            "",
        )
    )

    if value_type != "STRING":
        raise AlwaysOnContextIntegrityError(
            "current interaction fact "
            f"is not STRING: {slot_name}"
        )

    value = getattr(
        memory_value,
        "value",
        None,
    )

    if (
        not isinstance(
            value,
            str,
        )
        or not value.strip()
    ):
        raise AlwaysOnContextIntegrityError(
            "current interaction fact "
            f"has invalid text: {slot_name}"
        )

    return value.strip()


def build_memory1_always_on_context(
    store,
    owner_entity_id: str,
    *,
    max_chars: int = (
        DEFAULT_ALWAYS_ON_MAX_CHARS
    ),
) -> AlwaysOnContextBuild:
    """
    Build global interaction context directly from current
    canonical Memory 1.0 state.

    No Personal Cognition state is read here. There is no
    cache: every call re-reads bindings, properties and
    current OWNER facts from the supplied canonical store.
    """

    owner_entity_id = str(
        owner_entity_id
        or ""
    ).strip()

    if not owner_entity_id:
        raise ValueError(
            "owner_entity_id must be "
            "non-empty text"
        )

    max_chars = int(
        max_chars
    )

    if max_chars <= 0:
        raise ValueError(
            "max_chars must be > 0"
        )

    bindings = dict(
        store
        .list_reserved_property_bindings()
    )

    bound_slots = tuple(
        slot_name
        for slot_name
        in RESERVED_INTERACTION_SLOT_PRIORITY
        if slot_name
        in bindings
    )

    if not bound_slots:
        return AlwaysOnContextBuild(
            context="",
            bound_slots=(),
            included_slots=(),
            dropped_slots=(),
            max_chars=max_chars,
        )

    properties = {
        str(
            property_row.id
        ):
            property_row
        for property_row
        in store.list_properties()
    }

    property_ids = tuple(
        str(
            bindings[
                slot_name
            ]
        )
        for slot_name
        in bound_slots
    )

    for (
        slot_name,
        property_id,
    ) in zip(
        bound_slots,
        property_ids,
    ):
        property_row = (
            properties.get(
                property_id
            )
        )

        if property_row is None:
            raise AlwaysOnContextIntegrityError(
                "reserved interaction binding "
                "references missing property: "
                f"{slot_name} -> {property_id}"
            )

        _validate_property(
            slot_name,
            property_row,
        )

    facts = (
        store.query_current_facts(
            subject_entity_ids=(
                owner_entity_id,
            ),
            property_ids=property_ids,
        )
    )

    by_property: dict[
        str,
        list[Any],
    ] = {}

    for fact in facts:
        property_id = str(
            getattr(
                fact,
                "property_id",
                "",
            )
        )

        by_property.setdefault(
            property_id,
            [],
        ).append(
            fact
        )

    candidate_rows = []

    for (
        slot_name,
        property_id,
    ) in zip(
        bound_slots,
        property_ids,
    ):
        slot_facts = tuple(
            by_property.get(
                property_id,
                (),
            )
        )

        if len(slot_facts) > 1:
            raise AlwaysOnContextIntegrityError(
                "reserved interaction slot "
                "has multiple current OWNER facts: "
                f"{slot_name}"
            )

        if not slot_facts:
            continue

        value = _fact_string_value(
            slot_name,
            slot_facts[0],
        )

        candidate_rows.append(
            (
                slot_name,
                (
                    "- "
                    + slot_name
                    + "="
                    + json.dumps(
                        value,
                        ensure_ascii=False,
                        separators=(
                            ",",
                            ":",
                        ),
                    )
                ),
            )
        )

    if not candidate_rows:
        return AlwaysOnContextBuild(
            context="",
            bound_slots=bound_slots,
            included_slots=(),
            dropped_slots=(),
            max_chars=max_chars,
        )

    context = "\n".join(
        _HEADER_LINES
    )

    included = []
    dropped = []

    for index, (
        slot_name,
        row,
    ) in enumerate(
        candidate_rows
    ):
        proposed = (
            context
            + "\n"
            + row
        )

        if len(proposed) > max_chars:
            dropped.extend(
                candidate_slot
                for (
                    candidate_slot,
                    _,
                )
                in candidate_rows[
                    index:
                ]
            )
            break

        context = proposed

        included.append(
            slot_name
        )

    if not included:
        context = ""

    return AlwaysOnContextBuild(
        context=context,
        bound_slots=bound_slots,
        included_slots=tuple(
            included
        ),
        dropped_slots=tuple(
            dropped
        ),
        max_chars=max_chars,
    )
