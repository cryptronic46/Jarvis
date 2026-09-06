"""Fail-soft maintenance for the derived unified memory index.

Canonical JSON/JSONL files remain authoritative. This module only refreshes
explicit derived-index lanes after a real runtime write has completed.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable

from jarvis_core.services.memory_index import UnifiedMemoryIndex


# RUNTIME_MEMORY_MAINTENANCE_V1

RUNTIME_REFRESH_SOURCES = frozenset({
    "user_profile",
    "explicit_fact",
    "personal_model",
    "memory_graph",
})

RUNTIME_PERSONAL_SOURCES = (
    "user_profile",
    "explicit_fact",
    "personal_model",
    "memory_graph",
)

TOOL_SOURCE_REFRESH = MappingProxyType({
    "remember_user_fact": (
        "explicit_fact",
        "memory_graph",
    ),
    "record_jarvis_learning_goal": (
        "personal_model",
    ),
    "record_local_teaching": (
        "personal_model",
    ),
    "remember_project_state": (
        "memory_graph",
    ),
    "remember_decision": (
        "memory_graph",
    ),
    "relate_memory_entities": (
        "memory_graph",
    ),
})


def _not_attempted(
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "attempted": False,
        "refreshed": False,
        "changed_sources": [],
        "unchanged_sources": [],
        "reason": reason,
    }


def refresh_memory_sources(
    sources: Iterable[str],
    *,
    root: str | Path = ".",
    index_path: str | Path = "memory/unified_memory.sqlite3",
) -> dict[str, Any]:
    """Refresh only explicitly permitted derived personal-memory lanes."""

    requested = tuple(
        dict.fromkeys(
            str(source or "").strip()
            for source in sources
            if str(source or "").strip()
        )
    )

    if not requested:
        return _not_attempted(
            "NO_MEMORY_SOURCES_REQUESTED"
        )

    invalid = sorted(
        set(requested)
        - RUNTIME_REFRESH_SOURCES
    )

    if invalid:
        return {
            "ok": False,
            "attempted": False,
            "refreshed": False,
            "error": "MEMORY_RUNTIME_SOURCE_FORBIDDEN",
            "invalid_sources": invalid,
            "requested_sources": list(requested),
        }

    root_path = Path(
        root
    ).resolve()

    try:
        index = UnifiedMemoryIndex(
            index_path
        )

        result = index.refresh_sources(
            root=root_path,
            sources=requested,
        )

    except Exception as exc:
        return {
            "ok": False,
            "attempted": True,
            "refreshed": False,
            "error": (
                "MEMORY_RUNTIME_REFRESH_FAILED:"
                + type(exc).__name__
            ),
            "reason": str(exc),
            "requested_sources": list(requested),
        }

    if not isinstance(
        result,
        dict,
    ):
        return {
            "ok": False,
            "attempted": True,
            "refreshed": False,
            "error": "MEMORY_RUNTIME_REFRESH_INVALID_RESULT",
            "requested_sources": list(requested),
        }

    output = dict(
        result
    )

    output["attempted"] = True
    output["requested_sources"] = list(
        requested
    )

    return output


def refresh_after_tool(
    tool_name: str,
    *,
    root: str | Path = ".",
    index_path: str | Path = "memory/unified_memory.sqlite3",
) -> dict[str, Any]:
    """Refresh only the lanes mapped to one successful runtime tool."""

    name = str(
        tool_name
        or ""
    ).strip()

    sources = TOOL_SOURCE_REFRESH.get(
        name
    )

    if not sources:
        return _not_attempted(
            "TOOL_HAS_NO_MEMORY_REFRESH"
        )

    return refresh_memory_sources(
        sources,
        root=root,
        index_path=index_path,
    )


def refresh_after_personal_cognition(
    observation_result: Any,
    *,
    root: str | Path = ".",
    index_path: str | Path = "memory/unified_memory.sqlite3",
) -> dict[str, Any]:
    """Refresh personal_model only after a successful learning-enabled turn."""

    if not isinstance(
        observation_result,
        dict,
    ):
        return _not_attempted(
            "COGNITION_RESULT_NOT_STRUCTURED"
        )

    if observation_result.get(
        "ok"
    ) is not True:
        return _not_attempted(
            "COGNITION_WRITE_NOT_SUCCESSFUL"
        )

    if observation_result.get(
        "learning_enabled"
    ) is not True:
        return _not_attempted(
            "PERSONAL_LEARNING_DISABLED"
        )

    return refresh_memory_sources(
        ("personal_model",),
        root=root,
        index_path=index_path,
    )


def refresh_runtime_personal_memory(
    *,
    root: str | Path = ".",
    index_path: str | Path = "memory/unified_memory.sqlite3",
) -> dict[str, Any]:
    """Synchronize all derived personal lanes once at runtime startup."""

    return refresh_memory_sources(
        RUNTIME_PERSONAL_SOURCES,
        root=root,
        index_path=index_path,
    )
