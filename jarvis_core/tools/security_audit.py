from __future__ import annotations

from datetime import datetime
from typing import Any
import ctypes
import getpass
import ipaddress
import json
import os
import platform
import socket
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream

import psutil


REMOTE_ACCESS_PROCESS_NAMES = {
    "anydesk.exe": "AnyDesk",
    "teamviewer.exe": "TeamViewer",
    "teamviewer_service.exe": "TeamViewer",
    "rustdesk.exe": "RustDesk",
    "parsecd.exe": "Parsec",
    "parsec.exe": "Parsec",
    "remoting_host.exe": "Chrome Remote Desktop",
    "chromoting_host.exe": "Chrome Remote Desktop",
    "splashtop_remote_service.exe": "Splashtop",
    "screenconnect.clientservice.exe": "ScreenConnect",
    "screenconnect.windowsclient.exe": "ScreenConnect",
    "dwagent.exe": "DWService",
    "dwservice.exe": "DWService",
    "meshagent.exe": "MeshCentral Agent",
    "logmein.exe": "LogMeIn",
}


ADMIN_ACCOUNTS_SCRIPT = r'''
$ErrorActionPreference = "Stop"
$result = [ordered]@{
    ok = $true
    current = [ordered]@{}
    administrators = @()
    local_users = @()
}
try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    $result.current = [ordered]@{
        name = $identity.Name
        sid = $identity.User.Value
        is_admin = $principal.IsInRole(
            [System.Security.Principal.WindowsBuiltInRole]::Administrator
        )
    }

    $users = @(
        Get-CimInstance Win32_UserAccount -Filter "LocalAccount=True" |
        ForEach-Object {
            [PSCustomObject]@{
                name = $_.Name
                domain = $_.Domain
                sid = $_.SID
                disabled = [bool]$_.Disabled
                lockout = [bool]$_.Lockout
                password_required = [bool]$_.PasswordRequired
            }
        }
    )
    $result.local_users = $users

    $group = Get-CimInstance Win32_Group -Filter "LocalAccount=True AND SID='S-1-5-32-544'"
    $members = @()
    if ($null -ne $group) {
        try {
            $members = @(
                Get-CimAssociatedInstance -InputObject $group -Association Win32_GroupUser |
                ForEach-Object {
                    $className = $_.CimClass.CimClassName
                    [PSCustomObject]@{
                        name = $_.Name
                        domain = $_.Domain
                        sid = $_.SID
                        type = $className
                        local_account = $_.LocalAccount
                        disabled = (
                            if ($className -eq "Win32_UserAccount") {
                                [bool]$_.Disabled
                            } else {
                                $null
                            }
                        )
                    }
                }
            )
        } catch {
            try {
                $members = @(
                    Get-LocalGroupMember -SID "S-1-5-32-544" |
                    ForEach-Object {
                        [PSCustomObject]@{
                            name = $_.Name
                            domain = $null
                            sid = if ($null -ne $_.SID) { $_.SID.Value } else { $null }
                            type = [string]$_.ObjectClass
                            local_account = $null
                            disabled = $null
                        }
                    }
                )
            } catch {
                $members = @()
                $result.admin_error = $_.Exception.Message
            }
        }
    }
    $result.administrators = $members
} catch {
    $result.ok = $false
    $result.error = "ADMIN_QUERY_FAILED"
    $result.message = $_.Exception.Message
}
$result | ConvertTo-Json -Depth 7 -Compress
'''


WINDOWS_PROTECTION_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"
$result = [ordered]@{
    ok = $true
    firewall = @()
    defender = $null
    smb_sessions = @()
}
try {
    $result.firewall = @(
        Get-NetFirewallProfile |
        ForEach-Object {
            [PSCustomObject]@{
                name = $_.Name
                enabled = [bool]$_.Enabled
                default_inbound_action = [string]$_.DefaultInboundAction
                default_outbound_action = [string]$_.DefaultOutboundAction
            }
        }
    )
} catch { $result.firewall_error = $_.Exception.Message }

try {
    $mp = Get-MpComputerStatus
    if ($null -ne $mp) {
        $signatureUpdated = $null
        if ($null -ne $mp.AntivirusSignatureLastUpdated) {
            $signatureUpdated = $mp.AntivirusSignatureLastUpdated.ToString("o")
        }
        $result.defender = [ordered]@{
            antivirus_enabled = [bool]$mp.AntivirusEnabled
            antispyware_enabled = [bool]$mp.AntispywareEnabled
            real_time_protection_enabled = [bool]$mp.RealTimeProtectionEnabled
            behavior_monitor_enabled = [bool]$mp.BehaviorMonitorEnabled
            ioav_protection_enabled = [bool]$mp.IoavProtectionEnabled
            network_inspection_enabled = [bool]$mp.NISEnabled
            antivirus_signature_last_updated = $signatureUpdated
        }
    }
} catch { $result.defender_error = $_.Exception.Message }

try {
    $result.smb_sessions = @(
        Get-SmbSession |
        ForEach-Object {
            [PSCustomObject]@{
                client_computer = $_.ClientComputerName
                client_user = $_.ClientUserName
                num_opens = $_.NumOpens
                seconds_exists = $_.SecondsExists
            }
        }
    )
} catch { $result.smb_error = $_.Exception.Message }

$result | ConvertTo-Json -Depth 7 -Compress
'''


NETWORK_NEIGHBORS_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"
$result = [ordered]@{
    ok = $true
    neighbors = @()
    default_routes = @()
}
try {
    $result.neighbors = @(
        Get-NetNeighbor -AddressFamily IPv4 |
        Where-Object {
            $_.State -in @(
                "Reachable", "Stale", "Delay",
                "Probe", "Permanent"
            )
        } |
        ForEach-Object {
            [PSCustomObject]@{
                interface = $_.InterfaceAlias
                ip = $_.IPAddress
                mac = $_.LinkLayerAddress
                state = [string]$_.State
            }
        }
    )
} catch {
    $result.neighbor_error = $_.Exception.Message
}
try {
    $result.default_routes = @(
        Get-NetRoute `
            -AddressFamily IPv4 `
            -DestinationPrefix "0.0.0.0/0" |
        Sort-Object RouteMetric, InterfaceMetric |
        ForEach-Object {
            [PSCustomObject]@{
                interface = $_.InterfaceAlias
                if_index = $_.InterfaceIndex
                next_hop = $_.NextHop
                route_metric = $_.RouteMetric
                interface_metric = $_.InterfaceMetric
            }
        }
    )
} catch {
    $result.route_error = $_.Exception.Message
}
if (
    $null -ne $result.neighbor_error -and
    $null -ne $result.route_error
) {
    $result.ok = $false
    $result.error = "NET_QUERY_FAILED"
}
$result | ConvertTo-Json -Depth 6 -Compress
'''


def _windows() -> bool:
    return platform.system().lower() == "windows"


def _run_fixed_powershell_json(script: str, timeout_seconds: float = 8.0) -> dict[str, Any]:
    # No user/LLM text is interpolated into these fixed scripts.
    if not _windows():
        return {"ok": False, "error": "WINDOWS_ONLY", "message": "Esta auditoria requer Windows."}
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=max(3.0, min(float(timeout_seconds), 15.0)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "POWERSHELL_NOT_FOUND"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "POWERSHELL_TIMEOUT"}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    raw = decode_subprocess_stream(completed.stdout).strip()
    if not raw:
        return {"ok": False, "error": "POWERSHELL_EMPTY_OUTPUT", "message": decode_subprocess_stream(completed.stderr).strip()}
    try:
        value = json.loads(raw.splitlines()[-1])
        return value if isinstance(value, dict) else {"ok": True, "value": value}
    except Exception as exc:
        return {
            "ok": False,
            "error": "POWERSHELL_INVALID_JSON",
            "message": f"{type(exc).__name__}: {exc}",
            "raw_tail": raw[-500:],
        }


def _read_registry_dword(path: str, name: str) -> int | None:
    if not _windows():
        return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return int(winreg.QueryValueEx(key, name)[0])
    except Exception:
        return None


def get_admin_accounts() -> dict[str, Any]:
    result = _run_fixed_powershell_json(ADMIN_ACCOUNTS_SCRIPT)
    if not result.get("ok"):
        return result

    current = result.get("current") or {}
    current_sid = str(current.get("sid") or "").lower()
    admins = result.get("administrators") or []
    local_users = result.get("local_users") or []
    local_user_by_sid = {
        str(row.get("sid") or "").lower(): row
        for row in local_users
        if row.get("sid")
    }

    normalized = []
    for item in admins:
        sid = str(item.get("sid") or "")
        local_user = local_user_by_sid.get(sid.lower())
        disabled = item.get("disabled")
        if disabled is None and local_user is not None:
            disabled = local_user.get("disabled")
        normalized.append({
            "name": item.get("name"),
            "domain": item.get("domain"),
            "sid": sid or None,
            "type": item.get("type"),
            "disabled": disabled,
            "is_current_user": bool(current_sid and sid and sid.lower() == current_sid),
        })

    other_admins = [row for row in normalized if not row["is_current_user"]]
    other_enabled_or_unknown = [row for row in other_admins if row.get("disabled") is not True]
    current_is_member = any(row["is_current_user"] for row in normalized)

    return {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "current_user": {
            "name": current.get("name"),
            "sid": current.get("sid"),
            "token_is_admin": bool(current.get("is_admin")),
            "in_local_administrators_group": current_is_member,
        },
        "administrators": normalized,
        "other_admin_principals": other_admins,
        "other_enabled_or_unknown_admin_principals": other_enabled_or_unknown,
        "local_users": local_users,
        "only_current_enabled_admin_detected": bool(current_is_member and not other_enabled_or_unknown),
        "limitations": [
            "Contas de domínio/Microsoft/Entra podem aparecer como principais externos e nem sempre expõem estado disabled."
        ],
    }


def _query_wts_string(wtsapi32, server, session_id: int, info_class: int) -> str:
    import ctypes.wintypes as wintypes
    buffer = wintypes.LPWSTR()
    bytes_returned = wintypes.DWORD()
    ok = wtsapi32.WTSQuerySessionInformationW(
        server, wintypes.DWORD(session_id), info_class,
        ctypes.byref(buffer), ctypes.byref(bytes_returned),
    )
    if not ok or not buffer:
        return ""
    try:
        return str(buffer.value or "")
    finally:
        wtsapi32.WTSFreeMemory(buffer)


def get_active_user_sessions() -> dict[str, Any]:
    if not _windows():
        return {"ok": False, "error": "WINDOWS_ONLY"}
    try:
        import ctypes.wintypes as wintypes

        class WTS_SESSION_INFO(ctypes.Structure):
            _fields_ = [
                ("SessionId", wintypes.DWORD),
                ("pWinStationName", wintypes.LPWSTR),
                ("State", wintypes.DWORD),
            ]

        wtsapi32 = ctypes.WinDLL("Wtsapi32.dll")
        kernel32 = ctypes.WinDLL("Kernel32.dll")
        pp_info = ctypes.POINTER(WTS_SESSION_INFO)()
        count = wintypes.DWORD()

        if not wtsapi32.WTSEnumerateSessionsW(
            wintypes.HANDLE(0), 0, 1, ctypes.byref(pp_info), ctypes.byref(count)
        ):
            return {"ok": False, "error": "WTS_ENUM_FAILED"}

        current_session = wintypes.DWORD()
        kernel32.ProcessIdToSessionId(wintypes.DWORD(os.getpid()), ctypes.byref(current_session))

        rows = []
        try:
            array_type = WTS_SESSION_INFO * count.value
            sessions = ctypes.cast(pp_info, ctypes.POINTER(array_type)).contents
            for item in sessions:
                username = _query_wts_string(wtsapi32, wintypes.HANDLE(0), int(item.SessionId), 5)
                if not username:
                    continue
                domain = _query_wts_string(wtsapi32, wintypes.HANDLE(0), int(item.SessionId), 7)
                client = _query_wts_string(wtsapi32, wintypes.HANDLE(0), int(item.SessionId), 10)
                station = str(item.pWinStationName or "")
                remote = bool(station.lower().startswith("rdp") or client.strip())
                rows.append({
                    "session_id": int(item.SessionId),
                    "username": username,
                    "domain": domain,
                    "station": station,
                    "state_code": int(item.State),
                    "client_name": client or None,
                    "is_remote": remote,
                    "is_current_process_session": int(item.SessionId) == int(current_session.value),
                })
        finally:
            wtsapi32.WTSFreeMemory(pp_info)

        remote_sessions = [row for row in rows if row["is_remote"]]
        other_sessions = [row for row in rows if not row["is_current_process_session"]]
        return {
            "ok": True,
            "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "sessions": rows,
            "remote_sessions": remote_sessions,
            "other_user_sessions": other_sessions,
            "only_current_session_detected": not other_sessions,
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}


def _ip_classification(value: str | None) -> str | None:
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return "invalid"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_private:
        return "private"
    if ip.is_multicast:
        return "multicast"
    if ip.is_unspecified:
        return "unspecified"
    return "public"


def _process_name(pid: int | None) -> str | None:
    if not pid:
        return None
    try:
        return psutil.Process(int(pid)).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
        return None


def _endpoint(addr) -> dict[str, Any] | None:
    if not addr:
        return None
    try:
        ip, port = addr.ip, addr.port
    except AttributeError:
        try:
            ip, port = addr[0], addr[1]
        except Exception:
            return None
    return {"ip": str(ip), "port": int(port), "scope": _ip_classification(str(ip))}


def _remote_access_processes() -> list[dict[str, Any]]:
    rows, seen = [], set()
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            if name in REMOTE_ACCESS_PROCESS_NAMES:
                key = (proc.info.get("pid"), name)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "pid": proc.info.get("pid"),
                    "process": proc.info.get("name"),
                    "product": REMOTE_ACCESS_PROCESS_NAMES[name],
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return rows



def _usable_lan_neighbor(row: dict[str, Any]) -> bool:
    ip_text = str(row.get("ip") or "")
    mac = str(row.get("mac") or "").upper().strip()
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False

    if not isinstance(ip, ipaddress.IPv4Address):
        return False
    if not ip.is_private:
        return False
    if ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return False
    if ip_text.endswith(".255"):
        return False
    if mac in {"", "FF-FF-FF-FF-FF-FF", "00-00-00-00-00-00"}:
        return False
    return True


def _active_lan_neighbor(row: dict[str, Any]) -> bool:
    if not _usable_lan_neighbor(row):
        return False
    return str(row.get("state") or "").lower() in {
        "reachable",
        "delay",
        "probe",
    }


def _default_route_aliases(
    routes: list[dict[str, Any]],
) -> list[str]:
    aliases = []
    seen = set()
    for row in routes:
        name = str(row.get("interface") or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        aliases.append(name)
    return aliases


def _meaningful_connection(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or "").upper()
    remote = row.get("remote") or {}
    if status != "ESTABLISHED" or not remote:
        return False
    if remote.get("scope") == "loopback":
        return False
    return True


def _externally_reachable_listener(row: dict[str, Any]) -> bool:
    local = row.get("local") or {}
    ip = str(local.get("ip") or "")
    scope = local.get("scope")
    if scope == "loopback":
        return False
    return ip in {"0.0.0.0", "::"} or scope in {"private", "public"}


def _dedupe_remote_connections(
    rows: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for row in rows:
        remote = row.get("remote") or {}
        key = (
            str(remote.get("ip") or ""),
            int(remote.get("port") or 0),
            str(row.get("process") or ""),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= limit:
            break
    return result


def _primary_interfaces(
    interfaces: list[dict[str, Any]],
    default_route_aliases: list[str] | None = None,
) -> list[dict[str, Any]]:
    aliases = {
        str(value).lower()
        for value in (default_route_aliases or [])
        if str(value).strip()
    }
    candidates = []
    for interface in interfaces:
        if not interface.get("is_up"):
            continue
        ipv4 = [
            addr
            for addr in interface.get("addresses") or []
            if (
                addr.get("family") == "IPv4"
                and addr.get("scope") == "private"
                and not str(addr.get("address") or "").startswith("169.254.")
            )
        ]
        if not ipv4:
            continue
        name = str(interface.get("name") or "")
        candidates.append({
            "name": name,
            "speed_mbps": interface.get("speed_mbps"),
            "ipv4": [addr.get("address") for addr in ipv4],
            "is_default_route": name.lower() in aliases,
        })
    routed=[row for row in candidates if row["is_default_route"]]
    if routed:
        return routed[:1]
    def fallback_score(row):
        name=str(row.get("name") or "").lower(); score=0
        if "wi-fi" in name or "wifi" in name: score += 100
        if "ethernet" in name: score += 50
        if any(t in name for t in ("virtual","vmware","vbox","host-only","hyper-v","wsl")): score -= 200
        return score, int(row.get("speed_mbps") or 0)
    candidates.sort(key=fallback_score, reverse=True)
    return candidates[:1]


def _security_level(findings: list[dict[str, Any]]) -> str:
    severities = {str(x.get("severity") or "") for x in findings}
    if "critical" in severities:
        return "critical"
    if "attention" in severities:
        return "attention"
    return "ok"


def get_network_security_snapshot(connection_limit: int = 80) -> dict[str, Any]:
    connection_limit = max(10, min(int(connection_limit), 200))
    interfaces = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        stat = stats.get(name)
        interface = {
            "name": name,
            "is_up": bool(stat.isup if stat else False),
            "speed_mbps": stat.speed if stat else None,
            "addresses": [],
        }
        for addr in addrs:
            if addr.family == socket.AF_INET:
                interface["addresses"].append({
                    "family": "IPv4",
                    "address": addr.address,
                    "netmask": addr.netmask,
                    "scope": _ip_classification(addr.address),
                })
            elif addr.family == socket.AF_INET6:
                ip = addr.address.split("%")[0]
                interface["addresses"].append({
                    "family": "IPv6",
                    "address": ip,
                    "scope": _ip_classification(ip),
                })
        if interface["addresses"]:
            interfaces.append(interface)

    established, listeners = [], []
    connection_error = None
    try:
        for conn in psutil.net_connections(kind="inet"):
            local, remote = _endpoint(conn.laddr), _endpoint(conn.raddr)
            row = {
                "local": local,
                "remote": remote,
                "status": str(conn.status),
                "pid": conn.pid,
                "process": _process_name(conn.pid),
            }
            if str(conn.status).upper() == "LISTEN":
                listeners.append(row)
            elif remote:
                established.append(row)
    except psutil.AccessDenied as exc:
        connection_error = f"AccessDenied: {exc}"
    except Exception as exc:
        connection_error = f"{type(exc).__name__}: {exc}"

    public_established = [
        row for row in established
        if row.get("remote") and row["remote"].get("scope") == "public"
    ]
    neighbors_result = _run_fixed_powershell_json(
        NETWORK_NEIGHBORS_SCRIPT,
        timeout_seconds=6.0,
    )
    neighbors = (
        neighbors_result.get("neighbors") or []
        if neighbors_result.get("ok")
        else []
    )
    default_routes = (
        neighbors_result.get("default_routes") or []
        if neighbors_result.get("ok")
        else []
    )
    remote_tools = _remote_access_processes()

    lan_devices = [
        row for row in neighbors
        if _usable_lan_neighbor(row)
    ]
    active_lan_devices = [
        row for row in lan_devices
        if _active_lan_neighbor(row)
    ]
    meaningful_connections = [
        row for row in established
        if _meaningful_connection(row)
    ]
    reachable_listeners = [
        row for row in listeners
        if _externally_reachable_listener(row)
    ]
    filtered_remote_connections = _dedupe_remote_connections(
        meaningful_connections,
        limit=20,
    )
    active_interfaces = _primary_interfaces(
        interfaces,
        _default_route_aliases(default_routes),
    )

    return {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "interfaces": interfaces,
        "listening_ports": listeners[:connection_limit],
        "established_connections": established[:connection_limit],
        "public_established_connections": public_established[:connection_limit],
        "counts": {
            "listeners_raw": len(listeners),
            "listeners_non_loopback": len(reachable_listeners),
            "connections_raw": len(established),
            "established_non_loopback": len(meaningful_connections),
            "public_established": len(public_established),
            "neighbors_raw": len(neighbors),
            "lan_devices_known": len(lan_devices),
            "lan_devices_active": len(active_lan_devices),
            "lan_devices": len(active_lan_devices),
            "remote_access_processes": len(remote_tools),
        },
        "filtered": {
            "active_interfaces": active_interfaces,
            "active_lan_devices": active_lan_devices[:30],
            "lan_devices": lan_devices[:30],
            "remote_connections": filtered_remote_connections,
            "non_loopback_listeners": reachable_listeners[:30],
            "default_routes": default_routes[:10],
        },
        "known_ipv4_neighbors": neighbors[:80],
        "remote_access_software_running": remote_tools,
        "connection_error": connection_error,
        "notes": [
            "Ligações TCP/UDP normais não significam acesso remoto ao PC.",
            "A tabela de vizinhos é passiva; não é um scan ativo da LAN.",
        ],
    }


def get_windows_security_posture() -> dict[str, Any]:
    if not _windows():
        return {"ok": False, "error": "WINDOWS_ONLY"}

    protection = _run_fixed_powershell_json(WINDOWS_PROTECTION_SCRIPT, timeout_seconds=10.0)
    rdp_deny = _read_registry_dword(
        r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections"
    )
    remote_assistance = _read_registry_dword(
        r"SYSTEM\CurrentControlSet\Control\Remote Assistance", "fAllowToGetHelp"
    )
    return {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "hostname": socket.gethostname(),
        },
        "rdp_enabled": None if rdp_deny is None else rdp_deny == 0,
        "remote_assistance_enabled": None if remote_assistance is None else remote_assistance == 1,
        "firewall": protection.get("firewall") or [],
        "defender": protection.get("defender"),
        "smb_sessions": protection.get("smb_sessions") or [],
        "query_errors": {k: v for k, v in protection.items() if k.endswith("_error")},
    }


def _security_summary(
    admins: dict[str, Any],
    sessions: dict[str, Any],
    network: dict[str, Any],
    posture: dict[str, Any],
) -> dict[str, Any]:
    current = admins.get("current_user") or {}
    current_name = current.get("name") or getpass.getuser()
    remote_sessions = sessions.get("remote_sessions") or [] if sessions.get("ok") else []
    other_sessions = sessions.get("other_user_sessions") or [] if sessions.get("ok") else []
    smb_sessions = posture.get("smb_sessions") or []
    remote_tools = network.get("remote_access_software_running") or []
    other_admins = admins.get("other_enabled_or_unknown_admin_principals") or []
    active_remote_access_detected = bool(remote_sessions or smb_sessions)
    findings = []

    if remote_sessions:
        findings.append({"severity":"attention","code":"REMOTE_INTERACTIVE_SESSION","message":f"Há {len(remote_sessions)} sessão(ões) interativa(s) remota(s)."})
    if smb_sessions:
        findings.append({"severity":"attention","code":"SMB_SESSION","message":f"Há {len(smb_sessions)} sessão(ões) SMB remota(s) ativa(s)."})
    if other_sessions:
        findings.append({"severity":"info","code":"OTHER_USER_SESSION","message":f"Há {len(other_sessions)} outra(s) sessão(ões) de utilizador."})
    if other_admins:
        findings.append({"severity":"info","code":"OTHER_ADMIN_PRINCIPAL","message":f"Existem {len(other_admins)} outro(s) principal(is) administrador(es)."})
    if remote_tools:
        findings.append({
            "severity":"info","code":"REMOTE_ACCESS_SOFTWARE_RUNNING",
            "message":"Software de acesso remoto em execução: " + ", ".join(sorted({str(x.get('product')) for x in remote_tools if x.get('product')})) + "."
        })

    disabled_firewalls = [row for row in (posture.get("firewall") or []) if row.get("enabled") is False]
    if disabled_firewalls:
        findings.append({
            "severity":"attention","code":"FIREWALL_PROFILE_DISABLED",
            "message":"Perfis Firewall desativados: " + ", ".join(str(x.get("name")) for x in disabled_firewalls) + "."
        })
    defender = posture.get("defender") or {}
    if defender and defender.get("real_time_protection_enabled") is False:
        findings.append({
            "severity":"attention",
            "code":"DEFENDER_REALTIME_DISABLED",
            "message":"A proteção em tempo real do Microsoft Defender aparece desativada."
        })
    elif not defender:
        defender_error = (posture.get("query_errors") or {}).get(
            "defender_error"
        )
        findings.append({
            "severity":"info",
            "code":"DEFENDER_STATUS_UNKNOWN",
            "message":(
                "Não consegui confirmar o estado do Microsoft Defender"
                + (f": {defender_error}" if defender_error else ".")
            ),
        })

    if posture.get("remote_assistance_enabled") is True:
        findings.append({
            "severity":"attention",
            "code":"REMOTE_ASSISTANCE_ENABLED",
            "message":(
                "A Assistência Remota do Windows está permitida. "
                "Isto não significa que exista alguém ligado neste momento."
            ),
        })
    if not active_remote_access_detected and not other_sessions:
        findings.append({"severity":"ok","code":"NO_OTHER_ACTIVE_SESSION_DETECTED","message":"Não encontrei outra sessão de utilizador nem uma sessão RDP/SMB ativa."})
    if admins.get("only_current_enabled_admin_detected"):
        findings.append({"severity":"ok","code":"ONLY_CURRENT_ADMIN_DETECTED","message":"O utilizador atual é o único administrador habilitado que consegui confirmar."})

    return {
        "current_user": current_name,
        "current_user_admin": bool(current.get("token_is_admin") or current.get("in_local_administrators_group")),
        "only_current_enabled_admin_detected": admins.get("only_current_enabled_admin_detected"),
        "other_admin_count": len(other_admins),
        "other_session_count": len(other_sessions),
        "remote_interactive_session_count": len(remote_sessions),
        "smb_session_count": len(smb_sessions),
        "remote_access_software_count": len(remote_tools),
        "active_remote_access_detected": active_remote_access_detected,
        "rdp_enabled": posture.get("rdp_enabled"),
        "remote_assistance_enabled": posture.get("remote_assistance_enabled"),
        "firewall_all_enabled": bool(
            posture.get("firewall")
            and all(
                row.get("enabled") is True
                for row in posture.get("firewall") or []
            )
        ),
        "defender_realtime_enabled": (
            defender.get("real_time_protection_enabled")
            if defender
            else None
        ),
        "network": {
            "active_interfaces": (
                (network.get("filtered") or {}).get("active_interfaces")
                or []
            ),
            "lan_device_count": (
                (network.get("counts") or {}).get("lan_devices", 0)
            ),
            "non_loopback_connection_count": (
                (network.get("counts") or {}).get(
                    "established_non_loopback",
                    0,
                )
            ),
            "public_connection_count": (
                (network.get("counts") or {}).get(
                    "public_established",
                    0,
                )
            ),
            "non_loopback_listener_count": (
                (network.get("counts") or {}).get(
                    "listeners_non_loopback",
                    0,
                )
            ),
        },
        "findings": findings,
        "level": _security_level(findings),
        "interpretation": "Uma ligação Internet normal não prova acesso remoto. Sessões RDP, SMB e outras sessões de utilizador são indicadores mais fortes.",
    }


def run_security_audit() -> dict[str, Any]:
    admins = get_admin_accounts()
    sessions = get_active_user_sessions()
    network = get_network_security_snapshot()
    posture = get_windows_security_posture()
    summary = _security_summary(admins, sessions, network, posture)
    return {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summary,
        "accounts": admins,
        "sessions": sessions,
        "network": network,
        "windows_security": posture,
        "read_only": True,
    }


def format_security_overview(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui concluir a auditoria."

    summary = data.get("summary") or {}
    level_map = {
        "ok": "OK",
        "attention": "ATENÇÃO",
        "critical": "CRÍTICO",
    }
    status = level_map.get(
        str(summary.get("level") or "ok").lower(),
        "OK",
    )
    user = summary.get("current_user") or "utilizador atual"

    lines = [f"SEGURANÇA: {status}"]
    lines.append(
        f"Utilizador: {user} | Administrador: "
        + ("Sim" if summary.get("current_user_admin") else "Não")
    )

    if summary.get("only_current_enabled_admin_detected") is True:
        lines.append("Administradores: apenas o utilizador atual está habilitado.")
    elif summary.get("other_admin_count"):
        lines.append(
            f"Administradores: {summary['other_admin_count']} outro(s) "
            "administrador(es) habilitado(s)/desconhecido(s)."
        )
    else:
        lines.append("Administradores: não foram confirmados outros habilitados.")

    if summary.get("active_remote_access_detected"):
        lines.append(
            "Acesso remoto ATIVO: "
            f"RDP={summary.get('remote_interactive_session_count', 0)}, "
            f"SMB={summary.get('smb_session_count', 0)}."
        )
    else:
        lines.append("Acesso remoto ativo: não detetado.")

    lines.append(
        f"Sessões adicionais: {summary.get('other_session_count', 0)}."
    )
    lines.append(
        "Software de acesso remoto: "
        f"{summary.get('remote_access_software_count', 0)} processo(s)."
    )

    firewall = summary.get("firewall_all_enabled")
    if firewall is True:
        lines.append("Firewall: ativa nos perfis verificados.")
    elif firewall is False:
        lines.append("Firewall: ATENÇÃO — existe pelo menos um perfil desativado.")
    else:
        lines.append("Firewall: estado não confirmado.")

    defender = summary.get("defender_realtime_enabled")
    if defender is True:
        lines.append("Defender: proteção em tempo real ativa.")
    elif defender is False:
        lines.append("Defender: ATENÇÃO — proteção em tempo real desativada.")
    else:
        lines.append("Defender: estado não confirmado.")

    rdp = summary.get("rdp_enabled")
    lines.append(
        "RDP: "
        + (
            "ativo."
            if rdp is True
            else "desativado."
            if rdp is False
            else "não confirmado."
        )
    )

    remote_assistance = summary.get("remote_assistance_enabled")
    if remote_assistance is True:
        lines.append(
            "Assistência Remota: ATIVA "
            "(capacidade disponível; não significa sessão ativa)."
        )
    elif remote_assistance is False:
        lines.append("Assistência Remota: desativada.")

    net = summary.get("network") or {}
    active = net.get("active_interfaces") or []
    if active:
        adapter_text = ", ".join(
            f"{x.get('name')} ({'/'.join(x.get('ipv4') or [])})"
            for x in active
        )
        lines.append(f"Rede ativa: {adapter_text}.")
    lines.append(
        "Rede: "
        f"{net.get('lan_device_count', 0)} equipamento(s) LAN conhecido(s), "
        f"{net.get('non_loopback_connection_count', 0)} ligação(ões) "
        "ESTABLISHED fora de loopback."
    )

    attention = [
        x.get("message")
        for x in summary.get("findings") or []
        if x.get("severity") in {"attention", "critical"}
        and x.get("message")
    ]
    if attention:
        lines.append("Atenção:")
        lines.extend(f"- {message}" for message in attention)

    lines.append("Detalhe técnico: /security scan full")
    return "\n".join(lines)



def _yes_no_unknown(
    value: bool | None,
    yes: str = "Sim",
    no: str = "Não",
) -> str:
    if value is True:
        return yes
    if value is False:
        return no
    return "Desconhecido"


def format_security_full(
    data: dict[str, Any],
) -> str:
    """
    Complete but human-readable audit.

    This intentionally avoids dumping raw JSON. Raw diagnostic data remains
    available via /security scan raw.
    """
    if not data.get("ok"):
        return (
            data.get("message")
            or "Não consegui concluir a auditoria."
        )

    summary = data.get("summary") or {}
    accounts = data.get("accounts") or {}
    sessions = data.get("sessions") or {}
    posture = data.get("windows_security") or {}
    network = data.get("network") or {}
    filtered = network.get("filtered") or {}
    counts = network.get("counts") or {}

    level_map = {
        "ok": "OK",
        "attention": "ATENÇÃO",
        "critical": "CRÍTICO",
    }
    level = level_map.get(
        str(summary.get("level") or "ok").lower(),
        "OK",
    )

    lines = [f"SEGURANÇA DO SISTEMA · {level}"]

    # --------------------------------------------------------------
    # Conta / administradores
    # --------------------------------------------------------------
    current = accounts.get("current_user") or {}
    lines.append("")
    lines.append("CONTA")
    lines.append(
        f"Utilizador: "
        f"{summary.get('current_user') or current.get('name') or 'desconhecido'}"
    )
    lines.append(
        "Administrador: "
        + _yes_no_unknown(
            bool(
                current.get("in_local_administrators_group")
                or current.get("token_is_admin")
            )
        )
    )

    other_admins = (
        accounts.get(
            "other_enabled_or_unknown_admin_principals"
        )
        or []
    )
    if summary.get(
        "only_current_enabled_admin_detected"
    ) is True:
        lines.append(
            "Outros administradores habilitados: 0"
        )
    else:
        lines.append(
            f"Outros administradores habilitados/desconhecidos: "
            f"{len(other_admins)}"
        )

    # --------------------------------------------------------------
    # Sessions / remote access
    # --------------------------------------------------------------
    lines.append("")
    lines.append("SESSÕES")
    user_sessions = sessions.get("sessions") or []
    lines.append(
        f"Sessões Windows: {len(user_sessions)}"
    )
    lines.append(
        f"Sessões remotas: "
        f"{summary.get('remote_interactive_session_count', 0)}"
    )
    lines.append(
        f"Sessões SMB: "
        f"{summary.get('smb_session_count', 0)}"
    )

    if summary.get("active_remote_access_detected"):
        lines.append("Acesso remoto ativo: DETETADO")
    else:
        lines.append(
            "Acesso remoto ativo: não detetado"
        )

    remote_tools = (
        network.get(
            "remote_access_software_running"
        )
        or []
    )
    if remote_tools:
        products = sorted({
            str(row.get("product"))
            for row in remote_tools
            if row.get("product")
        })
        lines.append(
            "Software de acesso remoto: "
            + (
                ", ".join(products)
                if products
                else f"{len(remote_tools)} processo(s)"
            )
        )
    else:
        lines.append(
            "Software de acesso remoto: nenhum detetado"
        )

    # --------------------------------------------------------------
    # Windows security
    # --------------------------------------------------------------
    lines.append("")
    lines.append("PROTEÇÃO")
    lines.append(
        "Firewall: "
        + (
            "ativa"
            if summary.get("firewall_all_enabled") is True
            else "ATENÇÃO"
            if summary.get("firewall_all_enabled") is False
            else "não confirmada"
        )
    )
    defender = summary.get(
        "defender_realtime_enabled"
    )
    lines.append(
        "Defender em tempo real: "
        + (
            "ativo"
            if defender is True
            else "DESATIVADO"
            if defender is False
            else "não confirmado"
        )
    )
    rdp = summary.get("rdp_enabled")
    lines.append(
        "RDP: "
        + (
            "ativo"
            if rdp is True
            else "desativado"
            if rdp is False
            else "não confirmado"
        )
    )
    remote_assistance = summary.get(
        "remote_assistance_enabled"
    )
    lines.append(
        "Assistência Remota: "
        + (
            "ativa"
            if remote_assistance is True
            else "desativada"
            if remote_assistance is False
            else "não confirmada"
        )
    )

    # Defender signature age/date when available.
    defender_raw = posture.get("defender") or {}
    signature = defender_raw.get(
        "antivirus_signature_last_updated"
    )
    if signature:
        lines.append(
            f"Assinaturas Defender: {signature}"
        )

    # --------------------------------------------------------------
    # Network
    # --------------------------------------------------------------
    lines.append("")
    lines.append("REDE")
    interfaces = (
        filtered.get("active_interfaces")
        or summary.get("network", {}).get(
            "active_interfaces",
            [],
        )
        or []
    )
    if interfaces:
        primary = interfaces[0]
        ips = ", ".join(
            primary.get("ipv4") or []
        )
        speed = primary.get("speed_mbps")
        speed_text = (
            f" · {speed} Mbps"
            if speed not in (None, 0)
            else ""
        )
        lines.append(
            f"Ligação principal: "
            f"{primary.get('name') or 'desconhecida'}"
            + (f" · {ips}" if ips else "")
            + speed_text
        )
    else:
        lines.append(
            "Ligação principal: não identificada"
        )

    active_devices = counts.get(
        "lan_devices_active",
        counts.get(
            "lan_devices",
            (summary.get("network") or {}).get(
                "lan_device_count",
                0,
            ),
        ),
    )
    lines.append(
        f"Dispositivos ativos na LAN: "
        f"{int(active_devices or 0)}"
    )
    lines.append(
        f"Ligações públicas ativas: "
        f"{int(counts.get('public_established', (summary.get('network') or {}).get('public_connection_count', 0)) or 0)}"
    )

    # --------------------------------------------------------------
    # Attention items only
    # --------------------------------------------------------------
    attention = [
        item.get("message")
        for item in summary.get("findings") or []
        if (
            item.get("severity")
            in {"attention", "critical"}
            and item.get("message")
        )
    ]
    if attention:
        lines.append("")
        lines.append("ATENÇÃO")
        lines.extend(
            f"- {message}"
            for message in attention
        )

    lines.append("")
    lines.append(
        "JSON bruto: /security scan raw"
    )

    return "\n".join(lines)


def format_network_overview(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui analisar a rede."
    filtered = data.get("filtered") or {}
    counts = data.get("counts") or {}
    remote_tools = data.get("remote_access_software_running") or []
    lines = ["REDE: OK"]
    interfaces = filtered.get("active_interfaces") or []
    if interfaces:
        row = interfaces[0]
        ip = ", ".join(row.get("ipv4") or []) or "IP desconhecido"
        speed = row.get("speed_mbps")
        speed_text = f" · {speed} Mbps" if speed not in (None, 0) else ""
        lines.append(f"{row.get('name') or 'Ligação'} · {ip}{speed_text}")
    else:
        lines[0] = "REDE: ATENÇÃO"
        lines.append("Ligação principal: não identificada.")
    active_devices = int(counts.get("lan_devices_active", counts.get("lan_devices", 0)) or 0)
    public_connections = int(counts.get("public_established", 0) or 0)
    lines.append(f"Dispositivos ativos na rede: {active_devices}")
    lines.append(f"Ligações à Internet: {public_connections}")
    if remote_tools:
        products = sorted({str(row.get("product")) for row in remote_tools if row.get("product")})
        lines[0] = "REDE: ATENÇÃO"
        detail = f" ({', '.join(products)})" if products else ""
        lines.append(f"Acesso remoto: software ativo{detail}.")
    else:
        lines.append("Acesso remoto: não detetado.")
    lines.append("Detalhes: /network devices | /network status full")
    return "\n".join(lines)


def format_network_devices(data: dict[str, Any], include_stale: bool = False) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui analisar os dispositivos."
    filtered = data.get("filtered") or {}
    if include_stale:
        devices = filtered.get("lan_devices") or []
        title = "DISPOSITIVOS LAN CONHECIDOS"
    else:
        devices = filtered.get("active_lan_devices") or []
        title = "DISPOSITIVOS ATIVOS NA LAN"
    lines=[title]
    if not devices:
        lines.append("Nenhum dispositivo encontrado.")
        return "\n".join(lines)
    for row in devices[:20]:
        state=str(row.get("state") or "").lower()
        suffix=f" · {state}" if include_stale and state else ""
        lines.append(f"- {row.get('ip')} · {row.get('mac')}{suffix}")
    if not include_stale:
        lines.append("Todos: /network devices all")
    return "\n".join(lines)
