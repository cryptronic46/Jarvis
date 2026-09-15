import asyncio

from fastapi.testclient import TestClient
import pytest

from jarvis_web.backend.app import create_app
from jarvis_web.backend.security import (
    RequestBodyLimitMiddleware,
    SuspiciousPathGuardMiddleware,
)
from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_production_rejects_vite_origin() -> None:
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/sessions",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Content-Type": "text/plain",
            },
            content="{}",
        )
        assert response.status_code == 403


def test_dev_mode_keeps_vite_origin_available() -> None:
    with TestClient(create_app(dev_mode=True)) as client:
        # Without authentication the request still fails, but it must get past
        # the production Origin guard rather than receiving 403 for the Vite origin.
        response = client.post(
            "/api/sessions",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Content-Type": "application/json",
            },
            json={},
        )
        assert response.status_code == 401


def test_public_health_exposes_only_liveness() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_oversized_api_body_is_rejected_before_auth() -> None:
    with TestClient(create_app()) as client:
        payload = "A" * (RequestBodyLimitMiddleware.MAX_API_BODY_BYTES + 1)
        response = client.post(
            "/api/chat",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413


def test_invalid_negative_content_length_is_rejected() -> None:
    middleware = RequestBodyLimitMiddleware

    async def downstream(scope, receive, send):
        raise AssertionError("downstream must not be reached")

    app = middleware(downstream)

    messages = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": [(b"content-length", b"-1")],
    }

    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == 400


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/%2e%2e/Windows/win.ini",
        "/%2E%2E/%2E%2E/Windows/win.ini",
        "/%252e%252e/%252e%252e/Windows/win.ini",
        "/.%2e/.%2e/Windows/win.ini",
        r"/..\..\Windows\win.ini",
        "/file.txt%3Asecret",
    ],
)
def test_path_classifier_blocks_encoded_traversal_and_ntfs_ads(path: str) -> None:
    assert SuspiciousPathGuardMiddleware._is_suspicious(path) is True


def test_raw_asgi_encoded_traversal_is_rejected() -> None:
    messages = []

    async def downstream(scope, receive, send):
        raise AssertionError("downstream must not be reached")

    middleware = SuspiciousPathGuardMiddleware(downstream)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/%2e%2e/%2e%2e/Windows/win.ini",
        "raw_path": b"/%2e%2e/%2e%2e/Windows/win.ini",
        "headers": [],
    }

    asyncio.run(middleware(scope, receive, send))
    assert messages[0]["status"] == 400


def test_dotfile_paths_are_reserved_from_spa() -> None:
    with TestClient(create_app()) as client:
        for path in ("/.gitignore", "/.secret", "/.well-known/test"):
            response = client.get(path)
            assert response.status_code == 404


def test_security_headers_are_not_duplicated() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
        assert response.headers.get_list("cache-control") == ["no-store"]
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert response.headers["x-permitted-cross-domain-policies"] == "none"


def test_websocket_without_origin_is_rejected_even_when_authenticated() -> None:
    app, client = make_authenticated_client()
    try:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/events"):
                pass
    finally:
        client.__exit__(None, None, None)


def test_production_websocket_rejects_vite_origin_when_authenticated() -> None:
    app, client = make_authenticated_client()
    try:
        with pytest.raises(Exception):
            with client.websocket_connect(
                "/api/events",
                headers={"Origin": "http://127.0.0.1:5173"},
            ):
                pass
    finally:
        client.__exit__(None, None, None)
