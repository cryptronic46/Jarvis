from __future__ import annotations

from dataclasses import dataclass

from jarvis_web.backend.auth import SessionRecord


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    requires_step_up: bool = False


class PermissionBroker:
    """Deny-by-default future control-plane authorization boundary.

    Raw/privileged JARVIS Core actions remain unavailable to Web Chat.
    Home Assistant capabilities use a separate HomeCapabilityBroker and are
    never routed through this raw Core authorization surface.
    """

    def authorize_core_action(
        self,
        *,
        action: str,
        session: SessionRecord | None,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=False,
            reason=(
                "Privileged JARVIS Core actions are not available through "
                "the Web Security Gateway."
            ),
            requires_step_up=True,
        )
