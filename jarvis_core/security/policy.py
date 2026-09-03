from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from datetime import datetime, timedelta
from secrets import token_hex
from typing import Any, Callable


class RiskLevel(IntEnum):
    READ_ONLY = 0
    LOW = 1
    CONFIRM = 3
    CRITICAL = 5


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    risk: RiskLevel
    description: str


@dataclass(slots=True)
class PendingAction:
    token: str
    tool_name: str
    arguments: dict[str, Any]
    description: str
    created_at: str


class SecurityPolicy:
    def __init__(self, confirmation_ttl_seconds: int = 600) -> None:
        self._policies: dict[str, ToolPolicy] = {}
        self._pending: dict[str, PendingAction] = {}
        self.confirmation_ttl_seconds = max(30, int(confirmation_ttl_seconds))

    def _purge_expired(self) -> None:
        now = datetime.now().astimezone()
        expired = []
        for token, pending in self._pending.items():
            try:
                created = datetime.fromisoformat(pending.created_at)
                if created.tzinfo is None:
                    created = created.astimezone()
                if now - created > timedelta(seconds=self.confirmation_ttl_seconds):
                    expired.append(token)
            except Exception:
                expired.append(token)
        for token in expired:
            self._pending.pop(token, None)

    def register(self, tool_name: str, risk: RiskLevel, description: str) -> None:
        self._policies[tool_name] = ToolPolicy(risk=risk, description=description)

    def policy_for(self, tool_name: str) -> ToolPolicy:
        return self._policies.get(
            tool_name,
            ToolPolicy(RiskLevel.CRITICAL, "Unknown tool: denied by default."),
        )

    def request_confirmation(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        description: str,
    ) -> PendingAction:
        token = token_hex(3).upper()
        pending = PendingAction(
            token=token,
            tool_name=tool_name,
            arguments=dict(arguments),
            description=description,
            created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._pending[token] = pending
        return pending

    def pending(self) -> list[PendingAction]:
        self._purge_expired()
        return list(self._pending.values())

    def pop_pending(self, token: str) -> PendingAction | None:
        self._purge_expired()
        return self._pending.pop(token.upper(), None)

    def clear_pending(self, token: str) -> bool:
        return self._pending.pop(token.upper(), None) is not None
