"""JARVIS Web test-suite compatibility bootstrap.

Starlette's released TestClient currently still references the deprecated
``anyio.abc.BlockingPortal`` alias. AnyIO exposes the supported class from
``anyio.from_thread.BlockingPortal``.

Keep this test-only alias until Starlette ships the upstream fix, then remove it.
This does not modify JARVIS runtime behavior and does not suppress warnings.
"""

import anyio.abc
import anyio.from_thread


# Test-only compatibility bridge for the released Starlette TestClient.
# Assignment is intentionally performed before test modules import TestClient.
anyio.abc.BlockingPortal = anyio.from_thread.BlockingPortal


import pytest


@pytest.fixture(autouse=True)
def isolate_jarvis_runtime_state(monkeypatch, tmp_path):
    """Hard isolation between pytest and real JARVIS user state.

    Any app created by a test gets:
    - a unique temporary encrypted conversation store;
    - a unique temporary security-audit log.

    This fixture is autouse on purpose: a future test cannot forget to opt in.
    """
    test_state = tmp_path / "jarvis-test-runtime"
    test_state.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv(
        "JARVIS_WEB_SESSION_FILE",
        str(test_state / "sessions.dpapi"),
    )
    monkeypatch.setenv(
        "JARVIS_WEB_TEST_AUDIT_FILE",
        str(test_state / "security-audit.jsonl"),
    )
