from __future__ import annotations

from pathlib import Path
from datetime import datetime
from threading import Event, Thread
from typing import Any
import json

from jarvis_core.tools.security_audit import run_security_audit


class SecurityWatchStore:
    def __init__(
        self,
        baseline_path: str | Path = "memory/security_baseline.json",
        state_path: str | Path = "memory/security_watch.json",
    ):
        self.baseline_path = Path(baseline_path)
        self.state_path = Path(state_path)
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def fingerprint(audit: dict[str, Any]) -> dict[str, Any]:
        accounts = audit.get("accounts") or {}
        sessions = audit.get("sessions") or {}
        network = audit.get("network") or {}
        posture = audit.get("windows_security") or {}
        defender = posture.get("defender") or {}
        return {
            "other_admin_sids": sorted(
                str(row.get("sid"))
                for row in accounts.get("other_enabled_or_unknown_admin_principals", [])
                if row.get("sid")
            ),
            "remote_sessions": sorted(
                f"{row.get('domain')}\\{row.get('username')}@{row.get('client_name')}"
                for row in sessions.get("remote_sessions", [])
            ),
            "remote_access_software": sorted(
                str(row.get("product"))
                for row in network.get("remote_access_software_running", [])
                if row.get("product")
            ),
            "active_lan_macs": sorted(
                str(row.get("mac")).upper()
                for row in (network.get("filtered") or {}).get("active_lan_devices", [])
                if row.get("mac")
            ),
            "firewall_all_enabled": bool(
                posture.get("firewall")
                and all(row.get("enabled") is True for row in posture.get("firewall", []))
            ),
            "defender_realtime_enabled": defender.get("real_time_protection_enabled"),
            "rdp_enabled": posture.get("rdp_enabled"),
            "remote_assistance_enabled": posture.get("remote_assistance_enabled"),
        }

    def baseline(self) -> dict[str, Any]:
        audit = run_security_audit()
        if not audit.get("ok"):
            return audit
        payload = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "fingerprint": self.fingerprint(audit),
        }
        self.baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, **payload}

    def _load_baseline(self) -> dict[str, Any] | None:
        if not self.baseline_path.exists():
            return None
        try:
            return json.loads(self.baseline_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def check(self) -> dict[str, Any]:
        baseline = self._load_baseline()
        if not baseline:
            created = self.baseline()
            return {
                "ok": bool(created.get("ok")),
                "baseline_created": True,
                "alerts": [],
                "baseline": created,
            }

        audit = run_security_audit()
        if not audit.get("ok"):
            return audit

        old = baseline.get("fingerprint") or {}
        new = self.fingerprint(audit)
        alerts = []

        new_admins = sorted(set(new["other_admin_sids"]) - set(old.get("other_admin_sids", [])))
        if new_admins:
            alerts.append({
                "severity": "critical",
                "code": "NEW_ADMIN",
                "message": "Foi detetado um novo administrador no Windows.",
                "values": new_admins,
            })
        if new["remote_sessions"]:
            alerts.append({
                "severity": "critical",
                "code": "REMOTE_SESSION",
                "message": "Existe uma sessão remota ativa.",
                "values": new["remote_sessions"],
            })
        new_tools = sorted(set(new["remote_access_software"]) - set(old.get("remote_access_software", [])))
        if new_tools:
            alerts.append({
                "severity": "attention",
                "code": "NEW_REMOTE_ACCESS_SOFTWARE",
                "message": "Novo software de acesso remoto está em execução.",
                "values": new_tools,
            })
        if old.get("firewall_all_enabled") is True and new.get("firewall_all_enabled") is False:
            alerts.append({
                "severity": "critical",
                "code": "FIREWALL_DISABLED",
                "message": "A Firewall deixou de estar ativa em todos os perfis.",
            })
        if old.get("defender_realtime_enabled") is True and new.get("defender_realtime_enabled") is False:
            alerts.append({
                "severity": "critical",
                "code": "DEFENDER_DISABLED",
                "message": "A proteção em tempo real do Defender foi desativada.",
            })
        new_devices = sorted(set(new["active_lan_macs"]) - set(old.get("active_lan_macs", [])))
        if new_devices:
            alerts.append({
                "severity": "info",
                "code": "NEW_LAN_DEVICE",
                "message": "Novo dispositivo ativo visto na rede local.",
                "values": new_devices,
            })

        state = {
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "alerts": alerts,
            "current_fingerprint": new,
        }
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "baseline_created": False, **state}

    def status(self) -> dict[str, Any]:
        baseline = self._load_baseline()
        state = {}
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        return {
            "ok": True,
            "baseline_exists": bool(baseline),
            "baseline_created_at": baseline.get("created_at") if baseline else None,
            "last_check": state.get("checked_at"),
            "alerts": state.get("alerts", []),
        }


_STORE: SecurityWatchStore | None = None


def security_watch_store() -> SecurityWatchStore:
    global _STORE
    if _STORE is None:
        _STORE = SecurityWatchStore()
    return _STORE


def create_security_baseline() -> dict[str, Any]:
    return security_watch_store().baseline()


def check_security_watch() -> dict[str, Any]:
    return security_watch_store().check()


def get_security_watch_status() -> dict[str, Any]:
    return security_watch_store().status()


class SecurityWatchService:
    def __init__(
        self,
        events,
        interval_seconds: float = 120.0,
        resource_guard=None,
    ):
        self.events = events
        self.interval_seconds = max(60.0, float(interval_seconds))
        self.resource_guard = resource_guard
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="jarvis-security-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                if (
                    self.resource_guard is not None
                    and self.resource_guard("security_watch")
                ):
                    self.events.emit(
                        "BACKGROUND_WORK_DEFERRED",
                        workload="security_watch",
                    )
                    continue

                result = security_watch_store().check()
                alerts = result.get("alerts") or []
                if alerts:
                    self.events.emit("SECURITY_WATCH_ALERT", count=len(alerts), alerts=alerts)
            except Exception as exc:
                self.events.emit("SECURITY_WATCH_ERROR", error=f"{type(exc).__name__}: {exc}")
