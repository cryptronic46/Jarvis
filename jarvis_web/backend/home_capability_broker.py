from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from jarvis_web.backend.auth import SessionRecord


class HomeRiskTier(str, Enum):
    READ = "read"
    NORMAL = "normal"
    CRITICAL = "critical"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class HomeAuthorizationDecision:
    allowed: bool
    tier: HomeRiskTier
    reason: str
    requires_step_up: bool = False


# Capability names are deliberately structured. The Web never receives a
# generic Home Assistant service-call or arbitrary command primitive.
READ_CAPABILITIES = frozenset(
    {
        "home.snapshot",
        "home.entity_state",
        "home.temperature",
        "home.humidity",
        "home.air_quality",
        "home.openings",
        "home.presence",
        "home.energy",
        "home.appliance_state",
    }
)

NORMAL_CONTROL_CAPABILITIES = frozenset(
    {
        "light.turn_on",
        "light.turn_off",
        "light.toggle",
        "light.set_level",
        "light.set_color",
        "switch.turn_on",
        "switch.turn_off",
        "cover.open",
        "cover.close",
        "cover.stop",
        "climate.turn_on",
        "climate.turn_off",
        "climate.set_temperature",
        "fan.turn_on",
        "fan.turn_off",
        "media_player.turn_on",
        "media_player.turn_off",
        "media_player.set_volume",
        "appliance.start_cycle",
        "appliance.pause_cycle",
        "appliance.stop_cycle",
    }
)

CRITICAL_CAPABILITIES = frozenset(
    {
        "lock.lock",
        "lock.unlock",
        "alarm.arm",
        "alarm.disarm",
        "garage.open",
        "gate.open",
        "camera.disable",
        "security_sensor.disable",
        "appliance.start_high_heat",
    }
)

# These are administrative/general-purpose surfaces, not user capabilities.
# They remain unavailable through Web Chat even after Home Assistant is wired.
FORBIDDEN_CAPABILITIES = frozenset(
    {
        "home.admin",
        "home.raw_service_call",
        "home.template_execute",
        "home.shell_command",
        "home.configuration_write",
    }
)


class HomeCapabilityBroker:
    """Capability-level authorization for future Home Assistant integration.

    v0.5.0 defines policy only. It does not connect to Home Assistant and does
    not execute any device action.
    """

    def classify(self, capability: str) -> HomeRiskTier:
        if capability in READ_CAPABILITIES:
            return HomeRiskTier.READ
        if capability in NORMAL_CONTROL_CAPABILITIES:
            return HomeRiskTier.NORMAL
        if capability in CRITICAL_CAPABILITIES:
            return HomeRiskTier.CRITICAL
        return HomeRiskTier.FORBIDDEN

    def authorize(
        self,
        *,
        capability: str,
        session: SessionRecord | None,
    ) -> HomeAuthorizationDecision:
        tier = self.classify(capability)

        if session is None:
            return HomeAuthorizationDecision(
                False,
                tier,
                "Authentication required.",
            )

        if tier is HomeRiskTier.READ:
            allowed = session.has_scope("home.read")
            return HomeAuthorizationDecision(
                allowed,
                tier,
                "Home state query allowed." if allowed else "Missing home.read scope.",
            )

        if tier is HomeRiskTier.NORMAL:
            allowed = session.has_scope("home.control")
            return HomeAuthorizationDecision(
                allowed,
                tier,
                "Normal home control allowed." if allowed else "Missing home.control scope.",
            )

        if tier is HomeRiskTier.CRITICAL:
            # Critical operations require a separate future step-up flow and
            # explicit home.critical scope. Neither exists in v0.5.0.
            return HomeAuthorizationDecision(
                False,
                tier,
                "Critical home action requires step-up authentication.",
                requires_step_up=True,
            )

        return HomeAuthorizationDecision(
            False,
            HomeRiskTier.FORBIDDEN,
            "Unknown, administrative or raw Home Assistant operations are forbidden.",
            requires_step_up=False,
        )

    def manifest(self) -> dict[str, object]:
        return {
            "execution_available": False,
            "integration_state": "policy_only",
            "read": sorted(READ_CAPABILITIES),
            "normal_control": sorted(NORMAL_CONTROL_CAPABILITIES),
            "critical_step_up": sorted(CRITICAL_CAPABILITIES),
            "raw_or_admin_surfaces": "forbidden",
        }
