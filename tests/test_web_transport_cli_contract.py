from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "jarvis_core" / "cli.py"


def _call_text(source: str, node: ast.AST) -> str:
    return (
        ast.get_source_segment(source, node)
        or ""
    ).strip()


def test_web_transport_is_composed_into_existing_cli_application() -> None:
    source = CLI.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert (
        "from jarvis_web.transport_runner "
        "import WebTransportRunner"
    ) in source

    assert source.count(
        "bootstrap = build_application()"
    ) == 1

    assert source.count(
        "web_transport = WebTransportRunner()"
    ) == 1

    assert source.count(
        "web_transport.start(application)"
    ) == 1

    assert source.count(
        "web_transport.stop()"
    ) == 1

    assert source.index(
        "application.start_runtime_services()"
    ) < source.index(
        "web_transport.start(application)"
    )

    main_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "main"
    )

    shutdown_try = None

    for node in ast.walk(main_node):
        if not isinstance(node, ast.Try):
            continue

        final_text = "\n".join(
            ast.get_source_segment(source, item)
            or ""
            for item in node.finalbody
        )

        if "application.stop_runtime_services()" in final_text:
            shutdown_try = node
            break

    assert shutdown_try is not None

    assert _call_text(
        source,
        shutdown_try.body[0],
    ) == "web_transport.start(application)"

    assert len(shutdown_try.finalbody) == 1
    assert isinstance(
        shutdown_try.finalbody[0],
        ast.Try,
    )

    cleanup_guard = shutdown_try.finalbody[0]

    assert _call_text(
        source,
        cleanup_guard.body[0],
    ) == "web_transport.stop()"

    guaranteed_cleanup = "\n".join(
        ast.get_source_segment(source, item)
        or ""
        for item in cleanup_guard.finalbody
    )

    assert (
        "application.stop_activity_trace()"
        in guaranteed_cleanup
    )

    assert (
        "application.release_models_on_shutdown()"
        in guaranteed_cleanup
    )

    assert (
        "application.stop_runtime_services()"
        in guaranteed_cleanup
    )
