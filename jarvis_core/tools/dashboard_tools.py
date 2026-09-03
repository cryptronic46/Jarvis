from __future__ import annotations

from typing import Any

from jarvis_core.services.profiles import manager as profile_manager
from jarvis_core.services.agenda import agenda_store
from jarvis_core.services.integrations import integration_registry
from jarvis_core.services.privacy import privacy_state
from jarvis_core.services.security_watch import security_watch_store
from jarvis_core.services.network_inventory import network_inventory
from jarvis_core.tools.pc_health import get_pc_health
from jarvis_core.tools.environment_tools import get_home_environment


def get_dashboard_snapshot() -> dict[str, Any]:
    """Stable structured contract for the future graphical dashboard."""
    watch = security_watch_store().status()
    inventory = network_inventory().list(active_only=True)
    return {
        "ok": True,
        "profile": profile_manager().active(),
        "privacy": privacy_state().status(),
        "environment": get_home_environment(),
        "pc_health": get_pc_health(),
        "agenda": agenda_store().briefing(),
        "security_watch": {
            "baseline_exists": watch.get("baseline_exists"),
            "last_check": watch.get("last_check"),
            "alerts": watch.get("alerts", []),
        },
        "network": {
            "active_devices": inventory.get("devices", []),
            "active_count": len(inventory.get("devices", [])),
        },
        "integrations": integration_registry().status(),
        "ui_contract_version": 1,
    }
