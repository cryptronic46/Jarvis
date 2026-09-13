from __future__ import annotations

from dataclasses import dataclass, field
from threading import Thread
from time import sleep

from jarvis_core.runtime import (
    JarvisRuntime,
    ProcessRequestResult,
)


@dataclass(slots=True)
class JarvisApplication:
    """
    Transport-neutral application boundary for the live JARVIS Core.

    The application owns shared Core-facing operations. Terminal and Web
    transports must call this boundary instead of creating parallel runtime
    or authorization paths.
    """

    runtime: JarvisRuntime
    autonomy: object
    kali_bridge: object
    cyber_knowledge: object
    settings: object
    events: object
    brain: object
    telemetry: object
    performance: object
    activity_trace: object
    request_lock: object

    _runtime_services_started: bool = field(
        default=False,
        init=False,
        repr=False,
    )

    def _on_sustained_pressure(
        self,
        pressure: dict,
    ) -> None:
        if (
            self.settings
            .performance_release_llm_on_pressure
        ):
            result = self.brain.release_model(
                reason="sustained_resource_pressure"
            )

            self.events.emit(
                "PERFORMANCE_LLM_RELEASE_RESULT",
                pressure=pressure,
                result=result,
            )

    def _warm_services(
        self,
    ) -> None:
        self.events.emit(
            "WARMUP_STARTED"
        )

        sleep(
            max(
                0.0,
                float(
                    self.settings
                    .performance_warmup_delay_seconds
                ),
            )
        )

        if self.performance.should_warm_llm():
            self.brain.warmup()

        else:
            self.events.emit(
                "LLM_WARMUP_DEFERRED",
                pressure=self.performance.pressure(),
            )

        self.events.emit(
            "WARMUP_FINISHED"
        )

    def start_runtime_services(
        self,
    ) -> None:
        if self._runtime_services_started:
            return

        self.activity_trace.start()

        try:
            self.telemetry.start()

            try:
                self.performance.start(
                    on_sustained_pressure=(
                        self._on_sustained_pressure
                    )
                )

            except Exception:
                self.telemetry.stop()
                raise

        except Exception:
            self.activity_trace.stop()
            raise

        self._runtime_services_started = True

        if self.settings.background_warmup:
            Thread(
                target=self._warm_services,
                name="jarvis-warmup",
                daemon=True,
            ).start()

    def stop_activity_trace(
        self,
    ) -> None:
        self.activity_trace.stop()

    def release_models_on_shutdown(
        self,
    ) -> None:
        if bool(
            getattr(
                self.settings,
                "ollama_release_on_shutdown",
                True,
            )
        ):
            self.brain.release_all_models(
                reason="jarvis_shutdown",
                include_configured=True,
            )

    def stop_runtime_services(
        self,
    ) -> None:
        if not self._runtime_services_started:
            return

        try:
            self.performance.stop()

        finally:
            self.telemetry.stop()
            self._runtime_services_started = False

    def semantic_context_inputs(
        self,
    ):
        return (
            self.runtime
            .semantic_context_inputs()
        )

    def process_request(
        self,
        user_text: str,
        *,
        source: str = "terminal",
    ) -> ProcessRequestResult:
        with self.request_lock:
            return self.runtime.process_request(
                user_text,
                source=source,
            )

    def open_owner_kali_session(
        self,
        *,
        target: str = "",
        profiles,
        ports=None,
        scope: str,
        source_text: str,
    ) -> dict:
        scoped = (
            self.kali_bridge
            .build_security_session_scope(
                target=target,
                profiles=list(profiles),
                ports=ports,
                scope=scope,
            )
        )

        if not scoped.get("ok"):
            return scoped

        payload = dict(
            scoped.get("payload")
            or {}
        )

        try:
            authorization = (
                self.autonomy
                .record_direct_authorization(
                    capability=(
                        "kali_security_session"
                    ),
                    payload=payload,
                    description=(
                        "abrir uma sess?o Kali limitada "
                        f"ao scope {payload.get('scope')}, "
                        f"alvo {payload.get('target')} "
                        "e perfis "
                        f"{payload.get('profiles')}"
                    ),
                    source_text=source_text,
                )
            )

        except Exception as exc:
            return {
                "ok": False,
                "error":
                    "KALI_DIRECT_AUTHORITY_ERROR",
                "reason":
                    f"{type(exc).__name__}: {exc}",
            }

        if (
            not isinstance(
                authorization,
                dict,
            )
            or not authorization.get(
                "ok"
            )
            or not authorization.get(
                "authorized",
                False,
            )
        ):
            return {
                "ok": False,
                "error":
                    "KALI_DIRECT_AUTHORIZATION_FAILED",
                "reason_code": str(
                    authorization.get(
                        "error"
                    )
                    if isinstance(
                        authorization,
                        dict,
                    )
                    else ""
                )
                or
                "KALI_DIRECT_AUTHORIZATION_FAILED",
            }

        execution_token = str(
            authorization.get(
                "execution_token"
            )
            or ""
        )

        if not execution_token:
            return {
                "ok": False,
                "error":
                    "KALI_EXECUTION_CREDENTIAL_MISSING",
            }

        return (
            self.kali_bridge
            .open_security_session(
                target=target,
                profiles=list(profiles),
                ports=ports,
                scope=scope,
                execution_token=(
                    execution_token
                ),
            )
        )

    def owner_authorized_cyber_sync(
        self,
        *,
        full: bool = False,
        source_id: str = "",
        source_text: str,
    ) -> dict:
        source_id = str(
            source_id
            or ""
        ).strip()

        payload = {
            "operation":
                "cyber_knowledge_sync",
            "full": bool(full),
            "source_id": source_id,
        }

        try:
            authorization = (
                self.autonomy
                .record_direct_authorization(
                    capability=(
                        "external_learning"
                    ),
                    payload=payload,
                    description=(
                        "sincronizar fontes oficiais "
                        "da Cyber Knowledge Vault"
                    ),
                    source_text=source_text,
                )
            )

        except Exception as exc:
            return {
                "ok": False,
                "error":
                    "OWNER_AUTHORITY_ERROR",
                "reason_code":
                    "OWNER_AUTHORITY_ERROR",
                "message": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            }

        if (
            not isinstance(
                authorization,
                dict,
            )
            or not authorization.get(
                "ok"
            )
            or not authorization.get(
                "authorized",
                False,
            )
        ):
            return {
                "ok": False,
                "error":
                    "OWNER_AUTHORIZATION_FAILED",
                "reason_code": str(
                    authorization.get(
                        "error"
                    )
                    if isinstance(
                        authorization,
                        dict,
                    )
                    else ""
                )
                or
                "OWNER_AUTHORIZATION_FAILED",
            }

        execution_token = str(
            authorization.get(
                "execution_token"
            )
            or ""
        )

        if not execution_token:
            return {
                "ok": False,
                "error":
                    "OWNER_EXECUTION_CREDENTIAL_MISSING",
                "reason_code":
                    "OWNER_EXECUTION_CREDENTIAL_MISSING",
            }

        return self.cyber_knowledge.sync(
            full=bool(full),
            source_id=source_id,
            execution_token=(
                execution_token
            ),
        )
