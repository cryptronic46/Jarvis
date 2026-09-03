from __future__ import annotations

from datetime import datetime
import platform
import shutil
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream
import winreg
from typing import Any
import psutil


def _bytes_to_gib(value: int | float) -> float:
    return round(float(value) / (1024 ** 3), 2)


def _number_or_text(value: str) -> int | float | str:
    try:
        n = float(value)
        return int(n) if n.is_integer() else n
    except ValueError:
        return value


def get_cpu_name() -> str:
    if platform.system() == "Windows":
        try:
            path = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or "Unknown"


def get_current_time() -> dict[str, Any]:
    now = datetime.now().astimezone()
    return {"datetime": now.isoformat(timespec="seconds"), "timezone": str(now.tzinfo)}


def read_gpu_status() -> list[dict[str, Any]]:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return []

    query = (
        "name,driver_version,temperature.gpu,utilization.gpu,"
        "memory.used,memory.total,power.draw"
    )
    cmd = [
        nvidia_smi,
        f"--query-gpu={query}",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            return []

        sampled_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        gpus = []
        for line in decode_subprocess_stream(completed.stdout).splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 7:
                continue
            name, driver, temp, util, mem_used, mem_total, power = parts
            gpus.append(
                {
                    "sampled_at": sampled_at,
                    "name": name,
                    "driver_version": driver,
                    "temperature_c": _number_or_text(temp),
                    "utilization_percent": _number_or_text(util),
                    "memory_used_mib": _number_or_text(mem_used),
                    "memory_total_mib": _number_or_text(mem_total),
                    "power_w": _number_or_text(power),
                }
            )
        return gpus
    except (OSError, subprocess.SubprocessError):
        return []


def get_system_status() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()

    disks = []
    seen = set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        disks.append(
            {
                "mount": part.mountpoint,
                "filesystem": part.fstype,
                "total_gib": _bytes_to_gib(usage.total),
                "used_gib": _bytes_to_gib(usage.used),
                "free_gib": _bytes_to_gib(usage.free),
                "used_percent": usage.percent,
            }
        )

    boot_ts = float(psutil.boot_time())
    now_ts = datetime.now().timestamp()
    uptime_seconds = max(0, int(now_ts - boot_ts))
    return {
        "sampled_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "boot_time": datetime.fromtimestamp(boot_ts).astimezone().isoformat(timespec="seconds"),
        "uptime_seconds": uptime_seconds,
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "cpu": {
            "model": get_cpu_name(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "usage_percent": psutil.cpu_percent(interval=0.15),
            "frequency_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
        },
        "memory": {
            "total_gib": _bytes_to_gib(memory.total),
            "used_gib": _bytes_to_gib(memory.used),
            "available_gib": _bytes_to_gib(memory.available),
            "used_percent": memory.percent,
        },
        "disks": disks,
        "gpus": read_gpu_status(),
    }


def list_top_processes(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 25))
    rows = []
    for proc in psutil.process_iter(attrs=["pid", "name", "memory_info", "cpu_percent"]):
        try:
            info = proc.info
            mem = info.get("memory_info")
            rows.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name") or "Unknown",
                    "memory_mib": round(mem.rss / (1024 ** 2), 1) if mem else 0,
                    "cpu_percent": info.get("cpu_percent") or 0,
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    rows.sort(key=lambda x: x["memory_mib"], reverse=True)
    return rows[:limit]
