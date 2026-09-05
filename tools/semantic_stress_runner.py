from pathlib import Path
import argparse
import collections
import datetime as dt
import json
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT),
    )

from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)

DEFAULT_CASES = (
    ROOT
    / "tests"
    / "semantic_stress_cases.json"
)

AUDIT_DIR = ROOT / "Audit"


APP_ALIASES = {
    "brave": "brave",
    "brave browser": "brave",
    "spotify": "spotify",
    "bloco de notas": "bloco de notas",
    "calculadora": "calculadora",
}


def semantic_inputs_for_case(
    case: dict[str, Any],
) -> tuple[list[dict], dict[str, str]]:
    category = str(
        case.get("category")
        or ""
    )

    recent_turns: list[dict] = []

    if category == "self_state_followup":
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

    elif category == "social_followup":
        recent_turns = [
            {
                "user": "Provoca-me",
                "assistant": (
                    "Interacao social ativa."
                ),
                "route": (
                    "FAST/social_interaction"
                ),
            }
        ]

    return (
        recent_turns,
        dict(APP_ALIASES),
    )


def plain_request(request: Any) -> dict[str, Any]:
    if hasattr(request, "as_dict"):
        data = request.as_dict()
    else:
        data = {
            name: getattr(request, name, None)
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

    return dict(data)


def compare(
    actual: dict[str, Any],
    expected: dict[str, Any],
) -> list[str]:
    failures = []

    forbid_tool = bool(
        expected.get("forbid_tool")
    )

    if forbid_tool:
        if actual.get("requires_tool"):
            failures.append(
                "requires_tool=True but tool use is forbidden"
            )

        if actual.get("preferred_tool"):
            failures.append(
                "preferred_tool="
                + repr(actual.get("preferred_tool"))
                + " but tool use is forbidden"
            )

    for field in (
        "intent",
        "requires_tool",
        "preferred_tool",
        "subject",
        "action",
        "target",
    ):
        if field not in expected:
            continue

        wanted = expected[field]
        got = actual.get(field)

        if isinstance(wanted, list):
            if got not in wanted:
                failures.append(
                    f"{field}: expected one of "
                    f"{wanted!r}, got {got!r}"
                )
        elif got != wanted:
            failures.append(
                f"{field}: expected "
                f"{wanted!r}, got {got!r}"
            )

    return failures


def load_cases(
    path: Path,
) -> list[dict[str, Any]]:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    cases = payload.get("cases")

    if not isinstance(cases, list):
        raise SystemExit(
            "Invalid stress corpus: cases must be a list"
        )

    return cases


def markdown_report(
    report: dict[str, Any],
) -> str:
    lines = [
        "# JARVIS Semantic Stress Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Total: {report['summary']['total']}",
        f"- PASS: {report['summary']['passed']}",
        f"- FAIL: {report['summary']['failed']}",
        "",
        "## Failure clusters",
        "",
        "| Category | Total | PASS | FAIL |",
        "|---|---:|---:|---:|",
    ]

    for category, data in sorted(
        report["categories"].items()
    ):
        lines.append(
            f"| {category} | "
            f"{data['total']} | "
            f"{data['passed']} | "
            f"{data['failed']} |"
        )

    lines.extend([
        "",
        "## Failures",
        "",
    ])

    failures = [
        item
        for item in report["results"]
        if not item["passed"]
    ]

    if not failures:
        lines.append(
            "No failures."
        )
        return "\n".join(lines) + "\n"

    for item in failures:
        lines.extend([
            f"### {item['id']} — "
            f"{item['category']}",
            "",
            f"**Input:** `{item['text']}`",
            "",
            "**Problems:**",
            "",
        ])

        for problem in item["failures"]:
            lines.append(
                f"- {problem}"
            )

        lines.extend([
            "",
            "**Actual semantic request:**",
            "",
            "```json",
            json.dumps(
                item["actual"],
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ])

        if item.get("notes"):
            lines.extend([
                f"Notes: {item['notes']}",
                "",
            ])

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Safe JARVIS semantic stress runner. "
            "It never executes tools."
        )
    )

    parser.add_argument(
        "--cases",
        default=str(DEFAULT_CASES),
    )

    parser.add_argument(
        "--category",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--id",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit non-zero when semantic failures exist."
        ),
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
    )

    parser.add_argument(
        "--no-report",
        action="store_true",
    )

    args = parser.parse_args()

    cases_path = Path(args.cases)

    if not cases_path.is_absolute():
        cases_path = (
            ROOT / cases_path
        ).resolve()

    cases = load_cases(cases_path)

    category_filter = {
        item.strip()
        for item in args.category
        if item.strip()
    }

    id_filter = {
        item.strip()
        for item in args.id
        if item.strip()
    }

    if category_filter:
        cases = [
            case
            for case in cases
            if case.get("category")
            in category_filter
        ]

    if id_filter:
        cases = [
            case
            for case in cases
            if case.get("id")
            in id_filter
        ]

    results = []
    counters = collections.defaultdict(
        lambda: {
            "total": 0,
            "passed": 0,
            "failed": 0,
        }
    )

    for case in cases:
        case_id = str(case.get("id") or "")
        category = str(
            case.get("category")
            or "uncategorized"
        )
        text = str(case.get("text") or "")
        expected = dict(
            case.get("expected") or {}
        )

        try:
            (
                semantic_recent_turns,
                semantic_app_aliases,
            ) = semantic_inputs_for_case(
                case
            )

            request = resolve_semantic_request(
                text,
                recent_turns=semantic_recent_turns,
                app_aliases=semantic_app_aliases,
            )
            actual = plain_request(request)
            failures = compare(
                actual,
                expected,
            )
        except Exception as exc:
            actual = {}
            failures = [
                "resolver exception: "
                f"{type(exc).__name__}: {exc}"
            ]

        passed = not failures

        counters[category]["total"] += 1
        counters[category][
            "passed" if passed else "failed"
        ] += 1

        result = {
            "id": case_id,
            "category": category,
            "text": text,
            "expected": expected,
            "actual": actual,
            "passed": passed,
            "failures": failures,
            "notes": str(
                case.get("notes") or ""
            ),
        }

        results.append(result)

        if not args.quiet:
            marker = (
                "PASS"
                if passed
                else "FAIL"
            )

            print(
                f"[{marker}] "
                f"{case_id:<24} "
                f"{category:<24} "
                f"{text}"
            )

            if failures:
                for failure in failures:
                    print(
                        "       -",
                        failure,
                    )

    total = len(results)
    passed = sum(
        1
        for result in results
        if result["passed"]
    )
    failed = total - passed

    generated_at = (
        dt.datetime.now(
            dt.timezone.utc
        )
        .astimezone()
        .isoformat(
            timespec="seconds"
        )
    )

    report = {
        "generated_at": generated_at,
        "mode": "semantic_safe",
        "safety": {
            "qwen_called": False,
            "tool_registry_execute_called": False,
            "operating_system_actions": False,
        },
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
        },
        "categories": dict(counters),
        "results": results,
    }

    print()
    print("=" * 72)
    print("JARVIS SEMANTIC STRESS SUMMARY")
    print("=" * 72)
    print("TOTAL :", total)
    print("PASS  :", passed)
    print("FAIL  :", failed)

    if counters:
        print()
        print("BY CATEGORY")

        for category, data in sorted(
            counters.items()
        ):
            marker = (
                "PASS"
                if data["failed"] == 0
                else "FAIL"
            )

            print(
                f"{category:<26} "
                f"{data['passed']:>3}/"
                f"{data['total']:<3} {marker}"
            )

    if not args.no_report:
        AUDIT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        stamp = (
            dt.datetime.now()
            .strftime(
                "%Y-%m-%d_%H%M%S"
            )
        )

        json_path = (
            AUDIT_DIR
            / (
                "semantic_stress_report_"
                + stamp
                + ".json"
            )
        )

        md_path = (
            AUDIT_DIR
            / (
                "semantic_stress_report_"
                + stamp
                + ".md"
            )
        )

        json_path.write_text(
            json.dumps(
                report,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        md_path.write_text(
            markdown_report(report),
            encoding="utf-8",
            newline="\n",
        )

        print()
        print("REPORT JSON:", json_path)
        print("REPORT MD  :", md_path)

    # A stress runner is a quality gate: failures must
    # always produce a non-zero process exit code.
    if failed:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())