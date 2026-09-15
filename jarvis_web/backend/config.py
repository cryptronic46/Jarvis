from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    # SECURITY: hard-pinned to loopback until application authentication exists.
    api_host: str = "127.0.0.1"
    api_port: int = int(os.getenv("JARVIS_API_PORT", "8766"))

    runtime_origins: tuple[str, ...] = (
        "http://127.0.0.1:8766",
        "http://localhost:8766",
    )

    dev_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return self.runtime_origins + self.dev_origins

    trusted_hosts: tuple[str, ...] = (
        "127.0.0.1",
        "localhost",
        "[::1]",
        # Required only by Starlette/FastAPI TestClient.
        "testserver",
    )


settings = Settings()
