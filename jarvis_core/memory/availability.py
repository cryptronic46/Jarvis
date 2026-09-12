from __future__ import annotations

import sqlite3


SQLITE_AVAILABILITY_PRIMARY_CODES = frozenset({
    sqlite3.SQLITE_BUSY,
    sqlite3.SQLITE_LOCKED,
    sqlite3.SQLITE_CANTOPEN,
})


def sqlite_primary_error_code(exc: BaseException) -> int | None:
    code = getattr(exc, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None
    return code & 0xFF


def is_sqlite_availability_error(exc: BaseException) -> bool:
    return (
        isinstance(exc, sqlite3.OperationalError)
        and sqlite_primary_error_code(exc)
        in SQLITE_AVAILABILITY_PRIMARY_CODES
    )


__all__ = [
    "SQLITE_AVAILABILITY_PRIMARY_CODES",
    "is_sqlite_availability_error",
    "sqlite_primary_error_code",
]
