from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .errors import MemoryValidationError
from .validation import require_text


@dataclass(
    frozen=True,
    slots=True,
)
class TrustedEntityBindings:
    bindings: Mapping[str, str] = field(
        default_factory=dict
    )

    def __post_init__(
        self,
    ) -> None:
        if not isinstance(
            self.bindings,
            Mapping,
        ):
            raise MemoryValidationError(
                "TrustedEntityBindings.bindings "
                "must be a mapping"
            )

        checked: dict[str, str] = {}

        for (
            local_ref,
            canonical_entity_id,
        ) in self.bindings.items():
            if not isinstance(
                local_ref,
                str,
            ):
                raise MemoryValidationError(
                    "TrustedEntityBindings local refs "
                    "must be text"
                )

            if not isinstance(
                canonical_entity_id,
                str,
            ):
                raise MemoryValidationError(
                    "TrustedEntityBindings canonical "
                    "entity IDs must be text"
                )

            require_text(
                local_ref,
                (
                    "TrustedEntityBindings."
                    "local_ref"
                ),
            )

            require_text(
                canonical_entity_id,
                (
                    "TrustedEntityBindings."
                    "canonical_entity_id"
                ),
            )

            if (
                local_ref
                != local_ref.strip()
            ):
                raise MemoryValidationError(
                    "TrustedEntityBindings local refs "
                    "must not contain surrounding "
                    "whitespace"
                )

            if (
                canonical_entity_id
                != canonical_entity_id.strip()
            ):
                raise MemoryValidationError(
                    "TrustedEntityBindings canonical "
                    "entity IDs must not contain "
                    "surrounding whitespace"
                )

            checked[
                local_ref
            ] = canonical_entity_id

        object.__setattr__(
            self,
            "bindings",
            MappingProxyType(
                checked
            ),
        )

    def canonical_id_for(
        self,
        local_ref: str,
    ) -> str | None:
        require_text(
            local_ref,
            "local_ref",
        )

        return self.bindings.get(
            local_ref
        )

    def contains(
        self,
        local_ref: str,
    ) -> bool:
        require_text(
            local_ref,
            "local_ref",
        )

        return (
            local_ref
            in self.bindings
        )

    def local_refs(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            self.bindings
        )


__all__ = [
    "TrustedEntityBindings",
]
