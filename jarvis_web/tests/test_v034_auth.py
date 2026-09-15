import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from jarvis_web.backend.app import (
    _make_lifespan,
    create_app,
)


BOOTSTRAP = "auth-test-bootstrap-token-0123456789-abcdef"


def test_unauthenticated_local_post_is_rejected() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        response = client.post("/api/sessions")
        assert response.status_code == 401
        assert response.text == "Authentication required"


def test_health_remains_public_and_minimal() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_bootstrap_is_one_time_and_sets_httponly_cookie() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        first = client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )
        assert first.status_code == 303
        cookie = first.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie

        second = client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )
        assert second.status_code == 401


def test_authenticated_session_can_create_session() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        bootstrap = client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )
        assert bootstrap.status_code == 303

        response = client.post("/api/sessions")
        assert response.status_code == 201


def test_auth_status_changes_after_bootstrap() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        assert client.get("/api/auth/status").json()["authenticated"] is False

        client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )

        assert client.get("/api/auth/status").json()["authenticated"] is True


def test_websocket_without_session_is_rejected() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/events",
                headers={"Origin": "http://127.0.0.1:8766"},
            ):
                pass


def test_websocket_with_session_is_accepted() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )

        with client.websocket_connect(
            "/api/events",
            headers={"Origin": "http://127.0.0.1:8766"},
        ) as websocket:
            payload = websocket.receive_json()
            assert payload["type"] == "jarvis.ready"


def test_invalid_bootstrap_is_rejected() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        response = client.get(
            "/auth/bootstrap",
            params={"token": "x" * 32},
            follow_redirects=False,
        )
        assert response.status_code == 401



def test_unauthenticated_rename_is_rejected() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        response = client.patch(
            "/api/sessions/nonexistent",
            json={"title": "Blocked"},
        )
        assert response.status_code == 401



def test_bootstrap_cookie_security_attributes() -> None:
    with TestClient(create_app(bootstrap_token=BOOTSTRAP)) as client:
        response = client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )
        assert response.status_code == 303
        cookie = response.headers["set-cookie"].lower()
        assert "jarvis_local_session=" in cookie
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/" in cookie
        # Current localhost HTTP phase intentionally does not use Secure.
        assert "secure" not in cookie


def test_explicit_bootstrap_does_not_mutate_legacy_environment(
    monkeypatch,
) -> None:
    legacy_token = "legacy-environment-bootstrap-token-0123456789"
    monkeypatch.setenv(
        "JARVIS_BOOTSTRAP_TOKEN",
        legacy_token,
    )

    with TestClient(
        create_app(
            bootstrap_token=BOOTSTRAP,
        )
    ) as client:
        assert (
            os.environ["JARVIS_BOOTSTRAP_TOKEN"]
            == legacy_token
        )

        explicit = client.get(
            "/auth/bootstrap",
            params={"token": BOOTSTRAP},
            follow_redirects=False,
        )
        assert explicit.status_code == 303

        legacy_attempt = client.get(
            "/auth/bootstrap",
            params={"token": legacy_token},
            follow_redirects=False,
        )
        assert legacy_attempt.status_code == 401

        assert (
            os.environ["JARVIS_BOOTSTRAP_TOKEN"]
            == legacy_token
        )


def test_legacy_environment_bootstrap_is_consumed_when_explicit_missing(
    monkeypatch,
) -> None:
    legacy_token = "legacy-environment-bootstrap-token-abcdef0123456789"
    monkeypatch.setenv(
        "JARVIS_BOOTSTRAP_TOKEN",
        legacy_token,
    )

    with TestClient(create_app()) as client:
        assert (
            "JARVIS_BOOTSTRAP_TOKEN"
            not in os.environ
        )

        response = client.get(
            "/auth/bootstrap",
            params={"token": legacy_token},
            follow_redirects=False,
        )
        assert response.status_code == 303


def _closure_contains_plaintext_token(
    function,
    token: str,
) -> bool:
    target = getattr(
        function,
        "__wrapped__",
        function,
    )

    for cell in target.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue

        if value == token:
            return True

        if (
            isinstance(value, list)
            and token in value
        ):
            return True

    return False


def test_lifespan_releases_plaintext_bootstrap_after_auth_initialization() -> None:
    lifespan = _make_lifespan(
        BOOTSTRAP,
        None,
    )

    assert _closure_contains_plaintext_token(
        lifespan,
        BOOTSTRAP,
    )

    app = FastAPI(
        lifespan=lifespan,
    )

    with TestClient(app):
        assert not _closure_contains_plaintext_token(
            lifespan,
            BOOTSTRAP,
        )
