from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis_web.backend.app import create_app
from jarvis_web.backend.session_store import SessionStorageError, SessionStore
from jarvis_web.tests.auth_helpers import TEST_BOOTSTRAP_TOKEN


def test_default_store_during_pytest_is_in_temp_runtime(tmp_path: Path) -> None:
    store = SessionStore()
    configured = Path(os.environ["JARVIS_WEB_SESSION_FILE"])
    assert store.path == configured
    assert str(store.path).startswith(str(tmp_path))


def test_app_audit_log_during_pytest_is_in_temp_runtime(tmp_path: Path) -> None:
    app = create_app(bootstrap_token=TEST_BOOTSTRAP_TOKEN)
    with TestClient(app):
        configured = Path(os.environ["JARVIS_WEB_TEST_AUDIT_FILE"])
        assert app.state.security_audit.path == configured
        assert str(app.state.security_audit.path).startswith(str(tmp_path))


def test_session_store_fails_closed_if_pytest_isolation_env_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.delenv("JARVIS_WEB_SESSION_FILE", raising=False)
    with pytest.raises(SessionStorageError, match="Refusing to use production"):
        SessionStore()


def test_app_fails_closed_if_pytest_audit_isolation_env_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.delenv("JARVIS_WEB_TEST_AUDIT_FILE", raising=False)
    app = create_app(bootstrap_token=TEST_BOOTSTRAP_TOKEN)
    with pytest.raises(RuntimeError, match="Refusing to use production security audit"):
        with TestClient(app):
            pass


def test_api_mutation_only_changes_test_store(tmp_path: Path) -> None:
    app = create_app(bootstrap_token=TEST_BOOTSTRAP_TOKEN)
    with TestClient(app) as client:
        bootstrap = client.get(
            "/auth/bootstrap",
            params={"token": TEST_BOOTSTRAP_TOKEN},
            follow_redirects=False,
        )
        assert bootstrap.status_code == 303
        created = client.post("/api/sessions")
        assert created.status_code == 201

        configured = Path(os.environ["JARVIS_WEB_SESSION_FILE"])
        assert configured.exists()
        assert str(configured).startswith(str(tmp_path))
