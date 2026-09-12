from __future__ import annotations

import uuid


def new_memory_id() -> str:
    """Return an opaque local ID, preferring UUIDv7."""
    factory = getattr(
        uuid,
        "uuid7",
        uuid.uuid4,
    )

    return str(
        factory()
    )
