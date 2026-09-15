from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from queue import Empty, Queue
from threading import Lock, Thread
import time
from typing import Any

from uvicorn import Config, Server

from jarvis_web.backend.adapters.jarvis_core import RealJarvisCoreAdapter
from jarvis_web.backend.app import create_app
from jarvis_web.backend.config import settings


class WebTransportStartupError(RuntimeError):
    """Raised when the embedded Web transport cannot become ready."""


class WebTransportShutdownError(RuntimeError):
    """Raised when the embedded Web transport cannot terminate cleanly."""


class WebTransportState(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    READY = "READY"
    FAILED = "FAILED"
    STOPPING = "STOPPING"


@dataclass(frozen=True, slots=True)
class WebTransportStatus:
    state: WebTransportState
    reason: str | None = None


class WebTransportRunner:
    """Own one embedded Uvicorn Web transport for an existing JARVIS application."""

    def __init__(
        self,
        *,
        startup_timeout: float = 10.0,
        shutdown_timeout: float = 10.0,
        poll_interval: float = 0.01,
    ) -> None:
        if startup_timeout <= 0:
            raise ValueError("startup_timeout must be greater than zero")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be greater than zero")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero")

        self._startup_timeout = float(startup_timeout)
        self._shutdown_timeout = float(shutdown_timeout)
        self._poll_interval = float(poll_interval)

        self._lock = Lock()
        self._server: Server | None = None
        self._thread: Thread | None = None
        self._adapter: RealJarvisCoreAdapter | None = None
        self._asgi_app: Any | None = None
        self._thread_errors: Queue[BaseException] | None = None
        self._stop_requested = False
        self._status = WebTransportStatus(
            WebTransportState.STOPPED,
        )

    @property
    def status(self) -> WebTransportStatus:
        with self._lock:
            return self._status

    @property
    def started(self) -> bool:
        return self.status.state is WebTransportState.READY

    def start(
        self,
        application: Any,
        *,
        bootstrap_token: str | None = None,
    ) -> None:
        if application is None:
            raise ValueError(
                "WebTransportRunner requires an existing JarvisApplication"
            )

        with self._lock:
            if self._thread is not None:
                raise RuntimeError("WebTransportRunner is already started")

            self._stop_requested = False
            self._status = WebTransportStatus(
                WebTransportState.STARTING,
            )

            adapter = RealJarvisCoreAdapter(application)
            asgi_app = create_app(
                dev_mode=False,
                bootstrap_token=bootstrap_token,
                core_adapter=adapter,
            )

            config = Config(
                app=asgi_app,
                host=settings.api_host,
                port=settings.api_port,
                reload=False,
                access_log=False,
                log_config=None,
                proxy_headers=False,
                server_header=False,
            )

            server = Server(config)
            errors: Queue[BaseException] = Queue(maxsize=1)

            thread = Thread(
                target=self._run_server,
                args=(server, errors),
                name="jarvis-web-transport",
                daemon=False,
            )

            self._server = server
            self._thread = thread
            self._adapter = adapter
            self._asgi_app = asgi_app
            self._thread_errors = errors

            thread.start()

        deadline = time.monotonic() + self._startup_timeout

        while True:
            failure = self._take_thread_error(errors)

            if failure is not None:
                reason = self._startup_failure_reason(failure)
                self._set_status(
                    WebTransportState.FAILED,
                    reason,
                )
                self._clear_if_owned(server, thread)

                raise WebTransportStartupError(
                    reason
                ) from failure

            if not thread.is_alive():
                reason = (
                    "Embedded Web transport exited before becoming ready"
                )
                self._set_status(
                    WebTransportState.FAILED,
                    reason,
                )
                self._clear_if_owned(server, thread)

                raise WebTransportStartupError(reason)

            if server.started:
                self._set_status(
                    WebTransportState.READY,
                )
                return

            if time.monotonic() >= deadline:
                reason = (
                    "Embedded Web transport did not become ready "
                    f"within {self._startup_timeout:.1f} seconds "
                    f"on {settings.api_host}:{settings.api_port}"
                )

                self._mark_stop_requested()
                stopped = self._request_stop(
                    server,
                    thread,
                )

                self._set_status(
                    WebTransportState.FAILED,
                    reason,
                )

                if stopped:
                    self._clear_if_owned(
                        server,
                        thread,
                    )

                raise WebTransportStartupError(reason)

            time.sleep(self._poll_interval)

    def stop(self) -> None:
        with self._lock:
            server = self._server
            thread = self._thread
            current_state = self._status.state

        if server is None or thread is None:
            # Preserve FAILED so a subsequent observer can still inspect
            # the startup/runtime failure that caused shutdown.
            if current_state is not WebTransportState.FAILED:
                self._set_status(
                    WebTransportState.STOPPED,
                )
            return

        if not thread.is_alive():
            self._clear_if_owned(server, thread)

            if self.status.state is not WebTransportState.FAILED:
                self._set_status(
                    WebTransportState.STOPPED,
                )
            return

        self._set_status(
            WebTransportState.STOPPING,
        )
        self._mark_stop_requested()

        stopped = self._request_stop(
            server,
            thread,
        )

        if not stopped:
            reason = (
                "Embedded Web transport did not stop after "
                f"{self._shutdown_timeout:.1f} seconds"
            )
            self._set_status(
                WebTransportState.FAILED,
                reason,
            )

            raise WebTransportShutdownError(reason)

        self._clear_if_owned(server, thread)
        self._set_status(
            WebTransportState.STOPPED,
        )

    def _request_stop(
        self,
        server: Server,
        thread: Thread,
    ) -> bool:
        server.should_exit = True
        thread.join(self._shutdown_timeout)

        if not thread.is_alive():
            return True

        server.force_exit = True
        server.should_exit = True
        thread.join(self._shutdown_timeout)

        return not thread.is_alive()

    def _run_server(
        self,
        server: Server,
        errors: Queue[BaseException],
    ) -> None:
        try:
            server.run()
        except BaseException as exc:
            try:
                errors.put_nowait(exc)
            except Exception:
                pass

            if server.started:
                self._set_status(
                    WebTransportState.FAILED,
                    self._runtime_failure_reason(exc),
                )
        else:
            if (
                server.started
                and not self._stop_was_requested()
            ):
                self._set_status(
                    WebTransportState.FAILED,
                    "Embedded Web transport stopped unexpectedly",
                )

    @staticmethod
    def _take_thread_error(
        errors: Queue[BaseException],
    ) -> BaseException | None:
        try:
            return errors.get_nowait()
        except Empty:
            return None

    def _set_status(
        self,
        state: WebTransportState,
        reason: str | None = None,
    ) -> None:
        with self._lock:
            self._status = WebTransportStatus(
                state=state,
                reason=reason,
            )

    def _mark_stop_requested(self) -> None:
        with self._lock:
            self._stop_requested = True

    def _stop_was_requested(self) -> bool:
        with self._lock:
            return self._stop_requested

    @staticmethod
    def _clean_exception_text(
        exc: BaseException,
    ) -> str:
        text = str(exc).replace("\r", " ").replace("\n", " ").strip()

        if not text:
            text = exc.__class__.__name__
        else:
            text = f"{exc.__class__.__name__}: {text}"

        return text[:500]

    def _startup_failure_reason(
        self,
        exc: BaseException,
    ) -> str:
        if isinstance(exc, SystemExit):
            code = getattr(exc, "code", None)
            return (
                "Embedded Web transport failed during startup "
                f"(Uvicorn exit code {code}); verify that "
                f"{settings.api_host}:{settings.api_port} is available"
            )

        return (
            "Embedded Web transport failed during startup: "
            + self._clean_exception_text(exc)
        )

    def _runtime_failure_reason(
        self,
        exc: BaseException,
    ) -> str:
        return (
            "Embedded Web transport failed after becoming ready: "
            + self._clean_exception_text(exc)
        )

    def _clear_if_owned(
        self,
        server: Server,
        thread: Thread,
    ) -> None:
        with self._lock:
            if (
                self._server is not server
                or self._thread is not thread
            ):
                return

            self._server = None
            self._thread = None
            self._adapter = None
            self._asgi_app = None
            self._thread_errors = None
            self._stop_requested = False
