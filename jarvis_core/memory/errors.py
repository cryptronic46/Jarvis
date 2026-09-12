from __future__ import annotations


class MemoryError(Exception):
    """Base exception for JARVIS Memory 1.0."""


class MemoryAvailabilityError(MemoryError):
    """Recoverable Memory1 dependency availability failure."""


class MemoryValidationError(MemoryError):
    pass


class MemoryCanonicalContractMismatchError(
    MemoryValidationError
):
    """Existing canonical property contract disagrees with a proposal."""


class MemoryIntegrityError(MemoryError):
    pass


class MemoryProjectionError(MemoryError):
    pass


class MemorySchemaError(MemoryError):
    pass
