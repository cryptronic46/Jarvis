from __future__ import annotations

import time

import pytest

import jarvis_web.transport_runner as transport_module
from jarvis_web.transport_runner import (
    WebTransportRunner,
    WebTransportStartupError,
)


class _Application:
    pass


class _FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _HealthyServer:
    instances = []

    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False
        self.__class__.instances.append(self)

    def run(self):
        self.started = True

        while not self.should_exit:
            time.sleep(0.001)


class _StartupFailureServer:
    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False

    def run(self):
        raise SystemExit(3)


class _NeverReadyServer:
    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False

    def run(self):
        while not self.should_exit and not self.force_exit:
            time.sleep(0.001)


def test_runner_uses_same_application_and_secure_uvicorn_config(
    monkeypatch,
) -> None:
    _HealthyServer.instances.clear()

    monkeypatch.setattr(
        transport_module,
        "Config",
        _FakeConfig,
    )
    monkeypatch.setattr(
        transport_module,
        "Server",
        _HealthyServer,
    )

    application = _Application()
    runner = WebTransportRunner(
        startup_timeout=1.0,
        shutdown_timeout=1.0,
        poll_interval=0.001,
    )

    runner.start(application)

    try:
        assert runner.started is True
        assert runner._adapter is not None
        assert runner._adapter._application is application

        server = _HealthyServer.instances[-1]
        config = server.config.kwargs

        assert config["app"] is runner._asgi_app
        assert not isinstance(config["app"], str)

        assert config["host"] == "127.0.0.1"
        assert config["port"] == 8766
        assert config["reload"] is False
        assert config["access_log"] is False
        assert config["log_config"] is None
        assert config["proxy_headers"] is False
        assert config["server_header"] is False
    finally:
        runner.stop()

    assert runner.started is False


def test_runner_propagates_system_exit_from_uvicorn_startup(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        transport_module,
        "Config",
        _FakeConfig,
    )
    monkeypatch.setattr(
        transport_module,
        "Server",
        _StartupFailureServer,
    )

    runner = WebTransportRunner(
        startup_timeout=1.0,
        shutdown_timeout=1.0,
        poll_interval=0.001,
    )

    with pytest.raises(WebTransportStartupError) as exc_info:
        runner.start(_Application())

    assert isinstance(exc_info.value.__cause__, SystemExit)
    assert runner.started is False


def test_runner_times_out_and_stops_server_that_never_becomes_ready(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        transport_module,
        "Config",
        _FakeConfig,
    )
    monkeypatch.setattr(
        transport_module,
        "Server",
        _NeverReadyServer,
    )

    runner = WebTransportRunner(
        startup_timeout=0.05,
        shutdown_timeout=0.5,
        poll_interval=0.001,
    )

    with pytest.raises(
        WebTransportStartupError,
        match="did not become ready",
    ):
        runner.start(_Application())

    assert runner.started is False


def test_stop_is_idempotent_before_start() -> None:
    runner = WebTransportRunner()

    runner.stop()

    assert runner.started is False


def test_runner_passes_bootstrap_token_to_app_factory(
    monkeypatch,
) -> None:
    captured = {}
    asgi_app = object()

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return asgi_app

    monkeypatch.setattr(
        transport_module,
        "create_app",
        fake_create_app,
    )
    monkeypatch.setattr(
        transport_module,
        "Config",
        _FakeConfig,
    )
    monkeypatch.setattr(
        transport_module,
        "Server",
        _HealthyServer,
    )

    application = _Application()
    bootstrap_token = (
        "runner-bootstrap-token-"
        "0123456789abcdef0123456789abcdef"
    )

    runner = WebTransportRunner(
        startup_timeout=1.0,
        shutdown_timeout=1.0,
        poll_interval=0.001,
    )

    runner.start(
        application,
        bootstrap_token=bootstrap_token,
    )

    try:
        assert captured["bootstrap_token"] == bootstrap_token
        assert captured["dev_mode"] is False
        assert (
            captured["core_adapter"]._application
            is application
        )

        # The Runner transports but does not own/persist credentials.
        assert not hasattr(
            runner,
            "_bootstrap_token",
        )
    finally:
        runner.stop()
