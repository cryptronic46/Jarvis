from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import platform
import shutil
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream

import psutil


PHYSICAL_DISK_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"
$result = [ordered]@{
    ok = $true
    disks = @()
    recent_system_errors = 0
    recent_application_errors = 0
    last_boot = $null
}
try {
    $result.disks = @(
        Get-PhysicalDisk |
        ForEach-Object {
            [PSCustomObject]@{
                friendly_name = $_.FriendlyName
                media_type = [string]$_.MediaType
                health_status = [string]$_.HealthStatus
                operational_status = [string]$_.OperationalStatus
                size_bytes = [double]$_.Size
            }
        }
    )
} catch {
    $result.disk_error = $_.Exception.Message
}
try {
    $os = Get-CimInstance Win32_OperatingSystem
    if ($null -ne $os.LastBootUpTime) {
        $result.last_boot = $os.LastBootUpTime.ToString("o")
    }
} catch {
    $result.boot_error = $_.Exception.Message
}
$start = (Get-Date).AddHours(-24)
try {
    $result.recent_system_errors = @(
        Get-WinEvent -FilterHashtable @{
            LogName='System'
            Level=1,2
            StartTime=$start
        } -ErrorAction SilentlyContinue
    ).Count
} catch {}
try {
    $result.recent_application_errors = @(
        Get-WinEvent -FilterHashtable @{
            LogName='Application'
            Level=1,2
            StartTime=$start
        } -ErrorAction SilentlyContinue
    ).Count
} catch {}
$result | ConvertTo-Json -Depth 6 -Compress
'''


def _powershell_json(script: str, timeout: float = 10.0) -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"ok": False, "error": "WINDOWS_ONLY"}
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = decode_subprocess_stream(completed.stdout).strip()
        if not raw:
            return {
                "ok": False,
                "error": "EMPTY_OUTPUT",
                "message": decode_subprocess_stream(completed.stderr).strip(),
            }
        data = json.loads(raw.splitlines()[-1])
        return data if isinstance(data, dict) else {"ok": True, "value": data}
    except Exception as exc:
        return {
            "ok": False,
            "error": type(exc).__name__,
            "message": str(exc),
        }


def _gpu() -> dict[str, Any] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        output = subprocess.check_output(
            [
                exe,
                "--query-gpu=name,temperature.gpu,utilization.gpu,"
                "memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            timeout=4,
        )
        output = decode_subprocess_stream(output).strip().splitlines()
        if not output:
            return None
        parts = [x.strip() for x in output[0].split(",")]
        return {
            "name": parts[0],
            "temperature_c": float(parts[1]),
            "utilization_percent": float(parts[2]),
            "memory_used_mb": float(parts[3]),
            "memory_total_mb": float(parts[4]),
        }
    except Exception:
        return None


def get_pc_health() -> dict[str, Any]:
    issues = []
    cpu = psutil.cpu_percent(interval=0.10)
    memory = psutil.virtual_memory()
    volumes = []

    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        free_pct = usage.free / usage.total * 100 if usage.total else 0.0
        row = {
            "mount": part.mountpoint,
            "filesystem": part.fstype,
            "total_gb": round(usage.total / 1024**3, 1),
            "free_gb": round(usage.free / 1024**3, 1),
            "free_percent": round(free_pct, 1),
        }
        volumes.append(row)
        if free_pct < 10:
            issues.append({
                "severity": "attention",
                "code": "LOW_DISK_SPACE",
                "message": (
                    f"Pouco espaço livre em {part.mountpoint}: "
                    f"{free_pct:.1f}%."
                ),
            })

    if memory.percent >= 90:
        issues.append({
            "severity": "attention",
            "code": "HIGH_MEMORY",
            "message": f"RAM em {memory.percent:.0f}%.",
        })

    gpu = _gpu()
    if gpu and gpu.get("temperature_c", 0) >= 85:
        issues.append({
            "severity": "attention",
            "code": "HIGH_GPU_TEMP",
            "message": f"GPU a {gpu['temperature_c']:.0f} °C.",
        })

    windows = _powershell_json(PHYSICAL_DISK_SCRIPT)
    physical_disks = windows.get("disks", []) if windows.get("ok") else []
    for disk in physical_disks:
        if str(disk.get("health_status") or "").lower() not in {"healthy", ""}:
            issues.append({
                "severity": "attention",
                "code": "PHYSICAL_DISK_HEALTH",
                "message": (
                    f"Disco {disk.get('friendly_name')} reporta "
                    f"{disk.get('health_status')}."
                ),
            })

    return {
        "ok": True,
        "sampled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": "attention" if issues else "ok",
        "cpu_percent": round(cpu, 1),
        "memory": {
            "percent": round(memory.percent, 1),
            "used_gb": round(memory.used / 1024**3, 1),
            "total_gb": round(memory.total / 1024**3, 1),
        },
        "volumes": volumes,
        "gpu": gpu,
        "physical_disks": physical_disks,
        "last_boot": windows.get("last_boot"),
        "recent_errors_24h": {
            "system": windows.get("recent_system_errors"),
            "application": windows.get("recent_application_errors"),
        },
        "issues": issues,
    }


def format_pc_health(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui fazer o check-up."

    lines = [
        "PC: " + ("ATENÇÃO" if data.get("overall") == "attention" else "OK"),
        (
            f"CPU: {data.get('cpu_percent')}% · "
            f"RAM: {(data.get('memory') or {}).get('percent')}%"
        ),
    ]
    gpu = data.get("gpu") or {}
    if gpu:
        lines.append(
            f"GPU: {gpu.get('temperature_c')} °C · "
            f"{gpu.get('utilization_percent')}%"
        )
    volumes = data.get("volumes") or []
    if volumes:
        main = volumes[0]
        lines.append(
            f"Disco {main.get('mount')}: {main.get('free_gb')} GB livres "
            f"({main.get('free_percent')}%)"
        )
    physical = data.get("physical_disks") or []
    if physical:
        lines.append(
            "Storage: "
            + ", ".join(
                f"{x.get('friendly_name')}: {x.get('health_status')}"
                for x in physical[:3]
            )
        )
    issues = data.get("issues") or []
    if issues:
        lines.append("Atenção:")
        lines.extend(f"- {x.get('message')}" for x in issues[:5])
    else:
        lines.append("Não encontrei problemas críticos no check-up atual.")
    return "\n".join(lines)
