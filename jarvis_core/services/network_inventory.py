from __future__ import annotations

from pathlib import Path
from datetime import datetime
from typing import Any
import json

from jarvis_core.tools.security_audit import get_network_security_snapshot


class NetworkInventory:
    def __init__(self, path: str | Path = "memory/network_devices.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._save({"devices": {}})

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("devices", {})
                return data
        except Exception:
            pass
        return {"devices": {}}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _key(mac: str | None, ip: str | None) -> str:
        if mac:
            return str(mac).upper()
        return "IP:" + str(ip or "unknown")

    def refresh(self) -> dict[str, Any]:
        snapshot = get_network_security_snapshot(connection_limit=20)
        if not snapshot.get("ok"):
            return snapshot

        filtered = snapshot.get("filtered") or {}
        active_rows = filtered.get("active_lan_devices") or []
        known_rows = filtered.get("lan_devices") or active_rows
        active_keys = {self._key(row.get("mac"), row.get("ip")) for row in active_rows}

        data = self._load()
        devices = data["devices"]
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        new_keys = []

        for row in known_rows:
            key = self._key(row.get("mac"), row.get("ip"))
            current = devices.get(key) or {}
            if not current:
                new_keys.append(key)
            current.update({
                "mac": row.get("mac"),
                "ip": row.get("ip"),
                "interface": row.get("interface"),
                "state": row.get("state"),
                "first_seen": current.get("first_seen") or now,
                "last_seen": now,
                "active": key in active_keys,
                "label": current.get("label"),
            })
            devices[key] = current

        for key, row in devices.items():
            if key not in active_keys:
                row["active"] = False

        data["updated_at"] = now
        self._save(data)
        return {
            "ok": True,
            "active_count": sum(1 for row in devices.values() if row.get("active")),
            "known_count": len(devices),
            "new_devices": [devices[key] for key in new_keys],
            "devices": sorted(
                devices.values(),
                key=lambda row: (
                    not bool(row.get("active")),
                    str(row.get("label") or row.get("ip") or ""),
                ),
            ),
        }

    def label(self, identifier: str, label: str) -> dict[str, Any]:
        data = self._load()
        ident = str(identifier).strip().lower()
        for key, row in data.get("devices", {}).items():
            if (
                key.lower() == ident
                or str(row.get("ip") or "").lower() == ident
                or str(row.get("mac") or "").lower() == ident
            ):
                row["label"] = str(label).strip()[:100]
                self._save(data)
                return {"ok": True, "device": row}
        return {"ok": False, "error": "DEVICE_NOT_FOUND"}

    def list(self, active_only: bool = True) -> dict[str, Any]:
        data = self._load()
        rows = list(data.get("devices", {}).values())
        if active_only:
            rows = [row for row in rows if row.get("active")]
        return {"ok": True, "active_only": active_only, "devices": rows}


_INVENTORY: NetworkInventory | None = None


def network_inventory() -> NetworkInventory:
    global _INVENTORY
    if _INVENTORY is None:
        _INVENTORY = NetworkInventory()
    return _INVENTORY


def refresh_network_inventory() -> dict[str, Any]:
    return network_inventory().refresh()


def list_network_inventory(active_only: bool = True) -> dict[str, Any]:
    return network_inventory().list(active_only)


def label_network_device(identifier: str, label: str) -> dict[str, Any]:
    return network_inventory().label(identifier, label)
