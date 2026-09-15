from __future__ import annotations

import time

import pytest

import jarvis_web.transport_runner as transport_module
from jarvis_web.transport_runner import (
    WebTransportRunner,
    WebTransportStartupError,
    WebTransportState,
)


class _Application:
    pass


class _FakeConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _HealthyServer:
    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False

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


class _PostReadyFailureServer:
    def __init__(self, config):
        self.config = config
        self.started = False
        self.should_exit = False
        self.force_exit = False

    def run(self):
        self.started = True
        time.sleep(0.05)
        raise RuntimeError("simulated post-ready failure")


def _runner() -> WebTransportRunner:
    return WebTransportRunner(
        startup_timeout=1.0,
        shutdown_timeout=1.0,
        poll_interval=0.001,
    )


def test_initial_and_normal_lifecycle_status(monkeypatch) -> None:
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

    runner = _runner()

    assert runner.status.state is WebTransportState.STOPPED
    assert runner.status.reason is None
    assert runner.started is False

    runner.start(_Application())

    assert runner.status.state is WebTransportState.READY
    assert runner.status.reason is None
    assert runner.started is True

    runner.stop()

    assert runner.status.state is WebTransportState.STOPPED
    assert runner.status.reason is None
    assert runner.started is False


def test_startup_failure_is_terminal_and_preserved(monkeypatch) -> None:
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

    runner = _runner()

    with pytest.raises(WebTransportStartupError):
        runner.start(_Application())

    assert runner.status.state is WebTransportState.FAILED
    assert runner.status.reason is not None
    assert "Uvicorn exit code 3" in runner.status.reason
    assert "127.0.0.1:8766" in runner.status.reason
    assert runner.started is False

    # CLI cleanup must not erase the failure before another observer
    # has had a chance to inspect it.
    runner.stop()

    assert runner.status.state is WebTransportState.FAILED
    assert runner.status.reason is not None


def test_post_ready_thread_failure_changes_ready_to_failed(
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
        _PostReadyFailureServer,
    )

    runner = _runner()
    runner.start(_Application())

    assert runner.status.state is WebTransportState.READY

    deadline = time.monotonic() + 1.0

    while (
        runner.status.state is not WebTransportState.FAILED
        and time.monotonic() < deadline
    ):
        time.sleep(0.005)

    assert runner.status.state is WebTransportState.FAILED
    assert runner.status.reason is not None
    assert "post-ready failure" in runner.status.reason
    assert runner.started is False


def test_status_snapshot_is_immutable() -> None:
    runner = _runner()
    snapshot = runner.status

    with pytest.raises(Exception):
        snapshot.reason = "changed"
