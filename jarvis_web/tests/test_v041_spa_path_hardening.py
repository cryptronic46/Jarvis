from fastapi.testclient import TestClient
import pytest

from jarvis_web.backend.app import create_app
from jarvis_web.backend.security import SuspiciousPathGuardMiddleware


@pytest.mark.parametrize(
    "path",
    [
        "/.env",
        "/.env.local",
        "/.git/config",
        "/.venv/pyvenv.cfg",
        "/backend/app.py",
        "/data/sessions.json",
        "/logs/security-audit.jsonl",
        "/run/jarvis-web.pid",
        "/tests/test_v031_security.py",
        "/web/src/App.tsx",
        "/web/node_modules/example/index.js",
        "/web/dist/index.html",
    ],
)
def test_sensitive_source_runtime_paths_are_reserved(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path)
        assert response.status_code == 404
        assert "text/html" not in response.headers.get("content-type", "")


@pytest.mark.parametrize(
    "value",
    [
        "/../../Windows/win.ini",
        "/..%2f..%2fWindows%2fwin.ini",
        "/%2e%2e/%2e%2e/Windows/win.ini",
        "/%252e%252e%252fWindows%252fwin.ini",
        r"/web\..\..\backend\app.py",
        "/web/%2e%2e/%2e%2e/backend/app.py",
    ],
)
def test_traversal_classifier_rejects_encoded_and_plain_variants(value: str) -> None:
    assert SuspiciousPathGuardMiddleware._is_suspicious(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/assets/index-ABC123.js",
        "/conversation/hello-world",
        "/search?q=hello%20world",
        "/api/health",
    ],
)
def test_path_guard_does_not_block_normal_paths(value: str) -> None:
    assert SuspiciousPathGuardMiddleware._is_suspicious(value) is False


def test_plain_traversal_request_is_rejected_before_spa() -> None:
    with TestClient(create_app()) as client:
        # TestClient normalizes literal ../, so use an encoded request to verify
        # the middleware sees the malicious form.
        response = client.get("/..%2f..%2fWindows%2fwin.ini")
        assert response.status_code == 400
        assert "text/html" not in response.headers.get("content-type", "")
