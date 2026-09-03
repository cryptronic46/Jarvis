from __future__ import annotations

from typing import Any
import json
import subprocess

from jarvis_core.services.user_memory import store
from jarvis_core.core.subprocess_text import decode_subprocess_stream


def get_configured_location() -> dict[str, Any]:
    profile = store().profile()
    home = profile.get("home") or {}
    if not home:
        return {"ok": False, "error": "NO_CONFIGURED_LOCATION", "message": "Não existe uma localização-base configurada."}
    return {
        "ok": True,
        "source": "configured_coordinates",
        "label": home.get("label"),
        "locality": home.get("locality"),
        "municipality": home.get("municipality"),
        "district": home.get("district"),
        "country": home.get("country"),
        "latitude": home.get("latitude"),
        "longitude": home.get("longitude"),
        "accuracy": "configured_place",
    }


_WINDOWS_LOCATION_SCRIPT = r'''
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Device
$watcher = New-Object System.Device.Location.GeoCoordinateWatcher([System.Device.Location.GeoPositionAccuracy]::High)
$started = $watcher.TryStart($false, [TimeSpan]::FromSeconds(5))
if (-not $started) {
    [PSCustomObject]@{ok=$false;error="WINDOWS_LOCATION_UNAVAILABLE";message="O serviço de localização do Windows não respondeu."} | ConvertTo-Json -Compress
    exit 0
}
$coord = $watcher.Position.Location
if ($coord.IsUnknown) {
    [PSCustomObject]@{ok=$false;error="WINDOWS_LOCATION_UNKNOWN";message="O Windows não conseguiu determinar a localização."} | ConvertTo-Json -Compress
    exit 0
}
[PSCustomObject]@{ok=$true;source="windows_location_service";latitude=$coord.Latitude;longitude=$coord.Longitude;accuracy_m=$coord.HorizontalAccuracy;altitude_m=$coord.Altitude} | ConvertTo-Json -Compress
'''


def get_windows_precise_location(timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Fixed read-only Windows Location query; no user/LLM text is interpolated."""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WINDOWS_LOCATION_SCRIPT],
            capture_output=True,
            timeout=max(3.0, min(float(timeout_seconds), 12.0)),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        return {"ok": False, "error": "POWERSHELL_NOT_FOUND", "message": "PowerShell do Windows não foi encontrado."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "WINDOWS_LOCATION_TIMEOUT", "message": "O serviço de localização do Windows demorou demasiado."}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    output = decode_subprocess_stream(completed.stdout).strip()
    if not output:
        return {"ok": False, "error": "WINDOWS_LOCATION_EMPTY", "message": decode_subprocess_stream(completed.stderr).strip() or "O Windows não devolveu coordenadas."}
    try:
        data = json.loads(output.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "WINDOWS_LOCATION_INVALID_JSON", "message": output[-600:]}
    return data if isinstance(data, dict) else {"ok": False, "error": "WINDOWS_LOCATION_INVALID_RESPONSE"}


def get_precise_location() -> dict[str, Any]:
    windows = get_windows_precise_location()
    if windows.get("ok"):
        return windows
    configured = get_configured_location()
    if configured.get("ok"):
        configured["fallback_reason"] = windows.get("error")
        configured["message"] = "O Windows Location não forneceu posição atual; estou a usar a localização-base configurada."
        return configured
    return windows


def get_approximate_location() -> dict[str, Any]:
    """Compatibility alias. No IP geolocation is performed anymore."""
    result = get_configured_location()
    result["compatibility_alias"] = True
    return result
