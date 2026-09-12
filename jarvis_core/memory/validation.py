from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping
import json
import math
import re

from .errors import MemoryValidationError


_PREDICATE = re.compile(
    r"^[a-z][a-z0-9_]*$"
)


def require_text(
    value: str,
    field: str,
) -> str:
    text = str(
        value or ""
    ).strip()

    if not text:
        raise MemoryValidationError(
            f"{field} must not be empty"
        )

    return text


def require_confidence(
    value: float,
) -> float:
    number = float(
        value
    )

    if (
        not math.isfinite(
            number
        )
        or not 0.0
        <= number
        <= 1.0
    ):
        raise MemoryValidationError(
            (
                "confidence must be finite "
                "and between 0 and 1"
            )
        )

    return number


def require_aware(
    value: datetime | None,
    field: str,
) -> datetime | None:
    if value is None:
        return None

    if (
        value.tzinfo is None
        or value.utcoffset()
        is None
    ):
        raise MemoryValidationError(
            (
                f"{field} must be "
                "timezone-aware"
            )
        )

    return value


def require_predicate(
    value: str,
) -> str:
    text = require_text(
        value,
        "predicate",
    )

    if not _PREDICATE.fullmatch(
        text
    ):
        raise MemoryValidationError(
            (
                "predicate must be "
                "lowercase ASCII snake_case"
            )
        )

    return text


def require_json(
    value: Any,
    field: str = "value",
) -> None:

    def visit(
        item: Any,
        path: str,
    ) -> None:

        if (
            item is None
            or isinstance(
                item,
                (
                    str,
                    bool,
                    int,
                ),
            )
        ):
            return

        if isinstance(
            item,
            float,
        ):
            if not math.isfinite(
                item
            ):
                raise MemoryValidationError(
                    (
                        f"{field}{path} "
                        "contains a "
                        "non-finite float"
                    )
                )

            return

        if isinstance(
            item,
            (
                list,
                tuple,
            ),
        ):
            for index, child in enumerate(
                item
            ):
                visit(
                    child,
                    f"{path}[{index}]",
                )

            return

        if isinstance(
            item,
            Mapping,
        ):
            for key, child in (
                item.items()
            ):
                if not isinstance(
                    key,
                    str,
                ):
                    raise MemoryValidationError(
                        (
                            f"{field}{path} "
                            "contains a "
                            "non-string key"
                        )
                    )

                visit(
                    child,
                    f"{path}.{key}",
                )

            return

        raise MemoryValidationError(
            (
                f"{field}{path} is not "
                "canonical JSON data"
            )
        )

    visit(
        value,
        "",
    )


def freeze_metadata(
    value: Mapping[
        str,
        Any,
    ] | None,
) -> Mapping[
    str,
    Any,
]:
    data = dict(
        value or {}
    )

    require_json(
        data,
        "metadata",
    )

    return MappingProxyType(
        data
    )


def stable_json(
    value: Any,
) -> str:
    require_json(
        value
    )

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        allow_nan=False,
    )


def utc_text(
    value: datetime | None,
) -> str | None:
    if value is None:
        return None

    require_aware(
        value,
        "datetime",
    )

    return (
        value
        .astimezone(
            timezone.utc
        )
        .isoformat(
            timespec="microseconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )
