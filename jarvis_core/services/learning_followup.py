from __future__ import annotations

from ipaddress import ip_address
import re
from threading import RLock
from time import monotonic
from urllib.parse import urlsplit

from jarvis_core.services.personal_cognition import (
    record_jarvis_learning_goal as _record_jarvis_learning_goal,
)


_LOCK = RLock()

_STATE = {
    "topic": "",
    "created_at": 0.0,
}


def _clean_topic(
    value: object,
) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(
            value
            or ""
        ),
    ).strip(
        " ,;:.!?-"
    )[:220]


def isolated_public_url(
    value: object,
) -> str:
    """
    Accept one isolated syntactically public HTTP(S) URL.

    This is a semantic/scope gate, not a replacement for the
    research engine's own network and SSRF protections.
    """
    raw = str(
        value
        or ""
    ).strip()

    if (
        not raw
        or len(raw) > 2048
        or re.search(
            r"\s",
            raw,
        )
    ):
        return ""

    try:
        parsed = urlsplit(
            raw
        )

        if (
            parsed.scheme.lower()
            not in {
                "http",
                "https",
            }
        ):
            return ""

        if not parsed.netloc:
            return ""

        if (
            parsed.username is not None
            or parsed.password is not None
        ):
            return ""

        host = str(
            parsed.hostname
            or ""
        ).strip().lower()

        if not host:
            return ""

        if (
            host == "localhost"
            or host.endswith(
                ".localhost"
            )
            or host.endswith(
                ".local"
            )
            or host.endswith(
                ".internal"
            )
        ):
            return ""

        # Accessing .port also validates malformed ports.
        _ = parsed.port

        try:
            address = ip_address(
                host
            )
        except ValueError:
            # Host names used as public sources must be qualified.
            if "." not in host:
                return ""
        else:
            if not address.is_global:
                return ""

    except Exception:
        return ""

    return raw


def set_learning_followup_context(
    topic: str,
    *,
    now: float | None = None,
) -> dict:
    clean = _clean_topic(
        topic
    )

    if not clean:
        return {
            "ok": False,
            "error":
                "EMPTY_LEARNING_FOLLOWUP_TOPIC",
        }

    created_at = (
        monotonic()
        if now is None
        else float(now)
    )

    with _LOCK:
        _STATE["topic"] = clean
        _STATE["created_at"] = (
            created_at
        )

    return {
        "ok": True,
        "topic": clean,
        "created_at": created_at,
    }


def get_learning_followup_context(
    *,
    max_age_seconds: float = 300.0,
    now: float | None = None,
) -> dict | None:
    current = (
        monotonic()
        if now is None
        else float(now)
    )

    with _LOCK:
        topic = _clean_topic(
            _STATE.get(
                "topic"
            )
        )

        created_at = float(
            _STATE.get(
                "created_at"
            )
            or 0.0
        )

    if (
        not topic
        or created_at <= 0.0
    ):
        return None

    age = (
        current
        - created_at
    )

    if (
        age < 0.0
        or age
        > float(
            max_age_seconds
        )
    ):
        return None

    # Read-only semantic snapshot.
    # Deliberately contains no token, grant or authority flag.
    return {
        "topic": topic,
        "created_at": created_at,
    }


def clear_learning_followup_context() -> None:
    with _LOCK:
        _STATE["topic"] = ""
        _STATE["created_at"] = 0.0


def consume_learning_followup_context(
    *,
    topic: str,
    source_url: str,
    source_text: str,
    max_age_seconds: float = 300.0,
    now: float | None = None,
) -> dict:
    """
    Atomically consume one live followup referent.

    The previous OWNER learning goal supplies only the topic.
    The current OWNER turn must independently supply one isolated
    public URL. The context is cleared before any network action.
    """
    clean_topic = _clean_topic(
        topic
    )

    exact_url = isolated_public_url(
        source_text
    )

    normalized_argument_url = (
        isolated_public_url(
            source_url
        )
    )

    if (
        not clean_topic
        or not exact_url
        or not normalized_argument_url
        or exact_url
        != normalized_argument_url
    ):
        return {
            "ok": False,
            "error":
                "FOLLOWUP_URL_SCOPE_INVALID",
        }

    current = (
        monotonic()
        if now is None
        else float(now)
    )

    with _LOCK:
        live_topic = _clean_topic(
            _STATE.get(
                "topic"
            )
        )

        created_at = float(
            _STATE.get(
                "created_at"
            )
            or 0.0
        )

        if (
            not live_topic
            or created_at <= 0.0
        ):
            return {
                "ok": False,
                "error":
                    "FOLLOWUP_CONTEXT_NOT_AVAILABLE",
            }

        age = (
            current
            - created_at
        )

        if (
            age < 0.0
            or age
            > float(
                max_age_seconds
            )
        ):
            return {
                "ok": False,
                "error":
                    "FOLLOWUP_CONTEXT_EXPIRED",
            }

        if live_topic != clean_topic:
            return {
                "ok": False,
                "error":
                    "FOLLOWUP_TOPIC_MISMATCH",
            }

        # Consume before any caller can perform network activity.
        _STATE["topic"] = ""
        _STATE["created_at"] = 0.0

    return {
        "ok": True,
        "consumed": True,
        "topic": clean_topic,
        "source_url": exact_url,
        "created_at": created_at,
    }


def record_jarvis_learning_goal(
    topic: str,
    source_text: str = "",
) -> dict:
    """
    ToolRegistry callable for an explicit local OWNER learning goal.

    Durable local cognition is written first. Only a successful write
    creates the short-lived referent context.
    """
    result = (
        _record_jarvis_learning_goal(
            topic,
            source_text=source_text,
        )
    )

    if not isinstance(
        result,
        dict,
    ):
        return {
            "ok": False,
            "error":
                "INVALID_LEARNING_GOAL_RESULT",
        }

    if not result.get(
        "ok"
    ):
        return result

    clean_topic = _clean_topic(
        result.get(
            "topic"
        )
        or topic
    )

    followup = (
        set_learning_followup_context(
            clean_topic
        )
    )

    if not followup.get(
        "ok"
    ):
        return {
            "ok": False,
            "error":
                "LEARNING_GOAL_FOLLOWUP_CONTEXT_FAILED",
        }

    enriched = dict(
        result
    )

    enriched[
        "followup_context_created"
    ] = True

    enriched[
        "followup_window_seconds"
    ] = 300

    return enriched
