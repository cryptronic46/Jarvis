from __future__ import annotations

from typing import Any

from jarvis_core.services.autonomy import (
    authorized_learning,
    autonomy_guardian,
    parse_direct_external_learning_order,
)
from jarvis_core.services.learning_followup import (
    consume_learning_followup_context,
    isolated_public_url,
)


_RESEARCH_ENGINE = None
_EVENTS = None


def configure_external_learning_runtime(
    research_engine,
    events,
) -> None:
    """
    Bind runtime-only dependencies after LocalResearchEngine exists.
    """
    global _RESEARCH_ENGINE, _EVENTS

    _RESEARCH_ENGINE = research_engine
    _EVENTS = events


def _retry_reason(
    failure: str,
) -> str:
    reason_map = {
        "RESEARCH_UNAVAILABLE":
            "direct_research_unavailable_before_learning",
        "SEARCH_FAILED":
            "web_search_failed_before_learning",
        "SEARCH_RESULTS_IRRELEVANT":
            "web_search_irrelevant_before_learning",
        "FETCH_FAILED":
            "web_fetch_failed_before_learning",
        "FETCHED_SOURCES_IRRELEVANT":
            "web_sources_irrelevant_before_learning",
        "LOCAL_SYNTHESIS_FAILED":
            "local_synthesis_failed_before_learning",
        "LOCAL_SYNTHESIS_RELEVANCE_REJECTED":
            "local_synthesis_relevance_rejected_before_learning",
        "LEARNING_TOPIC_MISMATCH":
            "learning_store_topic_mismatch",
        "DIRECT_URL_FETCH_FAILED":
            "direct_url_fetch_failed_before_learning",
        "DIRECT_URL_TOPIC_MISMATCH":
            "direct_url_topic_mismatch_before_learning",
        "DIRECT_URL_BLOCKED":
            "direct_url_blocked_before_learning",
    }

    return reason_map.get(
        failure,
        "external_research_failed_before_learning",
    )


def queue_external_learning_retry(
    *,
    payload: dict,
    topic: str,
    error: str | None,
) -> dict[str, Any]:
    """
    Requeue exactly the failed external-learning payload.
    """
    failure = (
        str(error or "").strip()
        or "RESEARCH_FAILED"
    )

    guardian = autonomy_guardian()

    retry = guardian.request(
        capability="external_learning",
        payload=dict(payload),
        reason=_retry_reason(failure),
        description=(
            "repeat the same bounded external-learning session for "
            f"{str(topic or '')[:220]} after the research failure "
            "has been resolved"
        ),
        action=(
            "external_learning_resume_query"
            if str(
                payload.get("original_query")
                or ""
            ).strip()
            else "external_learning"
        ),
        source="local_research_retry",
    )

    return {
        "ok": False,
        "retry": retry,
        "failure": failure,
    }


def _normalize_source_url(
    value: object,
) -> str:
    return str(
        value
        or ""
    ).strip()


def _current_turn_authority_matches(
    *,
    parsed: dict[str, Any],
    topic: str,
    query: str,
    source_url: str,
    standing_public_web_read_only_grant: bool,
) -> bool:
    parsed_topic = str(
        parsed.get("topic")
        or ""
    ).strip()

    parsed_query = str(
        parsed.get("query")
        or ""
    ).strip()

    parsed_url = _normalize_source_url(
        parsed.get("source_url")
    )

    parsed_standing = bool(
        parsed.get(
            "standing_public_web_read_only_grant"
        )
    )

    return (
        parsed.get("kind")
        == "direct_external_learning"
        and bool(
            parsed.get(
                "direct_user_authority"
            )
        )
        and parsed_topic == topic
        and parsed_query == query
        and parsed_url == source_url
        and parsed_standing
        == bool(
            standing_public_web_read_only_grant
        )
    )


def execute_authorized_external_learning(
    topic: str,
    query: str,
    source_text: str,
    deep: bool = True,
    scope: str = "single_research_session",
    source_url: str = "",
    standing_public_web_read_only_grant: bool = False,
    authority_mode: str = "current_turn",
    authorization_token: str = "",
    authorization_action: str = "",
    authorized_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute one bounded external-learning request.

    Supported authority modes:

    current_turn:
        StructuredRequest came from the current OWNER instruction.
        The exact text is reparsed before any external side effect.

    approved_grant:
        The OWNER previously approved an AutonomyGuardian token.
        The exact token + capability + original payload are consumed
        atomically before research.

    followup_url:
        A successful local learning goal supplied only the topic referent.
        The current OWNER turn supplies one isolated public URL. The exact
        live follow-up context is consumed before any network side effect.
    """
    mode = str(
        authority_mode
        or "current_turn"
    ).strip().lower()

    if mode not in {
        "current_turn",
        "approved_grant",
        "followup_url",
    }:
        return {
            "ok": False,
            "error":
                "INVALID_EXTERNAL_LEARNING_AUTHORITY_MODE",
        }

    topic = str(
        topic
        or ""
    ).strip()

    query = str(
        query
        or ""
    ).strip()

    source_text = str(
        source_text
        or ""
    ).strip()

    source_url = _normalize_source_url(
        source_url
    )

    scope = str(
        scope
        or ""
    ).strip()

    using_standing = False
    using_followup = False
    guardian = None
    authorization_token_for_store = ""
    payload: dict[str, Any]

    if mode == "current_turn":
        if (
            not topic
            or not query
            or not source_text
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_EXTERNAL_LEARNING_SCOPE",
            }

        if (
            scope
            != "single_research_session"
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_EXTERNAL_LEARNING_SCOPE",
            }

        parsed = (
            parse_direct_external_learning_order(
                source_text
            )
        )

        if (
            parsed is None
            or not _current_turn_authority_matches(
                parsed=parsed,
                topic=topic,
                query=query,
                source_url=source_url,
                standing_public_web_read_only_grant=(
                    standing_public_web_read_only_grant
                ),
            )
        ):
            return {
                "ok": False,
                "error":
                    "SEMANTIC_AUTHORITY_REVALIDATION_FAILED",
            }

        guardian = autonomy_guardian()

        payload = {
            "topic": topic,
            "query": query,
            "deep": bool(deep),
            "scope":
                "single_research_session",
            "source_url": (
                source_url
                or None
            ),
        }

        using_standing = bool(
            guardian.has_standing_public_web_learning()
        )

        if using_standing:
            authorization_token_for_store = (
                "STANDING"
            )
        else:
            authorization = (
                guardian.record_direct_authorization(
                    capability="external_learning",
                    payload=payload,
                    description=(
                        "bounded external learning for "
                        f"{topic[:220]}"
                    ),
                    source_text=source_text,
                )
            )

            if not authorization.get("ok"):
                return {
                    "ok": False,
                    "error":
                        "DIRECT_AUTHORIZATION_RECORD_FAILED",
                }

            authorization_token_for_store = (
                "DIRECT"
            )

            if bool(
                standing_public_web_read_only_grant
            ):
                standing_result = (
                    guardian.grant_standing_public_web_learning(
                        source_text
                    )
                )

                if not standing_result.get(
                    "ok"
                ):
                    return {
                        "ok": False,
                        "error":
                            "STANDING_WEB_GRANT_FAILED",
                    }

                if _EVENTS is not None:
                    _EVENTS.emit(
                        "OWNER_STANDING_PUBLIC_WEB_LEARNING_GRANTED",
                        scope=(
                            "public_web_read_only_learning"
                        ),
                    )

    elif mode == "followup_url":
        if (
            not topic
            or not query
            or not source_text
            or not source_url
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_FOLLOWUP_EXTERNAL_LEARNING_SCOPE",
            }

        if (
            scope
            != "single_research_session"
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_FOLLOWUP_EXTERNAL_LEARNING_SCOPE",
            }

        if (
            bool(
                standing_public_web_read_only_grant
            )
            or query != topic
        ):
            return {
                "ok": False,
                "error":
                    "FOLLOWUP_AUTHORITY_SCOPE_MISMATCH",
            }

        exact_source_url = (
            isolated_public_url(
                source_text
            )
        )

        argument_source_url = (
            isolated_public_url(
                source_url
            )
        )

        if (
            not exact_source_url
            or not argument_source_url
            or exact_source_url
            != argument_source_url
        ):
            return {
                "ok": False,
                "error":
                    "FOLLOWUP_URL_SCOPE_INVALID",
            }

        consumed_followup = (
            consume_learning_followup_context(
                topic=topic,
                source_url=source_url,
                source_text=source_text,
                max_age_seconds=300.0,
            )
        )

        if (
            not consumed_followup.get("ok")
            or not consumed_followup.get(
                "consumed"
            )
        ):
            return {
                "ok": False,
                "error": str(
                    consumed_followup.get(
                        "error"
                    )
                    or
                    "FOLLOWUP_CONTEXT_CONSUMPTION_FAILED"
                ),
            }

        # Referent context is consumed before network access.
        # No grant or reusable authority is created.
        using_followup = True

        authorization_token_for_store = (
            "FOLLOWUP_CONTEXT"
        )

        payload = {
            "topic": topic,
            "query": query,
            "deep": bool(deep),
            "scope":
                "single_research_session",
            "source_url":
                source_url,
        }

    else:
        exact_payload = dict(
            authorized_payload
            or {}
        )

        token = str(
            authorization_token
            or ""
        ).strip().upper()

        approved_action = str(
            authorization_action
            or ""
        ).strip()[:80]

        if (
            not token
            or approved_action
            not in {
                "external_learning",
                "external_learning_resume_query",
            }
            or not exact_payload
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_APPROVED_EXTERNAL_LEARNING_GRANT",
            }

        payload_topic = str(
            exact_payload.get("topic")
            or ""
        ).strip()

        payload_query = str(
            exact_payload.get("query")
            or ""
        ).strip()

        payload_source_url = (
            _normalize_source_url(
                exact_payload.get(
                    "source_url"
                )
            )
        )

        payload_deep = bool(
            exact_payload.get(
                "deep",
                False,
            )
        )

        payload_scope = str(
            exact_payload.get(
                "scope"
            )
            or ""
        ).strip()

        if (
            not payload_topic
            or not payload_query
            or payload_scope
            != "single_research_session"
        ):
            return {
                "ok": False,
                "error":
                    "INVALID_APPROVED_EXTERNAL_LEARNING_SCOPE",
            }

        # Top-level arguments are duplicated deliberately so ToolRegistry
        # validation and runtime execution agree on the same scope.
        if (
            topic != payload_topic
            or query != payload_query
            or bool(deep) != payload_deep
            or scope != payload_scope
            or source_url
            != payload_source_url
        ):
            return {
                "ok": False,
                "error":
                    "APPROVED_GRANT_ARGUMENT_MISMATCH",
            }

        guardian = autonomy_guardian()

        consumed = (
            guardian.consume_authorized_grant(
                token=token,
                capability="external_learning",
                payload=exact_payload,
                action=approved_action,
            )
        )

        if (
            not consumed.get("ok")
            or not consumed.get("allowed")
        ):
            return {
                "ok": False,
                "error": str(
                    consumed.get("error")
                    or "APPROVED_GRANT_CONSUMPTION_FAILED"
                ),
            }

        payload = exact_payload
        topic = payload_topic
        query = payload_query
        source_url = payload_source_url
        deep = payload_deep

        authorization_token_for_store = (
            token
        )

    if _RESEARCH_ENGINE is None:
        return {
            "ok": False,
            "error":
                "EXTERNAL_LEARNING_RUNTIME_NOT_CONFIGURED",
        }

    if not _RESEARCH_ENGINE.available():
        return {
            "ok": False,
            "error":
                "PRIVACY_OR_RESEARCH_DISABLED",
        }

    if source_url:
        result = (
            _RESEARCH_ENGINE.research_url(
                source_url,
                query=query,
                topic=topic,
                deep=bool(deep),
            )
        )
    else:
        result = (
            _RESEARCH_ENGINE.research(
                query,
                topic=topic,
                deep=bool(deep),
                search_query=topic,
            )
        )

    if not result.ok:
        if using_standing:
            return {
                "ok": False,
                "error": str(
                    result.reason_code
                    or result.error
                    or "RESEARCH_FAILED"
                ),
                "standing_permission_preserved":
                    True,
            }

        if using_followup:
            return {
                "ok": False,
                "error": str(
                    result.reason_code
                    or result.error
                    or "RESEARCH_FAILED"
                ),
                "followup_context_consumed":
                    True,
            }

        retry = (
            queue_external_learning_retry(
                payload=payload,
                topic=topic,
                error=result.error,
            )
        )

        return {
            "ok": False,
            "error": str(
                result.error
                or "RESEARCH_FAILED"
            ),
            "retry":
                retry.get("retry"),
        }

    stored = authorized_learning().add(
        topic=topic,
        query=query,
        summary=result.text,
        model=result.model,
        authorization_token=(
            authorization_token_for_store
        ),
        sources=result.sources or [],
        source_type=(
            "authorized_followup_url_local_model_summary_v2"
            if using_followup
            else
            "authorized_direct_web_local_model_summary_v2"
        ),
    )

    if (
        not stored.get("ok")
        or not stored.get("stored")
    ):
        error = str(
            stored.get("error")
            or "LEARNING_STORE_REJECTED"
        )

        if using_standing:
            return {
                "ok": False,
                "error": error,
                "standing_permission_preserved":
                    True,
            }

        if using_followup:
            return {
                "ok": False,
                "error": error,
                "followup_context_consumed":
                    True,
            }

        retry = (
            queue_external_learning_retry(
                payload=payload,
                topic=topic,
                error=error,
            )
        )

        return {
            "ok": False,
            "error": error,
            "retry":
                retry.get("retry"),
        }

    if _EVENTS is not None:
        _EVENTS.emit(
            (
                "AUTHORIZED_EXTERNAL_LEARNING_STORED"
                if mode == "approved_grant"
                else (
                    "FOLLOWUP_CONTEXT_EXTERNAL_LEARNING_STORED"
                    if mode == "followup_url"
                    else
                    "DIRECT_AUTHORIZED_EXTERNAL_LEARNING_STORED"
                )
            ),
            topic=topic,
            stored=stored,
        )

    return {
        "ok": True,
        "stored": True,
        "topic": topic,
        "summary": str(
            result.text
            or ""
        ),
        "model": result.model,
        "sources":
            result.sources or [],
        "authority_mode": mode,
        "authorization": (
            "standing"
            if using_standing
            else (
                "approved_grant"
                if mode == "approved_grant"
                else (
                    "followup_context"
                    if mode == "followup_url"
                    else "direct"
                )
            )
        ),
        "authorization_token": (
            authorization_token_for_store
        ),
        "standing_permission_active":
            bool(
                guardian is not None
                and guardian.has_standing_public_web_learning()
            ),
    }
