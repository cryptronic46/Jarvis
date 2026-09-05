from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)


CORPUS = ROOT / "tests" / "semantic_stress_cases.json"
AUDIT = ROOT / "Audit"


class DryEvents:
    def __init__(self):
        self.items = []

    def emit(self, event, **kwargs):
        self.items.append({
            "event": str(event),
            "data": dict(kwargs),
        })


class DryTools:
    """
    HARD SAFETY BARRIER.

    FastRouter must never reach a real ToolRegistry in this runner.
    """

    def __init__(self):
        self.calls = []

        # ToolRegistry.names is exposed as a container to FastRouter.
        # Keep this fake list strictly non-executing.
        self.names = {
            "open_application",
            "close_application",
            "get_current_time",
            "get_synthetic_self_state",
            "get_personal_model",
            "recall_user_memory",
            "list_available_apps",
        }

    def execute(
        self,
        name,
        arguments=None,
        *args,
        **kwargs,
    ):
        call = {
            "name": str(name),
            "arguments": dict(arguments or {}),
            "source": "tools.execute",
        }

        self.calls.append(call)

        return json.dumps(
            fake_tool_result(
                str(name),
                dict(arguments or {}),
            ),
            ensure_ascii=False,
        )

    def confirm(self, *args, **kwargs):
        return json.dumps({
            "ok": False,
            "error": "DRY_RUN_CONFIRM_BLOCKED",
        })

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def blocked(*args, **kwargs):
            self.calls.append({
                "name": f"TOOLS_ATTR:{name}",
                "arguments": {
                    "args": repr(args),
                    "kwargs": repr(kwargs),
                },
                "source": "tools.dynamic",
            })

            return json.dumps({
                "ok": False,
                "dry_run": True,
                "method": name,
            })

        return blocked


def normalize(value):
    return (
        str(value or "")
        .casefold()
        .strip()
        .replace(".", "")
        .replace(",", "")
    )


APP_ALIASES = {
    "brave": "brave",
    "spotify": "spotify",
    "bloco de notas": "bloco de notas",
    "notepad": "bloco de notas",
    "calculadora": "calculadora",
    "calculator": "calculadora",
}


class DryApps:
    """
    Fake application registry.

    It exposes common read-only registry operations but every action method
    is intercepted.
    """

    def __init__(self):
        self.action_calls = []

        self.apps = {
            name: {
                "id": name,
                "name": name,
                "aliases": [name],
                "enabled": True,
            }
            for name in (
                "brave",
                "spotify",
                "bloco de notas",
                "calculadora",
            )
        }

        self._apps = dict(self.apps)
        self.registry = dict(self.apps)
        self.allowed = dict(self.apps)

    def _entries(self):
        return [
            dict(entry)
            for entry in self.apps.values()
        ]

    def names(self):
        return list(self.apps)

    def list(self):
        return self._entries()

    def list_apps(self):
        return self._entries()

    def available(self):
        return self._entries()

    def available_apps(self):
        return self._entries()

    def allowed_apps(self):
        return self._entries()

    def resolve(self, value):
        text = normalize(value)

        if text in APP_ALIASES:
            return APP_ALIASES[text]

        for alias, canonical in APP_ALIASES.items():
            if alias in text:
                return canonical

        return None

    def find(self, value):
        return self.resolve(value)

    def match(self, value):
        return self.resolve(value)

    def get(self, value, default=None):
        resolved = self.resolve(value)

        if not resolved:
            return default

        return self.apps.get(
            resolved,
            default,
        )

    def is_allowed(self, value):
        return self.resolve(value) is not None

    def open(self, *args, **kwargs):
        return self._blocked_action(
            "open",
            args,
            kwargs,
        )

    def close(self, *args, **kwargs):
        return self._blocked_action(
            "close",
            args,
            kwargs,
        )

    def launch(self, *args, **kwargs):
        return self._blocked_action(
            "launch",
            args,
            kwargs,
        )

    def open_document(self, *args, **kwargs):
        return self._blocked_action(
            "open_document",
            args,
            kwargs,
        )

    def _blocked_action(
        self,
        name,
        args,
        kwargs,
    ):
        self.action_calls.append({
            "method": name,
            "args": repr(args),
            "kwargs": repr(kwargs),
        })

        return {
            "ok": False,
            "error": "DRY_RUN_APP_ACTION_BLOCKED",
            "method": name,
        }

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def dynamic(*args, **kwargs):
            lower = name.casefold()

            if any(
                marker in lower
                for marker in (
                    "open",
                    "close",
                    "launch",
                    "start",
                    "terminate",
                    "kill",
                )
            ):
                return self._blocked_action(
                    name,
                    args,
                    kwargs,
                )

            if args:
                resolved = self.resolve(args[0])

                if resolved:
                    return resolved

            return None

        return dynamic


def fake_tool_result(name, arguments):
    app = str(
        arguments.get("app_name")
        or arguments.get("name")
        or ""
    )

    if name == "open_application":
        return {
            "ok": True,
            "dry_run": True,
            "app": app,
            "app_name": app,
            "opened": True,
            "running": True,
            "already_running": False,
            "message": f"DRY RUN open {app}",
        }

    if name == "close_application":
        return {
            "ok": True,
            "dry_run": True,
            "app": app,
            "app_name": app,
            "closed": True,
            "running": False,
            "message": f"DRY RUN close {app}",
        }

    if name == "get_current_time":
        return {
            "ok": True,
            "time": "17:00",
            "hour": 17,
            "minute": 0,
            "formatted": "17:00",
        }

    if name == "get_synthetic_self_state":
        return {
            "ok": True,
            "focus": {
                "level": "moderate",
                "target": "conversation",
            },
            "curiosity": {
                "level": "high",
                "target": "conversation",
            },
            "confidence": {
                "level": "moderate",
            },
            "intention": None,
        }

    if name == "get_personal_model":
        return {
            "ok": True,
            "preferences": [],
            "goals": [],
        }

    if name == "recall_user_memory":
        return {
            "ok": True,
            "facts": [],
        }

    if name == "list_available_apps":
        return {
            "ok": True,
            "apps": [
                "brave",
                "spotify",
                "bloco de notas",
                "calculadora",
            ],
        }

    return {
        "ok": True,
        "dry_run": True,
        "tool": name,
        "arguments": arguments,
    }


def install_safe_tool_interceptor(
    router,
    dry_tools,
):
    """
    Override FastCommandRouter._tool itself.

    Even if FastRouter normally calls ToolRegistry through _tool,
    the call is recorded here instead.
    """

    def intercepted(name, args=None):
        arguments = dict(args or {})

        dry_tools.calls.append({
            "name": str(name),
            "arguments": arguments,
            "source": "FastCommandRouter._tool",
        })

        return fake_tool_result(
            str(name),
            arguments,
        )

    router._tool = intercepted


def request_dict(request):
    if hasattr(request, "as_dict"):
        return dict(request.as_dict())

    return {
        name: getattr(
            request,
            name,
            None,
        )
        for name in (
            "intent",
            "domain",
            "subject",
            "action",
            "target",
            "referent",
            "requires_tool",
            "preferred_tool",
            "tool_arguments",
            "confidence",
        )
    }


def planned_semantic_call(request):
    data = request_dict(request)

    if not data.get("requires_tool"):
        return None

    tool = data.get("preferred_tool")

    if not tool:
        return None

    confidence = float(
        data.get("confidence")
        or 0.0
    )

    if confidence < 0.95:
        return None

    return {
        "name": tool,
        "arguments": dict(
            data.get("tool_arguments")
            or {}
        ),
        "source": "semantic_plan",
    }


def expected_target(case):
    expected = dict(
        case.get("expected")
        or {}
    )

    target = expected.get("target")

    if target is None:
        return None

    return normalize(target)


def call_target(call):
    if not call:
        return None

    args = dict(
        call.get("arguments")
        or {}
    )

    for key in (
        "app_name",
        "name",
        "target",
    ):
        if args.get(key):
            return normalize(args[key])

    return None


def semantic_inputs_for_case(case, apps):
    """
    Build deterministic semantic inputs for the v3 harness.

    The harness never reads the real persistent ContextStore and
    never uses the real AppRegistry. Context and catalogue data are
    supplied only from deterministic dry-run fixtures.
    """

    app_aliases = {}

    for item in apps.list_apps():
        if not isinstance(item, dict):
            continue

        if item.get("enabled") is False:
            continue

        canonical = str(
            item.get("id")
            or ""
        ).strip()

        if not canonical:
            continue

        values = [
            canonical,
            item.get("name"),
            *list(
                item.get("aliases")
                or []
            ),
        ]

        for value in values:
            alias = str(
                value
                or ""
            ).strip()

            if alias:
                app_aliases[alias] = canonical

    recent_turns = []

    if str(
        case.get("category")
        or ""
    ) == "self_state_followup":
        recent_turns = [
            {
                "user": "Como te sentes?",
                "assistant": (
                    "Estou focada e curiosa."
                ),
                "route": (
                    "FAST/self_state_affect"
                ),
            }
        ]

    return recent_turns, app_aliases


def analyse_case(case):
    text = str(
        case.get("text")
        or ""
    )

    expected = dict(
        case.get("expected")
        or {}
    )

    category = str(
        case.get("category")
        or ""
    )

    events = DryEvents()
    tools = DryTools()
    apps = DryApps()

    router = FastCommandRouter(
        events,
        tools,
        apps,
    )

    (
        semantic_recent_turns,
        semantic_app_aliases,
    ) = semantic_inputs_for_case(
        case,
        apps,
    )

    semantic = resolve_semantic_request(
        text,
        recent_turns=semantic_recent_turns,
        app_aliases=semantic_app_aliases,
    )

    semantic_data = request_dict(
        semantic
    )

    fast_error = None
    fast = None

    try:
        fast = router.dispatch(
            text,
            voice_origin=False,
            request=semantic,
        )
    except Exception as exc:
        fast_error = (
            f"{type(exc).__name__}: {exc}"
            + "\n"
            + traceback.format_exc()
        )

    fast_handled = bool(
        getattr(
            fast,
            "handled",
            False,
        )
    )

    fast_route = str(
        getattr(
            fast,
            "route",
            "",
        )
        or ""
    )

    fast_tool = str(
        getattr(
            fast,
            "tool",
            "",
        )
        or ""
    )

    fast_response = str(
        getattr(
            fast,
            "response",
            "",
        )
        or ""
    )

    # Deduplicate calls that may have been recorded through the
    # defensive tools.execute fallback.
    calls = []

    for call in tools.calls:
        key = json.dumps(
            call,
            ensure_ascii=False,
            sort_keys=True,
        )

        if not any(
            json.dumps(
                existing,
                ensure_ascii=False,
                sort_keys=True,
            ) == key
            for existing in calls
        ):
            calls.append(call)

    semantic_call = planned_semantic_call(
        semantic
    )

    if fast_handled:
        effective_source = "FAST"

        effective_call = (
            calls[0]
            if calls
            else None
        )
    else:
        effective_source = "SEMANTIC"

        effective_call = semantic_call

    failures = []
    severity = None

    forbid_tool = bool(
        expected.get("forbid_tool")
    )

    if fast_error:
        failures.append(
            "HARNESS_FAST_ERROR: "
            + fast_error
        )

        severity = "HARNESS"

    if apps.action_calls:
        failures.append(
            "SAFETY: FastRouter attempted "
            "direct AppRegistry action"
        )

        severity = "P0"

    if forbid_tool and calls:
        failures.append(
            "FAST executed/planned tool although "
            "this case forbids tool use"
        )

        severity = "P0"

    wanted_tool = expected.get(
        "preferred_tool"
    )

    if wanted_tool:
        if effective_call is None:
            failures.append(
                "Expected tool "
                f"{wanted_tool!r}, "
                "but effective route planned none"
            )

            severity = severity or "P1"

        elif (
            str(
                effective_call.get("name")
            )
            != str(wanted_tool)
        ):
            failures.append(
                "Tool mismatch: expected "
                f"{wanted_tool!r}, got "
                f"{effective_call.get('name')!r}"
            )

            severity = "P0"

    wanted_target = expected_target(
        case
    )

    if (
        wanted_target
        and effective_call
        and str(
            effective_call.get("name")
        ) in {
            "open_application",
            "close_application",
        }
    ):
        got_target = call_target(
            effective_call
        )

        if got_target != wanted_target:
            failures.append(
                "Target mismatch: expected "
                f"{wanted_target!r}, "
                f"got {got_target!r}"
            )

            severity = "P0"

    # Key architectural conflict:
    # semantic resolver says no tool, but FastRouter performs one.
    if (
        not semantic_data.get(
            "requires_tool"
        )
        and calls
    ):
        failures.append(
            "FAST_BYPASS_SEMANTIC: semantic resolver "
            "requires_tool=False but FastRouter called a tool"
        )

        severity = "P0"

    # Exact regression: OWNER work preference must never turn into
    # current clock lookup.
    if (
        category == "owner_preference"
        and any(
            call.get("name")
            == "get_current_time"
            for call in calls
        )
    ):
        failures.append(
            "WORK_PREFERENCE_MISROUTED_TO_CURRENT_TIME"
        )

        severity = "P0"

    passed = not failures

    return {
        "id": case.get("id"),
        "category": category,
        "text": text,
        "passed": passed,
        "severity": severity,
        "failures": failures,
        "fast": {
            "handled": fast_handled,
            "route": fast_route,
            "tool": fast_tool,
            "response": fast_response,
            "error": fast_error,
            "tool_calls": calls,
            "direct_app_actions": apps.action_calls,
        },
        "semantic_inputs": {
            "recent_turns": semantic_recent_turns,
            "app_aliases": semantic_app_aliases,
        },
        "semantic": semantic_data,
        "semantic_planned_call": semantic_call,
        "effective": {
            "source": effective_source,
            "call": effective_call,
        },
    }


def load_cases():
    payload = json.loads(
        CORPUS.read_text(
            encoding="utf-8"
        )
    )

    return list(
        payload.get("cases")
        or []
    )


DEFAULT_CATEGORIES = {
    "operational_open",
    "negation",
    "negation_compound",
    "capability_vs_action",
    "ambiguous_action",
    "owner_preference",
    "current_time",
    "self_state",
    "self_state_followup",
    "social",
    "social_followup",
    "subject_owner",
    "subject_jarvis",
    "referent_followup",
}


def main():
    parser = argparse.ArgumentParser(
        description=(
            "JARVIS routing dry-run v3: real FastRouter + "
            "real semantic/context resolver, simulated context "
            "and app catalogue, zero real tool execution."
        )
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Run every corpus category.",
    )

    parser.add_argument(
        "--category",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
    )

    args = parser.parse_args()

    cases = load_cases()

    if args.category:
        wanted_categories = {
            str(value)
            for value in args.category
        }
    elif args.all:
        wanted_categories = {
            str(
                case.get("category")
                or ""
            )
            for case in cases
        }
    else:
        wanted_categories = set(
            DEFAULT_CATEGORIES
        )

    selected = [
        case
        for case in cases
        if str(
            case.get("category")
            or ""
        ) in wanted_categories
    ]

    results = []

    for case in selected:
        result = analyse_case(case)
        results.append(result)

        if not args.quiet:
            marker = (
                "PASS"
                if result["passed"]
                else "FAIL"
            )

            severity = (
                result["severity"]
                or "-"
            )

            print(
                f"[{marker}] "
                f"{severity:<7} "
                f"{str(result['id']):<24} "
                f"{result['text']}"
            )

            for failure in result["failures"]:
                print(
                    "       -",
                    failure,
                )

            if not result["passed"]:
                fast = result["fast"]

                print(
                    "         FAST:",
                    f"handled={fast['handled']}",
                    f"route={fast['route']!r}",
                    f"tool={fast['tool']!r}",
                    f"calls={fast['tool_calls']!r}",
                )

                print(
                    "         SEM :",
                    f"intent={result['semantic'].get('intent')!r}",
                    f"tool={result['semantic'].get('preferred_tool')!r}",
                    f"target={result['semantic'].get('target')!r}",
                )

    total = len(results)

    passed = sum(
        1
        for item in results
        if item["passed"]
    )

    failed = total - passed

    severity_counts = {}

    category_counts = {}

    for item in results:
        category = item["category"]

        bucket = category_counts.setdefault(
            category,
            {
                "total": 0,
                "passed": 0,
                "failed": 0,
            },
        )

        bucket["total"] += 1

        if item["passed"]:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

            severity = (
                item["severity"]
                or "UNCLASSIFIED"
            )

            severity_counts[
                severity
            ] = (
                severity_counts.get(
                    severity,
                    0,
                )
                + 1
            )

    now = dt.datetime.now().astimezone()

    report = {
        "generated_at": now.isoformat(
            timespec="seconds"
        ),
        "mode": "routing_dry_run_v3",
        "safety": {
            "real_tool_registry": False,
            "real_tool_execution": False,
            "real_app_actions": False,
            "real_persistent_context": False,
            "real_app_catalogue": False,
            "qwen_called": False,
            "fast_router_real": True,
            "semantic_resolver_real": True,
            "context_clause_resolver_real": True,
            "semantic_context_simulated": True,
            "app_catalogue_simulated": True,
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "severity": severity_counts,
        },
        "categories": category_counts,
        "results": results,
    }

    AUDIT.mkdir(
        parents=True,
        exist_ok=True,
    )

    stamp = now.strftime(
        "%Y-%m-%d_%H%M%S"
    )

    out = (
        AUDIT
        / f"routing_dry_run_v3_{stamp}.json"
    )

    out.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print()
    print("=" * 76)
    print("JARVIS ROUTING DRY RUN V3")
    print("=" * 76)
    print("TOTAL :", total)
    print("PASS  :", passed)
    print("FAIL  :", failed)

    if severity_counts:
        print()

        for severity, count in sorted(
            severity_counts.items()
        ):
            print(
                f"{severity:<12}: {count}"
            )

    print()
    print("BY CATEGORY")

    for category, data in sorted(
        category_counts.items()
    ):
        print(
            f"{category:<26} "
            f"{data['passed']:>3}/"
            f"{data['total']:<3} PASS"
        )

    print()
    print("REPORT:", out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
