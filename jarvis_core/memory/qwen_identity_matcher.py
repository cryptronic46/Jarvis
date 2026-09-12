from __future__ import annotations

import json
from typing import Any

from .errors import (
    MemoryAvailabilityError,
    MemoryValidationError,
)
from .qwen_model import (
    JarvisQwenMemoryModel,
    QwenMemoryModelAvailabilityError,
)
from .resolution import (
    CanonicalIdentityDomain,
    IdentityResolutionAction,
    IdentitySelection,
    ModelCandidateView,
)


_SYSTEM_PROMPT = (
    'You are the semantic identity selector for JARVIS Memory 1.0. Use only the structured identity semantics and candidate handles provided in context_json. Treat semantic_labels as the primary identity signal. Judge semantic_labels by meaning, not by shared spelling, token overlap, language, or formatting. Translation across languages, natural-language paraphrases, and machine-style labels such as snake_case can be strong semantic matches when they denote the same concept. Do not require shared tokens, the same language, or the same formatting for a strong match. Treat semantic_type as secondary corroborating evidence: it may reinforce a match or break a tie between otherwise plausible candidates, but a semantic_type mismatch alone must not reject a candidate whose semantic_labels are a strong semantic match. Choose EXISTING when semantic_labels strongly identify exactly one existing candidate, even when semantic_type wording differs. When exactly one provided candidate is a strong semantic equivalent of the query labels, choose EXISTING for that candidate even when the labels are in different languages, one side is a natural-language paraphrase and the other is a machine-style label such as snake_case. A strong semantic match may be cross-language, a natural-language paraphrase, or a machine-style label such as snake_case; shared tokens are not required. Choose AMBIGUOUS only when two or more distinct candidates remain comparably plausible after considering semantic_labels; use semantic_type only as a secondary tiebreaker in that situation. Choose NEW when semantic_labels do not plausibly match any existing candidate. Choose NEW only after genuinely evaluating every provided candidate and finding no plausible semantic equivalent for the query labels. Never invent or request canonical identifiers. Return only the JSON object required by the schema.'
)

_USER_TEXT = (
    "Select the identity resolution action from the structured context."
)


def _selection_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "EXISTING",
                    "NEW",
                    "AMBIGUOUS",
                ],
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "selected_handle": {
                "type": [
                    "string",
                    "null",
                ],
            },
        },
        "required": [
            "action",
            "confidence",
            "selected_handle",
        ],
        "additionalProperties": False,
    }


def _validate_inputs(
    *,
    domain: CanonicalIdentityDomain,
    semantic_labels: tuple[str, ...],
    semantic_type: str,
    candidates: tuple[
        ModelCandidateView,
        ...,
    ],
) -> None:
    if not isinstance(
        domain,
        CanonicalIdentityDomain,
    ):
        raise MemoryValidationError(
            "identity matcher domain must be CanonicalIdentityDomain"
        )

    if not isinstance(
        semantic_labels,
        tuple,
    ):
        raise MemoryValidationError(
            "identity matcher semantic_labels must be tuple"
        )

    for label in semantic_labels:
        if (
            not isinstance(
                label,
                str,
            )
            or not label.strip()
        ):
            raise MemoryValidationError(
                "identity matcher semantic_labels contain invalid label"
            )

    if (
        not isinstance(
            semantic_type,
            str,
        )
        or not semantic_type.strip()
    ):
        raise MemoryValidationError(
            "identity matcher semantic_type must not be empty"
        )

    if not isinstance(
        candidates,
        tuple,
    ):
        raise MemoryValidationError(
            "identity matcher candidates must be tuple"
        )

    handles: list[str] = []

    for candidate in candidates:
        if not isinstance(
            candidate,
            ModelCandidateView,
        ):
            raise MemoryValidationError(
                "identity matcher candidates contain invalid candidate"
            )

        if candidate.domain is not domain:
            raise MemoryValidationError(
                "identity matcher candidate domain mismatch"
            )

        handles.append(
            candidate.handle
        )

    if len(
        set(
            handles
        )
    ) != len(
        handles
    ):
        raise MemoryValidationError(
            "identity matcher candidate handles must be unique"
        )


def _context_json(
    *,
    domain: CanonicalIdentityDomain,
    semantic_labels: tuple[str, ...],
    semantic_type: str,
    candidates: tuple[
        ModelCandidateView,
        ...,
    ],
) -> str:
    payload = {
        "domain":
            domain.value,

        "semantic_labels":
            list(
                semantic_labels
            ),

        "semantic_type":
            semantic_type,

        "candidates": [
            {
                "handle":
                    candidate.handle,

                "domain":
                    candidate.domain.value,

                "semantic_labels":
                    list(
                        candidate.semantic_labels
                    ),

                "semantic_type":
                    candidate.semantic_type,
            }
            for candidate
            in candidates
        ],
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _parse_selection(
    raw_json: str,
) -> IdentitySelection:
    try:
        payload = json.loads(
            raw_json
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ) as exc:
        raise MemoryValidationError(
            "identity matcher returned invalid JSON"
        ) from exc

    if not isinstance(
        payload,
        dict,
    ):
        raise MemoryValidationError(
            "identity matcher response must be object"
        )

    expected_keys = {
        "action",
        "confidence",
        "selected_handle",
    }

    if set(
        payload.keys()
    ) != expected_keys:
        raise MemoryValidationError(
            "identity matcher response keys invalid"
        )

    raw_action = payload[
        "action"
    ]

    if not isinstance(
        raw_action,
        str,
    ):
        raise MemoryValidationError(
            "identity matcher action must be string"
        )

    try:
        action = IdentityResolutionAction(
            raw_action
        )

    except ValueError as exc:
        raise MemoryValidationError(
            "identity matcher action invalid"
        ) from exc

    confidence = payload[
        "confidence"
    ]

    if (
        isinstance(
            confidence,
            bool,
        )
        or not isinstance(
            confidence,
            (
                int,
                float,
            ),
        )
    ):
        raise MemoryValidationError(
            "identity matcher confidence invalid"
        )

    selected_handle = payload[
        "selected_handle"
    ]

    if (
        selected_handle
        is not None
        and not isinstance(
            selected_handle,
            str,
        )
    ):
        raise MemoryValidationError(
            "identity matcher selected_handle invalid"
        )

    return IdentitySelection(
        action=action,
        confidence=float(
            confidence
        ),
        selected_handle=(
            selected_handle
        ),
    )


class QwenSemanticIdentityMatcher:
    __slots__ = (
        "_model",
    )

    def __init__(
        self,
        model: JarvisQwenMemoryModel,
    ) -> None:
        generate = getattr(
            model,
            "generate_constrained_json",
            None,
        )

        if not callable(
            generate
        ):
            raise MemoryValidationError(
                "identity matcher model must provide "
                "generate_constrained_json"
            )

        self._model = model

    def select_identity(
        self,
        *,
        domain: CanonicalIdentityDomain,
        semantic_labels: tuple[str, ...],
        semantic_type: str,
        candidates: tuple[
            ModelCandidateView,
            ...,
        ],
    ) -> IdentitySelection:
        _validate_inputs(
            domain=domain,
            semantic_labels=semantic_labels,
            semantic_type=semantic_type,
            candidates=candidates,
        )

        context_json = _context_json(
            domain=domain,
            semantic_labels=semantic_labels,
            semantic_type=semantic_type,
            candidates=candidates,
        )

        try:
            raw_json = (
                self._model
                .generate_constrained_json(
                    system_prompt=(
                        _SYSTEM_PROMPT
                    ),
                    user_text=(
                        _USER_TEXT
                    ),
                    context_json=(
                        context_json
                    ),
                    schema=(
                        _selection_schema()
                    ),
                )
            )

        except QwenMemoryModelAvailabilityError as exc:
            raise MemoryAvailabilityError(
                "identity matcher model unavailable"
            ) from exc

        except Exception as exc:
            raise MemoryValidationError(
                "identity matcher model call failed"
            ) from exc

        return _parse_selection(
            raw_json
        )
