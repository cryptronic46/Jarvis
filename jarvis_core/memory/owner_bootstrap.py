from __future__ import annotations

from .canonical_store import CanonicalMemoryStore
from .entity_bindings import TrustedEntityBindings
from .enums import (
    CommitStatus,
    MemoryNamespace,
    MemoryStatus,
)
from .errors import MemoryIntegrityError
from .models import Entity


_OWNER_LOCAL_REF = "owner"
_OWNER_CANONICAL_NAME = "owner"
_OWNER_ENTITY_TYPE = "person"


def _is_compatible_owner(
    entity: Entity,
) -> bool:
    return (
        entity.namespace
        is MemoryNamespace.OWNER
        and entity.status
        is MemoryStatus.ACTIVE
        and entity.canonical_name
        == _OWNER_CANONICAL_NAME
        and entity.entity_type
        == _OWNER_ENTITY_TYPE
    )


def _owner_bindings(
    owner: Entity,
) -> TrustedEntityBindings:
    return TrustedEntityBindings(
        {
            _OWNER_LOCAL_REF:
                owner.id,
        }
    )


def ensure_canonical_owner(
    store: CanonicalMemoryStore,
) -> TrustedEntityBindings:
    transaction = (
        store.begin_transaction(
            actor_entity_id=None
        )
    )

    transaction_open = True

    try:
        owners = tuple(
            entity
            for entity
            in store.list_entities()
            if (
                entity.namespace
                is MemoryNamespace.OWNER
            )
        )

        if len(
            owners
        ) > 1:
            raise MemoryIntegrityError(
                "canonical OWNER identity is not unique"
            )

        if len(
            owners
        ) == 1:
            owner = owners[
                0
            ]

            if not _is_compatible_owner(
                owner
            ):
                raise MemoryIntegrityError(
                    "canonical OWNER identity is structurally invalid"
                )

            transaction.rollback()

            transaction_open = False

            return _owner_bindings(
                owner
            )

        owner = Entity.create(
            namespace=(
                MemoryNamespace.OWNER
            ),
            canonical_name=(
                _OWNER_CANONICAL_NAME
            ),
            entity_type=(
                _OWNER_ENTITY_TYPE
            ),
            aliases=(),
            source_episode_ids=(),
            confidence=1.0,
        )

        transaction.create_entity(
            owner
        )

        receipt = (
            transaction.commit()
        )

        transaction_open = False

        if (
            receipt.status
            is not CommitStatus.COMMITTED
        ):
            raise MemoryIntegrityError(
                "canonical OWNER bootstrap did not commit"
            )

        persisted = (
            store.get_entity(
                owner.id
            )
        )

        if (
            persisted is None
            or not _is_compatible_owner(
                persisted
            )
        ):
            raise MemoryIntegrityError(
                "canonical OWNER bootstrap readback failed"
            )

        owners_after = tuple(
            entity
            for entity
            in store.list_entities()
            if (
                entity.namespace
                is MemoryNamespace.OWNER
            )
        )

        if (
            len(
                owners_after
            )
            != 1
            or owners_after[
                0
            ].id
            != owner.id
        ):
            raise MemoryIntegrityError(
                "canonical OWNER singleton invariant failed"
            )

        return _owner_bindings(
            persisted
        )

    except Exception:
        if transaction_open:
            transaction.rollback()

        raise
