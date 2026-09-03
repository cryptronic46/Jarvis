from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import ipaddress
import json
import socket

import psutil


DEFAULT_PROBE_PORTS = [22, 80, 443, 445, 3389, 8080, 8443]
MAX_PROBE_PORTS = 32


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    target: str
    ip: str | None
    scope: str
    authorized: bool
    reason: str
    label: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "target": self.target,
            "ip": self.ip,
            "scope": self.scope,
            "authorized": self.authorized,
            "reason": self.reason,
            "label": self.label,
        }


class CyberRangeManager:
    """Owner-controlled target authority for local cyber labs.

    The local model can inspect this state and use lab-only probes, but it
    cannot add/remove scopes through model tools. Scope mutation is reserved
    for explicit OWNER CLI commands.
    """

    def __init__(
        self,
        state_path: str | Path = "memory/cyber_range.json",
        *,
        enabled: bool = True,
        probe_timeout_seconds: float = 0.45,
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled = bool(enabled)
        self.probe_timeout_seconds = max(0.05, min(float(probe_timeout_seconds), 3.0))
        self._lock = RLock()
        self._state = self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": 1,
            "mode": "owner_strict",
            "lab_scopes": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()
        if not isinstance(data, dict):
            return self._default_state()
        scopes = data.get("lab_scopes")
        if not isinstance(scopes, list):
            scopes = []
        return {
            "version": 1,
            "mode": "owner_strict",
            "lab_scopes": [x for x in scopes if isinstance(x, dict)],
        }

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _parse_network(value: str) -> ipaddress._BaseNetwork:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("EMPTY_TARGET")
        try:
            if "/" in raw:
                return ipaddress.ip_network(raw, strict=False)
            ip = ipaddress.ip_address(raw)
            suffix = 32 if ip.version == 4 else 128
            return ipaddress.ip_network(f"{ip}/{suffix}", strict=False)
        except ValueError as exc:
            raise ValueError("IP_OR_CIDR_REQUIRED") from exc

    @staticmethod
    def _private_lab_network(network: ipaddress._BaseNetwork) -> bool:
        if network.version == 4:
            allowed = (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("169.254.0.0/16"),
            )
            return any(network.subnet_of(parent) for parent in allowed)
        allowed6 = (
            ipaddress.ip_network("fc00::/7"),
            ipaddress.ip_network("fe80::/10"),
        )
        return any(network.subnet_of(parent) for parent in allowed6)

    @staticmethod
    def _owner_addresses() -> set[str]:
        values = {"127.0.0.1", "::1"}
        try:
            for rows in psutil.net_if_addrs().values():
                for row in rows:
                    if row.family not in (socket.AF_INET, socket.AF_INET6):
                        continue
                    raw = str(row.address or "").split("%", 1)[0]
                    try:
                        values.add(str(ipaddress.ip_address(raw)))
                    except ValueError:
                        pass
        except Exception:
            pass
        return values

    def add_lab_scope(self, target: str, label: str = "") -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "CYBER_RANGE_DISABLED"}
        try:
            network = self._parse_network(target)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        if not self._private_lab_network(network):
            return {
                "ok": False,
                "error": "LAB_SCOPE_MUST_BE_PRIVATE",
                "target": str(network),
            }

        # Keep authorizations narrow. A /24 is enough for a normal IPv4 lab;
        # IPv6 lab scopes must be /64 or narrower.
        if (network.version == 4 and network.prefixlen < 24) or (
            network.version == 6 and network.prefixlen < 64
        ):
            return {
                "ok": False,
                "error": "LAB_SCOPE_TOO_BROAD",
                "target": str(network),
            }

        normalized = str(network)
        with self._lock:
            for row in self._state["lab_scopes"]:
                if row.get("target") == normalized:
                    if label:
                        row["label"] = str(label)[:120]
                        self._save()
                    return {"ok": True, "already_present": True, **row}
            row = {
                "target": normalized,
                "label": str(label or "")[:120],
                "added_at": self._now(),
                "authority": "owner_cli",
            }
            self._state["lab_scopes"].append(row)
            self._save()
        return {"ok": True, "added": True, **row}

    def remove_lab_scope(self, target: str) -> dict[str, Any]:
        try:
            normalized = str(self._parse_network(target))
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        with self._lock:
            before = len(self._state["lab_scopes"])
            self._state["lab_scopes"] = [
                row for row in self._state["lab_scopes"]
                if row.get("target") != normalized
            ]
            removed = len(self._state["lab_scopes"]) != before
            if removed:
                self._save()
        return {"ok": removed, "removed": removed, "target": normalized}

    def classify(self, target: str) -> dict[str, Any]:
        raw = str(target or "").strip()
        try:
            ip = ipaddress.ip_address(raw.split("%", 1)[0])
        except ValueError:
            return ScopeDecision(
                target=raw,
                ip=None,
                scope="INVALID",
                authorized=False,
                reason="Use a literal IP address for deterministic lab authority.",
            ).as_dict()

        ip_text = str(ip)
        if ip_text in self._owner_addresses():
            return ScopeDecision(
                target=raw,
                ip=ip_text,
                scope="OWNER_MACHINE",
                authorized=False,
                reason="Owner-machine addresses are defensive-audit scope, not lab attack targets.",
            ).as_dict()

        with self._lock:
            rows = list(self._state.get("lab_scopes") or [])
        for row in rows:
            try:
                network = ipaddress.ip_network(str(row.get("target")), strict=False)
            except ValueError:
                continue
            if ip in network:
                return ScopeDecision(
                    target=raw,
                    ip=ip_text,
                    scope="LAB",
                    authorized=True,
                    reason="Target is inside an OWNER-authorized cyber lab scope.",
                    label=str(row.get("label") or "") or None,
                ).as_dict()

        if ip.is_private or ip.is_link_local:
            return ScopeDecision(
                target=raw,
                ip=ip_text,
                scope="PRIVATE_UNAUTHORIZED",
                authorized=False,
                reason="Private address is not automatically a lab target.",
            ).as_dict()

        return ScopeDecision(
            target=raw,
            ip=ip_text,
            scope="EXTERNAL",
            authorized=False,
            reason="External targets are outside the cyber-range execution scope.",
        ).as_dict()

    def status(self) -> dict[str, Any]:
        with self._lock:
            scopes = [dict(x) for x in self._state.get("lab_scopes") or []]
        return {
            "ok": True,
            "enabled": self.enabled,
            "mode": "owner_strict",
            "owner_authority": "absolute",
            "model_can_modify_scope": False,
            "lab_scopes": scopes,
            "lab_scope_count": len(scopes),
            "owner_addresses": sorted(self._owner_addresses()),
            "execution_policy": {
                "LAB": "controlled_security_testing_allowed",
                "OWNER_MACHINE": "defensive_audit_and_hardening_only",
                "PRIVATE_UNAUTHORIZED": "active_testing_blocked",
                "EXTERNAL": "active_testing_blocked",
            },
        }

    @staticmethod
    def _normalize_ports(ports: list[int] | None) -> list[int]:
        values = DEFAULT_PROBE_PORTS if not ports else ports
        normalized: list[int] = []
        for raw in values:
            try:
                port = int(raw)
            except (TypeError, ValueError):
                continue
            if not 1 <= port <= 65535 or port in normalized:
                continue
            normalized.append(port)
            if len(normalized) >= MAX_PROBE_PORTS:
                break
        return normalized

    def probe(self, target: str, ports: list[int] | None = None) -> dict[str, Any]:
        decision = self.classify(target)
        if decision.get("scope") != "LAB" or not decision.get("authorized"):
            return {
                "ok": False,
                "error": "TARGET_NOT_AUTHORIZED_LAB",
                "decision": decision,
            }

        ip = str(decision["ip"])
        port_list = self._normalize_ports(ports)
        if not port_list:
            return {"ok": False, "error": "NO_VALID_PORTS", "decision": decision}

        open_ports: list[int] = []
        closed_or_filtered: list[int] = []
        for port in port_list:
            try:
                conn = socket.create_connection(
                    (ip, port),
                    timeout=self.probe_timeout_seconds,
                )
            except (OSError, TimeoutError):
                closed_or_filtered.append(port)
            else:
                open_ports.append(port)
                try:
                    conn.close()
                except Exception:
                    pass

        return {
            "ok": True,
            "scope": "LAB",
            "target": ip,
            "label": decision.get("label"),
            "probe": "tcp_connect",
            "ports_tested": port_list,
            "open_ports": open_ports,
            "closed_or_filtered_ports": closed_or_filtered,
            "limitations": [
                "TCP connect probe only; no exploitation or payload execution.",
                "Closed and filtered are intentionally not distinguished.",
            ],
        }


def format_cyber_range_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"Cyber Range indisponível: {data.get('error', 'erro desconhecido')}"
    lines = [
        "CYBER RANGE",
        f"Modo: {data.get('mode')}",
        f"Âmbitos LAB autorizados: {data.get('lab_scope_count', 0)}",
        "Política: LAB=testes controlados | OWNER_MACHINE=auditoria defensiva | restantes=bloqueados",
    ]
    for row in data.get("lab_scopes") or []:
        label = f" · {row.get('label')}" if row.get("label") else ""
        lines.append(f"- {row.get('target')}{label}")
    if not data.get("lab_scopes"):
        lines.append("- Nenhum alvo LAB autorizado. Use /cyber lab add IP_OU_CIDR [nome].")
    return "\n".join(lines)


def format_lab_probe(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        decision = data.get("decision") or {}
        return (
            f"Sondagem bloqueada: {data.get('error', 'erro')}. "
            f"Âmbito={decision.get('scope', 'desconhecido')}. "
            f"{decision.get('reason', '')}"
        ).strip()
    label = f" ({data.get('label')})" if data.get("label") else ""
    open_text = ", ".join(str(x) for x in data.get("open_ports") or []) or "nenhuma"
    tested = ", ".join(str(x) for x in data.get("ports_tested") or [])
    return "\n".join([
        f"CYBER LAB — TCP {data.get('target')}{label}",
        f"Portas testadas: {tested}",
        f"Portas abertas: {open_text}",
        "Resultado: sondagem TCP controlada; sem exploração/payload.",
    ])


_MANAGER: CyberRangeManager | None = None


def set_cyber_range_manager(manager: CyberRangeManager) -> None:
    global _MANAGER
    _MANAGER = manager


def cyber_range_manager() -> CyberRangeManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = CyberRangeManager()
    return _MANAGER


def get_cyber_range_status() -> dict[str, Any]:
    return cyber_range_manager().status()


def classify_cyber_target(target: str) -> dict[str, Any]:
    return cyber_range_manager().classify(target)


def probe_cyber_lab_target(
    target: str,
    ports: list[int] | None = None,
) -> dict[str, Any]:
    return cyber_range_manager().probe(target, ports)
