from jarvis_web.backend.permission_broker import PermissionBroker
from jarvis_web.tests.auth_helpers import make_authenticated_client


def test_security_me_has_no_core_control_authority() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/security/me")
        assert response.status_code == 200
        payload = response.json()

        assert payload["trust_level"] == "local_desktop"
        assert payload["core_control_authorized"] is False
        assert payload["remote_access_enabled"] is False
        assert "chat.write" in payload["scopes"]
        assert "security.manage_local" in payload["scopes"]
        assert all("core" not in scope for scope in payload["scopes"])
    finally:
        client.__exit__(None, None, None)


def test_remote_access_is_hard_disabled() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/security/remote-status")
        assert response.status_code == 200
        assert response.json()["enabled"] is False
    finally:
        client.__exit__(None, None, None)


def test_local_desktop_can_list_sessions_without_tokens() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/security/sessions")
        assert response.status_code == 200
        sessions = response.json()["sessions"]
        assert len(sessions) >= 1
        session = sessions[0]

        assert "session_id" in session
        assert "device_id" in session
        assert "device_label" in session
        assert "scopes" in session
        assert "token" not in session
        assert "cookie" not in session
    finally:
        client.__exit__(None, None, None)


def test_revoke_all_invalidates_current_session() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.post("/api/security/revoke-all")
        assert response.status_code == 200
        assert response.json()["revoked"] >= 1

        denied = client.post("/api/sessions")
        assert denied.status_code == 401
    finally:
        client.__exit__(None, None, None)


def test_permission_broker_denies_every_core_action_by_default() -> None:
    broker = PermissionBroker()
    decision = broker.authorize_core_action(
        action="home.unlock_front_door",
        session=None,
    )

    assert decision.allowed is False
    assert decision.requires_step_up is True
