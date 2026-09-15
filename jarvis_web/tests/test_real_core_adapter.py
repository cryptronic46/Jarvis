from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis_web.backend.adapters import RealJarvisCoreAdapter
from jarvis_web.backend.app import create_app


@dataclass
class FakeProcessRequestResult:
    answer: str
    route: str = "TEST"
    elapsed_ms: int = 1
    hybrid: object | None = None


class FakeJarvisApplication:
    def __init__(self):
        self.calls = []

    def process_request(
        self,
        user_text: str,
        *,
        source: str = "terminal",
    ):
        self.calls.append(
            {
                "user_text": user_text,
                "source": source,
            }
        )

        return FakeProcessRequestResult(
            answer="Resposta da JARVIS real simulada",
        )


def test_real_adapter_uses_injected_application() -> None:
    application = FakeJarvisApplication()

    adapter = RealJarvisCoreAdapter(
        application,
    )

    answer = asyncio.run(
        adapter.chat(
            "Ol? Jarvis",
            session_id="web-session",
            history=[
                {
                    "role": "user",
                    "content": "contexto UI",
                }
            ],
        )
    )

    assert answer == (
        "Resposta da JARVIS real simulada"
    )

    assert application.calls == [
        {
            "user_text": "Ol? Jarvis",
            "source": "web",
        }
    ]

    assert adapter._application is application


def test_real_adapter_status_is_safe() -> None:
    application = FakeJarvisApplication()

    adapter = RealJarvisCoreAdapter(
        application,
    )

    assert asyncio.run(
        adapter.health()
    ) == "ready"

    assert asyncio.run(
        adapter.status()
    ) == {
        "state": "ready",
        "adapter": "jarvis-core",
        "local_only": True,
    }


def test_real_adapter_does_not_build_core() -> None:
    source = (
        Path(__file__)
        .resolve()
        .parents[1]
        / "backend"
        / "adapters"
        / "jarvis_core.py"
    ).read_text(
        encoding="utf-8",
    )

    assert "build_application" not in source
    assert "JarvisRuntime(" not in source
    assert "HybridBrain(" not in source
    assert "mode:" not in source

def test_real_adapter_wires_same_application_into_fastapi() -> None:
    application = FakeJarvisApplication()
    adapter = RealJarvisCoreAdapter(application)

    app = create_app(
        core_adapter=adapter,
    )

    with TestClient(app):
        assert app.state.core_adapter is adapter
        assert app.state.core_adapter._application is application
