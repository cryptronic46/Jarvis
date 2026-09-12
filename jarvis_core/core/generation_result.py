from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class GenerationStatus(StrEnum):
    """Typed outcome of one local text-generation attempt."""

    SUCCESS = "SUCCESS"
    MODEL_FAILURE = "MODEL_FAILURE"


@dataclass(frozen=True, slots=True)
class BrainAnswer:
    """JarvisBrain response boundary consumed by HybridBrain."""

    text: str
    generation_status: GenerationStatus

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("BrainAnswer.text must be str")

        if not isinstance(self.generation_status, GenerationStatus):
            raise TypeError(
                "BrainAnswer.generation_status must be GenerationStatus"
            )


__all__ = [
    "BrainAnswer",
    "GenerationStatus",
]
