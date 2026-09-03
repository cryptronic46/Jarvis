from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any
import ipaddress
import json
import platform
import socket
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream

import psutil

from jarvis_core.tools.security_audit import get_network_security_snapshot
from jarvis_core.services.cyber_knowledge import cyber_vault


WINDOWS_ENRICHMENT_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"

function Resolve-ExecutablePath([string]$CommandLine) {
    if (-not $CommandLine) { return $null }
    $expanded = [Environment]::ExpandEnvironmentVariables($CommandLine.Trim())
    if ($expanded.StartsWith('"')) {
        $match = [regex]::Match($expanded, '^"([^"]+)"')
        if ($match.Success) { return $match.Groups[1].Value }
    }
    $match = [regex]::Match(
        $expanded,
        '^(.*?\.exe)(?:\s|$)',
        [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
    )
    if ($match.Success) { return $match.Groups[1].Value.Trim('"') }
    return $null
}

function Get-FileSecurityMeta([string]$Path) {
    $out = [ordered]@{
        path = $Path
        signature_status = $null
        signer_subject = $null
        company = $null
        product = $null
        file_version = $null
    }
    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $out }
    try {
        $sig = Get-AuthenticodeSignature -FilePath $Path
        if ($null -ne $sig) {
            $out.signature_status = [string]$sig.Status
            if ($null -ne $sig.SignerCertificate) {
                $out.signer_subject = [string]$sig.SignerCertificate.Subject
            }
        }
    } catch {}
    try {
        $vi = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($Path)
        $out.company = [string]$vi.CompanyName
        $out.product = [string]$vi.ProductName
        $out.file_version = [string]$vi.FileVersion
    } catch {}
    return $out
}

$result = [ordered]@{
    ok = $true
    processes = @()
    services = @()
    inbound_allow_rules = @()
    system_root = [string]$env:windir
    errors = @()
}

$serviceRows = @()
try {
    $serviceRows = @(
        Get-CimInstance Win32_Service |
        Where-Object { $_.ProcessId -gt 0 } |
        ForEach-Object {
            $exe = Resolve-ExecutablePath ([string]$_.PathName)
            $meta = Get-FileSecurityMeta $exe
            [PSCustomObject]@{
                pid = [int]$_.ProcessId
                name = [string]$_.Name
                display_name = [string]$_.DisplayName
                state = [string]$_.State
                start_mode = [string]$_.StartMode
                path_name = [string]$_.PathName
                executable_path = $meta.path
                signature_status = $meta.signature_status
                signer_subject = $meta.signer_subject
                company = $meta.company
                product = $meta.product
                file_version = $meta.file_version
            }
        }
    )
    $result.services = $serviceRows
} catch {
    $result.errors += "Services: $($_.Exception.Message)"
}

try {
    $pids = @(
        Get-NetTCPConnection -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
        Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess
    ) | Where-Object { $_ -ge 0 } | Sort-Object -Unique

    foreach ($pidValue in $pids) {
        if ($pidValue -eq 0) { continue }
        $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($null -eq $proc) { continue }
        $path = $null
        try { $path = $proc.Path } catch {}
        if (-not $path) {
            try {
                $cimProc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
                if ($null -ne $cimProc -and $cimProc.ExecutablePath) {
                    $path = [string]$cimProc.ExecutablePath
                }
            } catch {}
        }
        if (-not $path) {
            $servicePath = @(
                $serviceRows |
                Where-Object { $_.pid -eq [int]$pidValue -and $_.executable_path } |
                Select-Object -First 1
            )
            if ($servicePath.Count -gt 0) { $path = [string]$servicePath[0].executable_path }
        }
        if (-not $path) {
            $core = @("svchost", "lsass", "wininit", "services", "spoolsv")
            if ($core -contains [string]$proc.ProcessName) {
                $candidate = Join-Path $env:windir ("System32\" + [string]$proc.ProcessName + ".exe")
                if (Test-Path -LiteralPath $candidate) { $path = $candidate }
            }
        }
        $meta = Get-FileSecurityMeta $path
        $result.processes += [PSCustomObject]@{
            pid = [int]$pidValue
            name = [string]$proc.ProcessName
            path = $meta.path
            signature_status = $meta.signature_status
            signer_subject = $meta.signer_subject
            company = $meta.company
            product = $meta.product
            file_version = $meta.file_version
        }
    }
} catch {
    $result.errors += "Processes: $($_.Exception.Message)"
}

try {
    $rules = @(Get-NetFirewallRule -Enabled True -Direction Inbound -Action Allow | Select-Object -First 700)
    foreach ($rule in $rules) {
        $ports = @($rule | Get-NetFirewallPortFilter)
        $apps = @($rule | Get-NetFirewallApplicationFilter)
        $services = @($rule | Get-NetFirewallServiceFilter)
        if (-not $ports) { $ports = @($null) }
        if (-not $apps) { $apps = @($null) }
        if (-not $services) { $services = @($null) }
        foreach ($pf in $ports) {
            $program = $null
            if ($apps -and $null -ne $apps[0]) { $program = [string]$apps[0].Program }
            $svc = $null
            if ($services -and $null -ne $services[0]) { $svc = [string]$services[0].Service }
            $result.inbound_allow_rules += [PSCustomObject]@{
                name = [string]$rule.Name
                display_name = [string]$rule.DisplayName
                display_group = [string]$rule.DisplayGroup
                profile = [string]$rule.Profile
                protocol = (if ($null -ne $pf) { [string]$pf.Protocol } else { $null })
                local_port = (if ($null -ne $pf) { [string]$pf.LocalPort } else { $null })
                remote_port = (if ($null -ne $pf) { [string]$pf.RemotePort } else { $null })
                program = $program
                service = $svc
            }
        }
    }
} catch {
    $result.errors += "Firewall: $($_.Exception.Message)"
}

$result | ConvertTo-Json -Depth 8 -Compress
'''


WINDOWS_CORE_PROCESSES = {
    "svchost.exe",
    "lsass.exe",
    "wininit.exe",
    "services.exe",
    "spoolsv.exe",
    "msmpeng.exe",
}

KNOWN_EXPECTED_PROCESSES = {
    "system",
    "svchost.exe",
    "services.exe",
    "spoolsv.exe",
    "wininit.exe",
    "lsass.exe",
    "steam.exe",
    "steamwebhelper.exe",
    "chrome.exe",
    "msedge.exe",
    "brave.exe",
    "firefox.exe",
    "discord.exe",
    "spotify.exe",
    "onedrive.exe",
    "nvcontainer.exe",
    "nvidia app.exe",
    "nvapp.exe",
    "ollama.exe",
    "python.exe",
    "pythonw.exe",
}

COMMON_OUTBOUND_PORTS = {
    53, 80, 123, 443, 5228, 5229, 5230, 8080, 8443,
}

WINDOWS_SYSTEM_PORTS = {
    135, 139, 445,
}


def _windows() -> bool:
    return platform.system().lower() == "windows"


def _run_enrichment() -> dict[str, Any]:
    if not _windows():
        return {
            "ok": False,
            "error": "WINDOWS_ONLY",
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }

    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                WINDOWS_ENRICHMENT_SCRIPT,
            ],
            capture_output=True,
            timeout=35,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "POWERSHELL_NOT_FOUND",
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": "POWERSHELL_TIMEOUT",
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }

    raw = decode_subprocess_stream(completed.stdout).strip()
    if not raw:
        return {
            "ok": False,
            "error": "POWERSHELL_EMPTY_OUTPUT",
            "message": decode_subprocess_stream(completed.stderr).strip(),
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }

    try:
        data = json.loads(raw.splitlines()[-1])
        if isinstance(data, dict):
            return data
    except Exception as exc:
        return {
            "ok": False,
            "error": "POWERSHELL_INVALID_JSON",
            "message": f"{type(exc).__name__}: {exc}",
            "processes": [],
            "services": [],
            "inbound_allow_rules": [],
        }

    return {
        "ok": False,
        "error": "INVALID_ENRICHMENT_RESULT",
        "processes": [],
        "services": [],
        "inbound_allow_rules": [],
    }


def _endpoint(value: Any) -> dict[str, Any] | None:
    if not value:
        return None

    try:
        ip = str(value.ip)
        port = int(value.port)
    except AttributeError:
        try:
            ip = str(value[0])
            port = int(value[1])
        except Exception:
            return None

    return {
        "ip": ip,
        "port": port,
        "scope": _scope(ip),
    }


def _scope(ip: str) -> str:
    try:
        obj = ipaddress.ip_address(str(ip).split("%")[0])
    except Exception:
        return "unknown"

    if obj.is_loopback:
        return "loopback"
    if obj.is_private:
        return "private"
    if obj.is_link_local:
        return "link-local"
    if obj.is_multicast:
        return "multicast"
    if obj.is_unspecified:
        return "unspecified"
    return "public"


def _normalize_process_name(name: Any) -> str:
    value = str(name or "").strip().lower()
    if value and not value.endswith(".exe") and value not in {"system"}:
        value += ".exe"
    return value


def _base_process_info(pid: int | None) -> dict[str, Any]:
    if pid in {None, 0}:
        return {
            "pid": pid,
            "name": None,
            "path": None,
            "username": None,
            "create_time": None,
        }

    if pid == 4:
        return {
            "pid": 4,
            "name": "System",
            "path": None,
            "username": "NT AUTHORITY\\SYSTEM",
            "create_time": None,
        }

    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            try:
                path = proc.exe()
            except Exception:
                path = None
            try:
                username = proc.username()
            except Exception:
                username = None
            try:
                create_time = datetime.fromtimestamp(
                    proc.create_time()
                ).astimezone().isoformat(timespec="seconds")
            except Exception:
                create_time = None
            try:
                name = proc.name()
            except Exception:
                name = None
        return {
            "pid": pid,
            "name": name,
            "path": path,
            "username": username,
            "create_time": create_time,
        }
    except Exception:
        return {
            "pid": pid,
            "name": None,
            "path": None,
            "username": None,
            "create_time": None,
        }


def _collect_connections() -> tuple[list[dict[str, Any]], str | None]:
    rows = []
    error = None

    try:
        connections = psutil.net_connections(kind="inet")
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"

    for conn in connections:
        local = _endpoint(conn.laddr)
        remote = _endpoint(conn.raddr)
        status = str(conn.status or "").upper()
        sock_type = (
            "TCP"
            if conn.type == socket.SOCK_STREAM
            else "UDP"
            if conn.type == socket.SOCK_DGRAM
            else str(conn.type)
        )

        rows.append({
            "protocol": sock_type,
            "status": status,
            "pid": conn.pid,
            "local": local,
            "remote": remote,
        })

    return rows, error


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    seen = set()

    for row in rows:
        local = row.get("local") or {}
        remote = row.get("remote") or {}
        key = (
            row.get("protocol"),
            row.get("status"),
            row.get("pid"),
            local.get("ip"),
            local.get("port"),
            remote.get("ip"),
            remote.get("port"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)

    return output


def _service_map(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            pid = int(row.get("pid"))
        except Exception:
            continue
        result[pid].append(row)
    return result


def _process_map(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result = {}
    for row in rows:
        try:
            pid = int(row.get("pid"))
        except Exception:
            continue
        result[pid] = row
    return result


def _port_matches(rule_value: Any, port: int | None) -> bool:
    if port is None:
        return False

    value = str(rule_value or "").strip()
    if not value:
        return False

    low = value.lower()
    if low in {"any", "*"}:
        return True

    for piece in value.replace(" ", "").split(","):
        if not piece:
            continue
        if "-" in piece:
            left, right = piece.split("-", 1)
            try:
                if int(left) <= port <= int(right):
                    return True
            except Exception:
                continue
        else:
            try:
                if int(piece) == port:
                    return True
            except Exception:
                continue

    return False


def _protocol_matches(rule_value: Any, protocol: str) -> bool:
    value = str(rule_value or "").strip().lower()
    if not value or value in {"any", "256"}:
        return True

    protocol = str(protocol or "").upper()
    if protocol == "TCP":
        return value in {"tcp", "6"}
    if protocol == "UDP":
        return value in {"udp", "17"}
    return False


def _program_matches(rule_program: Any, process_path: Any) -> bool:
    rule = str(rule_program or "").strip().lower()
    path = str(process_path or "").strip().lower()

    if not rule or rule in {"any", "*"}:
        return True
    if not path:
        return False

    return rule.replace("/", "\\") == path.replace("/", "\\")


def _matching_firewall_rules(
    row: dict[str, Any],
    rules: list[dict[str, Any]],
    process_path: str | None,
) -> list[dict[str, Any]]:
    local = row.get("local") or {}
    port = local.get("port")
    protocol = str(row.get("protocol") or "")

    matched = []
    for rule in rules:
        if not _protocol_matches(rule.get("protocol"), protocol):
            continue
        if not _port_matches(rule.get("local_port"), port):
            continue
        if not _program_matches(rule.get("program"), process_path):
            continue
        matched.append(rule)

    return matched[:8]


def _is_microsoft(meta: dict[str, Any]) -> bool:
    joined = " ".join([
        str(meta.get("signer_subject") or ""),
        str(meta.get("company") or ""),
        str(meta.get("product") or ""),
    ]).lower()
    return "microsoft" in joined


def _signed_valid(meta: dict[str, Any]) -> bool:
    return str(meta.get("signature_status") or "").lower() == "valid"


def _service_process_fallback(services: list[dict[str, Any]]) -> dict[str, Any]:
    for row in services:
        path = row.get("executable_path")
        if path:
            return {
                "path": path,
                "signature_status": row.get("signature_status"),
                "signer_subject": row.get("signer_subject"),
                "company": row.get("company"),
                "product": row.get("product"),
                "file_version": row.get("file_version"),
            }
    return {}


def _canonical_windows_path(path: Any) -> bool:
    value = str(path or "").replace("/", "\\").lower()
    return (
        "\\windows\\system32\\" in value
        or "\\windows\\syswow64\\" in value
        or "\\programdata\\microsoft\\windows defender\\" in value
    )


def _group_logical_listeners(listeners: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in listeners:
        local = row.get("local") or {}
        process = row.get("process") or {}
        key = (row.get("protocol"), row.get("pid"), local.get("port"), str(process.get("name") or ""))
        if key not in groups:
            copy = dict(row)
            copy["bindings"] = []
            copy["raw_count"] = 0
            groups[key] = copy
        groups[key]["bindings"].append({"ip": local.get("ip"), "scope": local.get("scope")})
        groups[key]["raw_count"] += 1
    output = list(groups.values())
    for row in output:
        bindings = row.get("bindings") or []
        row["dual_stack"] = (
            any(":" in str(x.get("ip") or "") for x in bindings)
            and any("." in str(x.get("ip") or "") for x in bindings)
        )
    return output


def _classification(
    *,
    process: dict[str, Any],
    meta: dict[str, Any],
    row: dict[str, Any],
    firewall_rules: list[dict[str, Any]],
    kind: str,
) -> tuple[str, str, list[str]]:
    reasons = []
    name = _normalize_process_name(meta.get("name") or process.get("name"))
    pid = process.get("pid")
    valid = _signed_valid(meta)
    microsoft = _is_microsoft(meta)
    path = meta.get("path") or process.get("path")

    if kind == "connection" and pid in {None, 0}:
        reasons.append("processo terminou ou ownership ficou indisponível entre snapshots")
        return "transient", "low", reasons

    if pid == 4 or name == "system":
        reasons.append("processo do sistema Windows")
        return "expected", "low", reasons

    if microsoft and valid:
        reasons.append("assinatura Microsoft válida")
        if kind == "listener" and firewall_rules:
            reasons.append("existe regra inbound allow correspondente")
        return "expected", "low", reasons

    if name in WINDOWS_CORE_PROCESSES and _canonical_windows_path(path):
        if valid:
            reasons.append("processo Windows core em caminho canónico com assinatura válida")
            return "expected", "low", reasons
        reasons.append("identidade Windows core e caminho canónico confirmados; assinatura indisponível")
        return "observed", "low", reasons

    if name in KNOWN_EXPECTED_PROCESSES and valid:
        reasons.append("aplicação conhecida com assinatura válida")
        return "expected", "low", reasons

    if kind == "connection":
        remote = row.get("remote") or {}
        if valid and remote.get("port") in COMMON_OUTBOUND_PORTS:
            reasons.append("processo assinado numa porta outbound comum")
            return "expected", "low", reasons

    sig_state = str(meta.get("signature_status") or "").lower()
    if sig_state in {"notsigned", "hashmismatch", "nottrusted", "unknownerror"}:
        reasons.append("executável sem assinatura válida/fiável")
        return "review", "moderate", reasons

    if kind == "listener":
        local = row.get("local") or {}
        if local.get("scope") == "unspecified":
            reasons.append("listener ligado a todas as interfaces")
            if firewall_rules:
                reasons.append("regra inbound allow correspondente")
                return "review", "moderate", reasons

    if path:
        reasons.append("caminho do executável confirmado, mas assinatura/classificação não concluída")
        return "observed", "low", reasons

    reasons.append("informação insuficiente para classificação")
    return "unknown", "unknown", reasons


def _enrich_rows(
    rows: list[dict[str, Any]],
    enrichment: dict[str, Any],
    kind: str,
) -> list[dict[str, Any]]:
    proc_map = _process_map(
        enrichment.get("processes") or []
    )
    svc_map = _service_map(
        enrichment.get("services") or []
    )
    rules = enrichment.get(
        "inbound_allow_rules"
    ) or []

    output = []
    for row in rows:
        pid = row.get("pid")
        process = _base_process_info(pid)

        try:
            pid_int = int(pid) if pid is not None else None
        except Exception:
            pid_int = None

        meta = (
            proc_map.get(pid_int, {})
            if pid_int is not None
            else {}
        )

        service_rows = svc_map.get(pid_int, []) if pid_int is not None else []
        fallback = _service_process_fallback(service_rows)

        merged = {
            **process,
            **{key: value for key, value in fallback.items() if value not in {None, ""}},
            **{key: value for key, value in meta.items() if value not in {None, ""}},
        }

        firewall = (
            _matching_firewall_rules(
                row,
                rules,
                merged.get("path"),
            )
            if kind == "listener"
            else []
        )

        classification, severity, reasons = _classification(
            process=process,
            meta=merged,
            row=row,
            firewall_rules=firewall,
            kind=kind,
        )

        output.append({
            **row,
            "process": merged,
            "services": service_rows,
            "signature": {
                "status": merged.get(
                    "signature_status"
                ),
                "signer": merged.get(
                    "signer_subject"
                ),
                "company": merged.get("company"),
                "product": merged.get("product"),
                "file_version": merged.get(
                    "file_version"
                ),
            },
            "firewall": {
                "matching_inbound_allow_rules": firewall,
                "confirmed_allow_rule": bool(firewall),
            },
            "classification": classification,
            "severity": severity,
            "reasons": reasons,
        })

    return output


def _knowledge_refs(
    listeners: list[dict[str, Any]],
    connections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    vault = cyber_vault()
    queries = []

    if any(
        int((row.get("local") or {}).get("port") or 0) == 445
        for row in listeners
    ):
        queries.append(
            "SMB Windows lateral movement network shares"
        )

    if any(
        row.get("classification") == "review"
        for row in listeners
    ):
        queries.append(
            "network services listening ports firewall attack surface"
        )

    if any(
        row.get("classification") == "review"
        for row in connections
    ):
        queries.append(
            "network connections processes incident investigation"
        )

    queries += [
        "Windows Firewall network protection security controls",
        "network services listening ports firewall attack surface",
    ]

    output = []
    seen = set()
    for query in queries[:6]:
        result = vault.search(query, limit=3)
        for row in result.get("results") or []:
            key = (
                row.get("source_id"),
                row.get("external_id"),
                row.get("title"),
            )
            if key in seen:
                continue
            seen.add(key)
            output.append({
                "title": row.get("title"),
                "publisher": row.get("publisher"),
                "external_id": row.get("external_id"),
                "source_id": row.get("source_id"),
                "trust": row.get("trust"),
                "url": row.get("url"),
            })

    return output[:12]


def inspect_network_deep(
    detail: str = "standard",
) -> dict[str, Any]:
    detail = str(detail or "standard").lower().strip()
    if detail not in {"standard", "full", "raw"}:
        detail = "standard"

    base = get_network_security_snapshot(
        connection_limit=200
    )
    rows, connection_error = _collect_connections()
    rows = _dedupe(rows)

    listeners = [
        row for row in rows
        if row.get("status") == "LISTEN"
        and (row.get("local") or {}).get(
            "scope"
        ) != "loopback"
    ]

    public_connections = [
        row for row in rows
        if row.get("remote")
        and (row.get("remote") or {}).get(
            "scope"
        ) == "public"
    ]

    enrichment = _run_enrichment()

    listeners = _enrich_rows(
        listeners,
        enrichment,
        "listener",
    )
    public_connections = _enrich_rows(
        public_connections,
        enrichment,
        "connection",
    )

    rank = {
        "review": 0,
        "unknown": 1,
        "observed": 2,
        "transient": 3,
        "expected": 4,
    }

    listeners.sort(
        key=lambda row: (
            rank.get(row.get("classification"), 9),
            int((row.get("local") or {}).get("port") or 0),
        )
    )
    public_connections.sort(
        key=lambda row: (
            rank.get(row.get("classification"), 9),
            str((row.get("process") or {}).get("name") or ""),
            int((row.get("remote") or {}).get("port") or 0),
        )
    )

    logical_listeners = _group_logical_listeners(listeners)

    all_rows = listeners + public_connections
    counts = Counter(
        row.get("classification")
        for row in all_rows
    )

    review_items = [
        row
        for row in all_rows
        if row.get("classification") == "review"
    ]
    unknown_items = [
        row
        for row in all_rows
        if row.get("classification") == "unknown"
    ]

    references = _knowledge_refs(
        listeners,
        public_connections,
    )

    result = {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "mode": detail,
        "summary": {
            "listeners": len(listeners),
            "logical_listeners": len(logical_listeners),
            "public_connections": len(public_connections),
            "expected": int(counts.get("expected", 0)),
            "observed": int(counts.get("observed", 0)),
            "transient": int(counts.get("transient", 0)),
            "review": int(counts.get("review", 0)),
            "unknown": int(counts.get("unknown", 0)),
            "firewall_rules_collected": len(
                enrichment.get(
                    "inbound_allow_rules"
                ) or []
            ),
            "processes_enriched": len(
                enrichment.get("processes") or []
            ),
            "services_enriched": len(
                enrichment.get("services") or []
            ),
        },
        "priority_review": review_items[:12],
        "unknown_items": unknown_items[:12],
        "listeners": listeners,
        "logical_listeners": logical_listeners,
        "public_connections": public_connections,
        "knowledge_references": references,
        "collector_states": {
            "base_network_snapshot": bool(
                base.get("ok")
            ),
            "psutil_connections": connection_error is None,
            "windows_enrichment": bool(
                enrichment.get("ok")
            ),
        },
        "limitations": [
            "A classificação 'expected' significa consistente com sinais locais conhecidos; não é uma garantia absoluta de benignidade.",
            "Uma assinatura Authenticode válida prova identidade/integridade do ficheiro assinado, não que todo o comportamento do processo seja seguro.",
            "A associação a regras de Firewall é conservadora e só é marcada como confirmada quando programa/protocolo/porta correspondem.",
            "Sem reputação externa de IPs nesta versão; os destinos remotos são avaliados apenas por contexto local.",
            "Processos protegidos são resolvidos por caminho CIM/serviço quando possível; se a assinatura continuar inacessível ficam OBSERVED, não são assumidos como seguros.",
            "PID 0 em ligações transitórias significa ownership indisponível entre snapshots e é classificado TRANSIENT.",
            "Bindings IPv4/IPv6 do mesmo PID/porta são agrupados como um listener lógico no relatório full.",
        ],
        "read_only": True,
    }

    if detail in {"full", "raw"}:
        result["enrichment_errors"] = (
            enrichment.get("errors") or []
        )
        result["base_network_counts"] = (
            base.get("counts") or {}
        )

    if detail == "raw":
        result["raw_base_network"] = base
        result["raw_enrichment"] = enrichment

    return result


def _short_process(row: dict[str, Any]) -> str:
    process = row.get("process") or {}
    name = (
        process.get("name")
        or f"PID {row.get('pid')}"
    )
    return str(name)


def _signature_label(row: dict[str, Any]) -> str:
    sig = row.get("signature") or {}
    status = sig.get("status")
    company = sig.get("company")
    if status and company:
        return f"{status} · {company}"
    return str(status or company or "não confirmada")


def format_deep_network_inspection(
    data: dict[str, Any],
    *,
    full: bool = False,
) -> str:
    if not data.get("ok"):
        return (
            data.get("message")
            or "Não consegui concluir a inspeção profunda da rede."
        )

    summary = data.get("summary") or {}
    priorities = data.get("priority_review") or []
    unknown = data.get("unknown_items") or []

    lines = [
        "JARVIS — DEEP SECURITY INSPECTION",
        (
            f"Listeners: {summary.get('listeners',0)} raw / "
            f"{summary.get('logical_listeners',0)} lógicos · "
            f"Ligações públicas: {summary.get('public_connections',0)}"
        ),
        (
            f"Esperado: {summary.get('expected',0)} · "
            f"Observado: {summary.get('observed',0)} · "
            f"Transitório: {summary.get('transient',0)} · "
            f"Rever: {summary.get('review',0)} · "
            f"Desconhecido: {summary.get('unknown',0)}"
        ),
        "",
        "PRIORIDADE DE REVISÃO",
    ]

    if not priorities:
        lines.append(
            "Nenhum listener/ligação foi classificado automaticamente como prioridade."
        )
    else:
        for i, row in enumerate(priorities[:12], start=1):
            kind = (
                "LISTEN"
                if row.get("status") == "LISTEN"
                else "CONEXÃO"
            )
            local = row.get("local") or {}
            remote = row.get("remote") or {}
            target = (
                f"{local.get('ip')}:{local.get('port')}"
                if kind == "LISTEN"
                else
                f"{remote.get('ip')}:{remote.get('port')}"
            )
            lines.append(
                f"{i}. {kind} · {_short_process(row)} · {target}"
            )
            lines.append(
                f"   Assinatura: {_signature_label(row)}"
            )
            if row.get("reasons"):
                lines.append(
                    "   Motivo: "
                    + "; ".join(row["reasons"])
                )

    if unknown:
        lines += ["", "NÃO CONFIRMADO"]
        for row in unknown[:8]:
            local = row.get("local") or {}
            remote = row.get("remote") or {}
            endpoint = remote or local
            lines.append(
                f"- {_short_process(row)} · "
                f"{endpoint.get('ip')}:{endpoint.get('port')} · "
                + "; ".join(row.get("reasons") or [])
            )

    if full:
        lines += ["", "LISTENERS"]
        for row in (data.get("logical_listeners") or data.get("listeners") or [])[:40]:
            local = row.get("local") or {}
            fw = row.get("firewall") or {}
            services = row.get("services") or []
            svc = (
                ", ".join(
                    str(x.get("name"))
                    for x in services[:3]
                    if x.get("name")
                )
                or "-"
            )
            binding_text = (
                " / ".join(str(x.get("ip")) for x in row.get("bindings") or [])
                if row.get("bindings") else str(local.get("ip"))
            )
            lines.append(
                f"- {row.get('classification').upper()} · "
                f"{_short_process(row)} · "
                f"{row.get('protocol')} "
                f"{binding_text}:{local.get('port')} · "
                f"PID {row.get('pid')} · "
                f"serviço {svc} · "
                f"firewall allow {'SIM' if fw.get('confirmed_allow_rule') else 'não confirmado'}"
            )
            lines.append(
                f"  Assinatura: {_signature_label(row)}"
            )

        lines += ["", "LIGAÇÕES PÚBLICAS"]
        for row in (
            data.get("public_connections") or []
        )[:40]:
            remote = row.get("remote") or {}
            local = row.get("local") or {}
            lines.append(
                f"- {row.get('classification').upper()} · "
                f"{_short_process(row)} · "
                f"{local.get('ip')}:{local.get('port')} → "
                f"{remote.get('ip')}:{remote.get('port')} · "
                f"PID {row.get('pid')}"
            )
            lines.append(
                f"  Assinatura: {_signature_label(row)}"
            )

    refs = data.get("knowledge_references") or []
    if refs:
        lines += ["", "CONHECIMENTO CORRELACIONADO"]
        for row in refs[:8]:
            source = (
                row.get("publisher")
                or row.get("source_id")
                or "Fonte"
            )
            ext = row.get("external_id")
            suffix = (
                f" · {ext}"
                if ext and ext != "root"
                else ""
            )
            lines.append(
                f"- {source}{suffix}: {row.get('title')}"
            )

    if full:
        lines += ["", "LIMITAÇÕES"]
        for item in data.get("limitations") or []:
            lines.append(f"- {item}")

    lines.append(
        "Detalhe: /cyber inspect network full · "
        "JSON técnico: /cyber inspect network raw"
    )
    return "\n".join(lines)
