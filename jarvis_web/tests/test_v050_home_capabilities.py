from jarvis_web.backend.auth import LocalAuthManager
from jarvis_web.backend.home_capability_broker import HomeCapabilityBroker, HomeRiskTier
from jarvis_web.backend.web_chat_policy import evaluate_web_chat_message
from jarvis_web.tests.auth_helpers import make_authenticated_client


def _local_session():
    auth = LocalAuthManager(bootstrap_token="bootstrap")
    issued = auth.consume_bootstrap("bootstrap")
    assert issued is not None
    return issued[1]


def test_local_web_has_normal_home_scopes_but_no_raw_core_scope() -> None:
    session = _local_session()
    assert session.has_scope("home.read")
    assert session.has_scope("home.control")
    assert not session.has_scope("home.critical")
    assert not session.has_scope("core.control")
    assert not session.has_scope("shell")


def test_home_read_and_normal_control_are_authorized() -> None:
    broker = HomeCapabilityBroker()
    session = _local_session()
    assert broker.authorize(capability="home.temperature", session=session).allowed
    assert broker.authorize(capability="light.turn_off", session=session).allowed
    assert broker.authorize(capability="appliance.start_cycle", session=session).allowed


def test_critical_home_actions_require_future_step_up() -> None:
    broker = HomeCapabilityBroker()
    session = _local_session()
    decision = broker.authorize(capability="lock.unlock", session=session)
    assert decision.allowed is False
    assert decision.tier is HomeRiskTier.CRITICAL
    assert decision.requires_step_up is True


def test_raw_or_unknown_home_actions_are_forbidden() -> None:
    broker = HomeCapabilityBroker()
    session = _local_session()
    for capability in ["home.raw_service_call", "home.shell_command", "whatever.exec"]:
        decision = broker.authorize(capability=capability, session=session)
        assert decision.allowed is False
        assert decision.tier is HomeRiskTier.FORBIDDEN


def test_home_natural_language_intents_are_allowed_through_chat_policy() -> None:
    for message in [
        "Qual é a temperatura do quarto?",
        "Está alguma janela aberta?",
        "Desliga as luzes da sala.",
        "Liga o desumidificador.",
        "Põe a máquina de lavar a funcionar.",
    ]:
        assert evaluate_web_chat_message(message).allowed is True


def test_terminal_command_syntax_remains_blocked_even_for_home() -> None:
    decision = evaluate_web_chat_message("/home light.turn_off sala")
    assert decision.allowed is False
    assert decision.code == "core_command_blocked"


def test_security_home_policy_manifest_is_policy_only() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/security/home-policy")
        assert response.status_code == 200
        payload = response.json()
        assert payload["execution_available"] is False
        assert payload["integration_state"] == "policy_only"
        assert payload["session_can_read"] is True
        assert payload["session_can_control_normal"] is True
        assert payload["session_can_control_critical"] is False
        assert "light.turn_off" in payload["normal_control"]
        assert "lock.unlock" in payload["critical_step_up"]
    finally:
        client.__exit__(None, None, None)


def test_security_me_separates_home_from_raw_core_control() -> None:
    app, client = make_authenticated_client()
    try:
        response = client.get("/api/security/me")
        assert response.status_code == 200
        payload = response.json()
        assert payload["core_control_authorized"] is False
        assert payload["home_read_authorized"] is True
        assert payload["home_control_authorized"] is True
        assert payload["home_critical_authorized"] is False
    finally:
        client.__exit__(None, None, None)


def test_no_raw_home_execution_api_exists_yet() -> None:
    app, client = make_authenticated_client()
    try:
        for path in [
            "/api/home/execute",
            "/api/home/service-call",
            "/api/home/admin",
            "/api/home/shell",
        ]:
            response = client.post(path, json={"anything": "anything"})
            assert response.status_code == 404
    finally:
        client.__exit__(None, None, None)
