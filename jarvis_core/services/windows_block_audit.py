from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
import json
import os
import platform
import re
import subprocess
from urllib import request as urlrequest

import sys




def _decode_subprocess_stream(value: Any) -> str:
    """Stdlib-only boundary decoder for the preflight security auditor."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return str(value)
    raw = bytes(value)
    for encoding in ("utf-8-sig", "utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


AUDIT_EXTENSIONS = {
    ".dll", ".pyd", ".exe", ".py", ".ps1", ".bat", ".cmd",
}
BINARY_EXTENSIONS = {".dll", ".pyd", ".exe"}
EXCLUDED_DIRS = {
    "__pycache__", ".git", ".cache", "logs", "memory", "knowledge",
}
ZONE_LABELS = {
    0: "LocalMachine", 1: "LocalIntranet", 2: "Trusted",
    3: "Internet", 4: "Restricted",
}
CONFIRMED_BLOCK_EVENT_IDS = {
    3077: "AppControl/SmartAppControl",
    8004: "AppLocker EXE/DLL",
    8007: "AppLocker MSI/Script",
}
INTEGRITY_EVENT_IDS = {
    3004: "CodeIntegrity invalid signature/integrity",
    3033: "CodeIntegrity signature policy",
}
SMART_APP_CONTROL_POLICY_ID = "{0283ac0f-fff1-49ae-ada1-8a933130cad6}"
SMART_APP_CONTROL_POLICY_NAME = "VerifiedAndReputableDesktop"

# Startup acceleration: a recent clean full audit may be reused for a short
# window when all release/runtime/native-file metadata signals are unchanged.
# This avoids re-importing the full native voice/STT stack and re-querying
# Windows event logs on every quick JARVIS restart. The full /security audit
# remains uncached and authoritative.
STARTUP_CACHE_SCHEMA = 1
STARTUP_CACHE_TTL_SECONDS = 600.0
STARTUP_CACHE_MAX_TTL_SECONDS = 1800.0
STARTUP_CACHE_NAME = "windows_block_startup_cache.json"


POWERSHELL_BLOCK_EVENT_SCRIPT = r'''
$ErrorActionPreference = "SilentlyContinue"
$Root = [Environment]::GetEnvironmentVariable("JARVIS_BLOCK_AUDIT_ROOT")
$DaysRaw = [Environment]::GetEnvironmentVariable("JARVIS_BLOCK_AUDIT_DAYS")
$Days = 14
if ($DaysRaw) { try { $Days = [int]$DaysRaw } catch {} }
if ($Days -lt 1) { $Days = 1 }
if ($Days -gt 90) { $Days = 90 }
$Since = (Get-Date).AddDays(-$Days)
$RootRelative = ""
if ($Root) {
    $RootRelative = ($Root -replace '^[A-Za-z]:', '').TrimStart('\')
}
$RootDeviceNeedle = $(if ($RootRelative) { "\" + $RootRelative + "\" } else { "" })
$Rows = @()
$Logs = @()
$Specs = @(
    @{ LogName = "Microsoft-Windows-CodeIntegrity/Operational"; Id = @(3004, 3033, 3077) },
    @{ LogName = "Microsoft-Windows-AppLocker/EXE and DLL"; Id = @(8004) },
    @{ LogName = "Microsoft-Windows-AppLocker/MSI and Script"; Id = @(8007) }
)
foreach ($Spec in $Specs) {
    $LogName = [string]$Spec.LogName
    try {
        $Events = @(Get-WinEvent -FilterHashtable @{ LogName=$LogName; Id=$Spec.Id; StartTime=$Since } -ErrorAction Stop | Select-Object -First 300)
        $Logs += [PSCustomObject]@{ log=$LogName; ok=$true; count=$Events.Count; error=$null }
        foreach ($Event in $Events) {
            $Properties = @($Event.Properties | ForEach-Object { if ($null -eq $_.Value) { "" } else { [string]$_.Value } })
            $Message = ""
            try { $Message = [string]$Event.Message } catch {}
            $Combined = (($Properties -join "`n") + "`n" + $Message)
            if ($Root) {
                $MatchesDosPath = $Combined.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
                $MatchesDevicePath = $RootDeviceNeedle -and ($Combined.IndexOf($RootDeviceNeedle, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
                if (-not $MatchesDosPath -and -not $MatchesDevicePath) { continue }
            }
            $Rows += [PSCustomObject]@{
                id = [int]$Event.Id
                log = $LogName
                time_created = $(if ($Event.TimeCreated) { $Event.TimeCreated.ToUniversalTime().ToString("o") } else { $null })
                properties = $Properties
                message = $Message
            }
        }
    }
    catch {
        $Logs += [PSCustomObject]@{ log=$LogName; ok=$false; count=0; error=[string]$_.Exception.Message }
    }
}
[PSCustomObject]@{ ok=$true; events=$Rows; logs=$Logs } | ConvertTo-Json -Depth 7 -Compress
'''


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_zone_identifier(content: str) -> dict[str, Any] | None:
    values: dict[str, str] = {}
    for raw_line in str(content or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    raw_zone = values.get("ZoneId")
    if raw_zone is None:
        return None
    try:
        zone_id = int(raw_zone)
    except ValueError:
        return None
    return {
        "zone_id": zone_id,
        "zone": ZONE_LABELS.get(zone_id, f"Zone{zone_id}"),
        "host_url": values.get("HostUrl"),
        "referrer_url": values.get("ReferrerUrl"),
        "currently_marked_from_internet": zone_id in {3, 4},
    }


def read_zone_identifier(path: str | Path) -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    ads_path = str(Path(path)) + ":Zone.Identifier"
    try:
        with open(ads_path, "r", encoding="utf-8", errors="replace") as stream:
            content = stream.read(8192)
    except OSError:
        return None
    return parse_zone_identifier(content)


def _candidate_allowed(path: Path, root: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in AUDIT_EXTENSIONS:
        return False
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    lowered_parts = {part.lower() for part in relative.parts[:-1]}
    if lowered_parts & EXCLUDED_DIRS:
        return False
    if ".venv" in lowered_parts and suffix == ".py":
        return False
    return True


def iter_candidate_files(root: str | Path, *, max_files: int = 20000):
    base = Path(root).resolve()
    count = 0
    for current, dirs, files in os.walk(base):
        current_path = Path(current)
        dirs[:] = [name for name in dirs if name.lower() not in EXCLUDED_DIRS]
        for name in files:
            path = current_path / name
            if not _candidate_allowed(path, base):
                continue
            yield path
            count += 1
            if count >= max_files:
                return


def _scan_motw(root: Path, *, max_files: int) -> dict[str, Any]:
    scanned = 0
    marked: list[dict[str, Any]] = []
    extension_counts: dict[str, int] = {}
    for path in iter_candidate_files(root, max_files=max_files):
        scanned += 1
        suffix = path.suffix.lower()
        extension_counts[suffix] = extension_counts.get(suffix, 0) + 1
        zone = read_zone_identifier(path)
        if not zone or not zone.get("currently_marked_from_internet"):
            continue
        try:
            display_path = str(path.relative_to(root))
        except ValueError:
            display_path = str(path)
        marked.append({
            "path": str(path),
            "relative_path": display_path,
            "extension": suffix,
            "binary": suffix in BINARY_EXTENSIONS,
            **zone,
        })
    return {
        "ok": True,
        "scanned_files": scanned,
        "extension_counts": extension_counts,
        "marked": marked,
        "truncated": scanned >= max_files,
    }


def classify_windows_event(event_id: int) -> tuple[str, str]:
    eid = int(event_id)
    if eid in CONFIRMED_BLOCK_EVENT_IDS:
        return "confirmed_block", CONFIRMED_BLOCK_EVENT_IDS[eid]
    if eid in INTEGRITY_EVENT_IDS:
        return "integrity_issue", INTEGRITY_EVENT_IDS[eid]
    return "other", "Windows application control event"


def _extract_policy_id(event: dict[str, Any]) -> str | None:
    values = [str(value or "") for value in event.get("properties") or []]
    values.append(str(event.get("message") or ""))
    pattern = re.compile(r"Policy\s*ID\s*:\s*(\{[0-9a-fA-F-]{36}\})", re.IGNORECASE)
    for text in values:
        match = pattern.search(text)
        if match:
            return match.group(1).lower()
    return None


def _is_pyav_native_path(path: str) -> bool:
    normalized = str(path or "").replace("/", "\\").lower()
    return (
        "\\.venv\\lib\\site-packages\\av\\" in normalized
        and normalized.endswith((".pyd", ".dll"))
    )


def _annotate_block_event(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    policy_id = str(output.get("policy_id") or "").lower()
    if policy_id == SMART_APP_CONTROL_POLICY_ID.lower():
        output["source"] = f"SmartAppControl/{SMART_APP_CONTROL_POLICY_NAME}"
        output["smart_app_control"] = True
        paths = output.get("paths") or []
        if paths and all(_is_pyav_native_path(path) for path in paths):
            output["mitigated"] = True
            output["mitigation"] = "stt_pcm_numpy_bypass_configured"
            output["dependency"] = "PyAV"
        else:
            output["mitigated"] = False
    else:
        output["smart_app_control"] = False
        output["mitigated"] = False
    return output


def _annotate_current_file_state(row: dict[str, Any]) -> dict[str, Any]:
    """Separate a historical Windows block event from a block that is still
    actionable in the current installation. Event logs are evidence that a
    file was blocked at a point in time; they are not proof that the blocked
    artifact is still present. We never delete or alter the Windows event.
    """
    output = dict(row)
    paths = [str(value or "") for value in output.get("paths") or [] if str(value or "").strip()]
    existing = [path for path in paths if os.path.exists(path)]
    missing = [path for path in paths if path not in existing]
    output["referenced_paths_existing"] = existing
    output["referenced_paths_missing"] = missing
    output["current_file_present"] = bool(existing)
    output["resolved_historical"] = False

    if (
        output.get("classification") == "confirmed_block"
        and not output.get("mitigated")
        and paths
        and not existing
    ):
        output["resolved_historical"] = True
        output["resolution"] = "blocked_artifact_no_longer_present"
    return output


def _extract_jarvis_paths(event: dict[str, Any], root: Path) -> list[str]:
    root_text = str(root)
    root_name = root_text.replace("\\", "/").rstrip("/").split("/")[-1]
    candidates: list[str] = []
    values = [str(value or "").strip().strip('"') for value in event.get("properties") or []]
    message = str(event.get("message") or "")
    values.append(message)

    dos_pattern = re.compile(
        re.escape(root_text)
        + r'[^"\r\n<>|]*?(?:\.dll|\.pyd|\.exe|\.py|\.ps1|\.bat|\.cmd)',
        re.IGNORECASE,
    )
    device_pattern = re.compile(
        r'\\Device\\HarddiskVolume\d+\\'
        + re.escape(root_name)
        + r'\\([^"\r\n<>|]*?(?:\.dll|\.pyd|\.exe|\.py|\.ps1|\.bat|\.cmd))',
        re.IGNORECASE,
    )

    for text in values:
        candidates.extend(match.group(0) for match in dos_pattern.finditer(text))
        for match in device_pattern.finditer(text):
            relative = match.group(1).replace("/", "\\")
            candidates.append(root_text.rstrip("\\/") + "\\" + relative)

    output: list[str] = []
    seen = set()
    for value in candidates:
        normalized = value.strip().strip('"')
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def _collect_windows_events(root: Path, *, days: int, timeout_seconds: float) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": True, "supported": False, "events": [], "logs": [], "reason": "non_windows"}
    env = dict(os.environ)
    env["JARVIS_BLOCK_AUDIT_ROOT"] = str(root)
    env["JARVIS_BLOCK_AUDIT_DAYS"] = str(max(1, min(int(days), 90)))
    command = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_BLOCK_EVENT_SCRIPT,
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            timeout=max(2.0, float(timeout_seconds)),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "supported": True, "events": [], "logs": [], "error": "EVENT_LOG_TIMEOUT"}
    except Exception as exc:
        return {"ok": False, "supported": True, "events": [], "logs": [], "error": type(exc).__name__, "message": str(exc)}
    if proc.returncode != 0:
        return {
            "ok": False, "supported": True, "events": [], "logs": [],
            "error": "POWERSHELL_FAILED", "returncode": proc.returncode,
            "stderr": _decode_subprocess_stream(proc.stderr).strip()[:1000],
        }
    raw = _decode_subprocess_stream(proc.stdout).strip()
    if not raw:
        return {"ok": False, "supported": True, "events": [], "logs": [], "error": "EMPTY_EVENT_LOG_RESULT"}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"ok": False, "supported": True, "events": [], "logs": [], "error": "INVALID_EVENT_LOG_JSON", "message": str(exc)}
    rows = payload.get("events") or []
    if isinstance(rows, dict):
        rows = [rows]
    processed = []
    for row in rows:
        try:
            event_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        classification, source = classify_windows_event(event_id)
        processed.append(_annotate_current_file_state(_annotate_block_event({
            "id": event_id,
            "classification": classification,
            "source": source,
            "log": row.get("log"),
            "time_created": row.get("time_created"),
            "paths": _extract_jarvis_paths(row, root),
            "policy_id": _extract_policy_id(row),
        })))
    logs = payload.get("logs") or []
    if isinstance(logs, dict):
        logs = [logs]
    return {"ok": True, "supported": True, "events": processed, "logs": logs}


NATIVE_IMPORT_PROBE_SCRIPT = r"""
import json

rows = {}

def check(name, callback):
    try:
        detail = callback()
        rows[name] = {"status": "ok", "detail": detail}
    except Exception as exc:
        rows[name] = {
            "status": "failed",
            "error": type(exc).__name__,
            "message": str(exc)[:500],
        }

def check_numpy():
    import numpy
    return getattr(numpy, "__version__", "unknown")

def check_sounddevice():
    import sounddevice
    return getattr(sounddevice, "__version__", "unknown")

def check_ctranslate2():
    import ctranslate2
    return getattr(ctranslate2, "__version__", "unknown")

def check_faster_whisper_pcm():
    from jarvis_core.services.stt_compat import probe_faster_whisper_pcm_import
    result = probe_faster_whisper_pcm_import()
    if not result.get("ok"):
        raise RuntimeError(result.get("message") or result.get("error") or "STT_IMPORT_FAILED")
    return "PyAV not required for PCM import path"

check("numpy", check_numpy)
check("sounddevice", check_sounddevice)
check("ctranslate2", check_ctranslate2)
check("faster_whisper_pcm", check_faster_whisper_pcm)
print(json.dumps({"ok": True, "components": rows}, ensure_ascii=True))
"""


def _probe_native_import_health(root: Path, *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": True, "supported": False, "components": {}, "reason": "non_windows"}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", NATIVE_IMPORT_PROBE_SCRIPT],
            cwd=str(root),
            capture_output=True,
            timeout=max(3.0, float(timeout_seconds)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "supported": True, "components": {}, "error": "NATIVE_IMPORT_TIMEOUT"}
    except Exception as exc:
        return {
            "ok": False,
            "supported": True,
            "components": {},
            "error": type(exc).__name__,
            "message": str(exc)[:500],
        }
    if proc.returncode != 0:
        return {
            "ok": False,
            "supported": True,
            "components": {},
            "error": "NATIVE_IMPORT_PROCESS_FAILED",
            "returncode": proc.returncode,
            "stderr": _decode_subprocess_stream(proc.stderr).strip()[:1000],
        }
    stdout_text = _decode_subprocess_stream(proc.stdout)
    lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "supported": True, "components": {}, "error": "NATIVE_IMPORT_EMPTY"}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "supported": True,
            "components": {},
            "error": "NATIVE_IMPORT_INVALID_JSON",
            "message": str(exc),
        }
    payload["supported"] = True
    return payload




def _norm_path_key(value: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(value))).replace("/", "\\")


def _parse_event_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _probe_native_llama_binary(root: Path, *, timeout_seconds: float = 8.0) -> dict[str, Any]:
    """Probe only the JARVIS-owned pinned llama-server binary.

    This is deliberately narrower than executing an arbitrary path mentioned by
    Windows Event Log. It proves that the current JARVIS text runtime and its DLL
    dependencies can be loaded by Windows *now*, which lets the audit distinguish
    a historical Code Integrity event from a present blocker.
    """
    exe = root / "runtime" / "llama.cpp" / "llama-server.exe"
    if os.name != "nt":
        return {"ok": True, "supported": False, "installed": exe.is_file(), "reason": "non_windows"}
    if not exe.is_file():
        return {"ok": True, "supported": True, "installed": False, "path": str(exe), "reason": "not_installed"}
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            cwd=str(exe.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(2.0, float(timeout_seconds)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "supported": True, "installed": True, "path": str(exe), "error": "LLAMA_VERSION_TIMEOUT"}
    except Exception as exc:
        return {"ok": False, "supported": True, "installed": True, "path": str(exe), "error": type(exc).__name__, "message": str(exc)[:500]}
    code = int(proc.returncode or 0)
    code_hex = f"0x{(code & 0xFFFFFFFF):08X}"
    stdout = _decode_subprocess_stream(proc.stdout).strip()
    stderr = _decode_subprocess_stream(proc.stderr).strip()
    return {
        "ok": code == 0,
        "supported": True,
        "installed": True,
        "path": str(exe),
        "returncode": code,
        "returncode_hex": code_hex,
        "stdout": stdout[:1200],
        "stderr": stderr[:1200],
    }



def _probe_local_ollama_executor(root: Path, *, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Probe the optional loopback-only Qwen compatibility executor.

    A healthy result does not turn Ollama into JARVIS's reasoning authority; it
    only proves that the same configured local model can be executed while a
    standalone llama.cpp binary is blocked by Windows policy.
    """
    settings_path = root / "settings.json"
    settings: dict[str, Any] = {}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig")) if settings_path.is_file() else {}
    except Exception:
        settings = {}
    backend = str(settings.get("local_llm_backend") or "jarvis_local").strip().lower()
    allowed = bool(settings.get("local_llm_allow_ollama_compat", True)) and backend in {"jarvis_local", "auto", "auto_local", "ollama_local_compat", "ollama_compat"}
    host = str(settings.get("ollama_host") or "http://127.0.0.1:11434").rstrip("/")
    model = str(settings.get("model") or "qwen3:8b")
    if not allowed:
        return {"ok": False, "allowed": False, "online": False, "model_ok": False, "model": model, "reason": "disabled"}
    try:
        req = urlrequest.Request(host + "/api/tags", method="GET")
        with urlrequest.urlopen(req, timeout=max(1.0, float(timeout_seconds))) as response:
            raw = response.read()
        data = json.loads(raw.decode("utf-8")) if raw else {}
        names = {
            str(row.get("model") or row.get("name") or "")
            for row in (data.get("models") or [])
            if isinstance(row, dict)
        }
        model_ok = model in names
        return {"ok": bool(model_ok), "allowed": True, "online": True, "model_ok": model_ok, "model": model, "host": host, "models": sorted(names)}
    except Exception as exc:
        return {"ok": False, "allowed": True, "online": False, "model_ok": False, "model": model, "host": host, "error": type(exc).__name__, "message": str(exc)[:500]}

def _corroborate_block_event(
    row: dict[str, Any],
    *,
    marked_path_keys: set[str],
    native_failures: list[str],
    llama_probe: dict[str, Any],
    local_executor_probe: dict[str, Any] | None = None,
    root: Path,
) -> dict[str, Any]:
    """Classify whether a historical Windows block event is still current.

    Event 3077/8004/8007 is immutable historical evidence: it proves a block
    happened, not that the same artifact is blocked forever. A present blocker
    therefore needs current corroboration (MOTW, a failing active native stack,
    or a failing JARVIS llama-server load probe). Events without present
    corroboration remain visible as historical/review evidence and are never
    deleted.
    """
    local_executor_probe = local_executor_probe or {}
    output = dict(row)
    output["current_block_corroborated"] = False
    output["current_block_reason"] = None
    output["historical_uncorroborated"] = False

    if output.get("mitigated") or output.get("resolved_historical"):
        return output

    paths = [str(v or "") for v in output.get("paths") or [] if str(v or "").strip()]
    existing = [str(v or "") for v in output.get("referenced_paths_existing") or [] if str(v or "").strip()]
    if not paths:
        output["historical_uncorroborated"] = True
        output["resolution"] = "event_has_no_extractable_current_path"
        return output
    if not existing:
        output["resolved_historical"] = True
        output["resolution"] = "blocked_artifact_no_longer_present"
        return output

    current_marked = [path for path in existing if _norm_path_key(path) in marked_path_keys]
    if current_marked:
        output["current_block_corroborated"] = True
        output["current_block_reason"] = "referenced_artifact_still_has_motw"
        output["current_motw_paths"] = current_marked
        return output

    root_runtime = _norm_path_key(root / "runtime" / "llama.cpp") + "\\"
    runtime_paths = [path for path in existing if _norm_path_key(path).startswith(root_runtime)]
    if runtime_paths:
        if llama_probe.get("installed") and llama_probe.get("ok"):
            output["resolved_historical"] = True
            output["resolution"] = "jarvis_llama_runtime_load_probe_now_ok"
            output["current_runtime_probe"] = "ok"
            return output
        if llama_probe.get("installed") and not llama_probe.get("ok"):
            if local_executor_probe.get("ok"):
                output["mitigated"] = True
                output["resolution"] = "standalone_llama_blocked_but_local_qwen_compat_executor_healthy"
                output["mitigation"] = "ollama_loopback_executor_only"
                output["current_runtime_probe"] = llama_probe.get("returncode_hex") or llama_probe.get("error") or "failed"
                output["effective_executor"] = "ollama_local_compat"
                return output
            output["current_block_corroborated"] = True
            output["current_block_reason"] = "jarvis_llama_runtime_load_probe_failed"
            output["current_runtime_probe"] = llama_probe.get("returncode_hex") or llama_probe.get("error") or "failed"
            return output

    venv_paths = [path for path in existing if "\\.venv\\" in _norm_path_key(path).lower()]
    if venv_paths and native_failures:
        output["current_block_corroborated"] = True
        output["current_block_reason"] = "active_native_import_probe_failed"
        output["native_import_failures"] = list(native_failures)
        return output

    # Replacement/update evidence is considered only after present blockers
    # were checked. A newly written file that still has MOTW, or a newly
    # installed runtime that currently fails to load, must remain active.
    event_time = _parse_event_time(output.get("time_created"))
    if event_time is not None:
        replaced = []
        for path in existing:
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc)
                if mtime > event_time:
                    replaced.append(path)
            except OSError:
                pass
        if replaced and len(replaced) == len(existing):
            output["resolved_historical"] = True
            output["resolution"] = "all_referenced_artifacts_modified_after_block_event"
            output["artifacts_modified_after_event"] = replaced
            return output

    output["historical_uncorroborated"] = True
    output["resolution"] = "historical_event_without_present_block_corroboration"
    return output


def audit_windows_blocked_files(
    *, root: str | Path | None = None, event_days: int = 14,
    event_timeout_seconds: float = 5.0, max_files: int = 20000,
    save_report: bool = True,
) -> dict[str, Any]:
    started = monotonic()
    base = Path(root or _default_root()).resolve()
    if not base.exists():
        return {"ok": False, "error": "ROOT_NOT_FOUND", "root": str(base)}
    if os.name != "nt":
        return {
            "ok": True, "supported": False, "platform": platform.system(),
            "root": str(base), "status": "unsupported", "scanned_files": 0,
            "motw_current": [], "confirmed_block_events": [], "integrity_events": [],
            "event_logs": [], "elapsed_ms": round((monotonic() - started) * 1000),
            "limitations": ["Windows Mark-of-the-Web and App Control logs are only available on Windows."],
        }
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="jarvis-block-audit") as pool:
        motw_future = pool.submit(_scan_motw, base, max_files=max_files)
        events_future = pool.submit(
            _collect_windows_events, base, days=event_days,
            timeout_seconds=event_timeout_seconds,
        )
        native_future = pool.submit(
            _probe_native_import_health, base, timeout_seconds=10.0,
        )
        llama_future = pool.submit(
            _probe_native_llama_binary, base, timeout_seconds=8.0,
        )
        executor_future = pool.submit(
            _probe_local_ollama_executor, base, timeout_seconds=3.0,
        )
        motw = motw_future.result()
        windows_events = events_future.result()
        native_health = native_future.result()
        llama_probe = llama_future.result()
        local_executor_probe = executor_future.result()
    all_events = windows_events.get("events") or []
    integrity = [
        row
        for row in all_events
        if row.get("classification") == "integrity_issue"
    ]
    marked = motw.get("marked") or []

    native_marked = [
        row
        for row in marked
        if row.get("extension") in BINARY_EXTENSIONS
    ]
    python_marked = [
        row
        for row in marked
        if row.get("extension") == ".py"
    ]
    script_marked = [
        row
        for row in marked
        if row.get("extension") in {".ps1", ".bat", ".cmd"}
    ]
    other_marked = [
        row
        for row in marked
        if row not in native_marked
        and row not in python_marked
        and row not in script_marked
    ]

    venv_marked = [
        row
        for row in marked
        if "\\.venv\\" in str(row.get("path") or "").lower()
        or "/.venv/" in str(row.get("path") or "").lower()
    ]
    core_marked = [
        row
        for row in marked
        if row not in venv_marked
    ]

    native_components = native_health.get("components") or {}
    native_failures = [
        name for name, row in native_components.items()
        if str((row or {}).get("status") or "").lower() != "ok"
    ]

    marked_path_keys = {_norm_path_key(row.get("path") or "") for row in marked if row.get("path")}
    confirmed_raw = [
        row for row in all_events if row.get("classification") == "confirmed_block"
    ]
    confirmed = [
        _corroborate_block_event(
            row,
            marked_path_keys=marked_path_keys,
            native_failures=native_failures,
            llama_probe=llama_probe,
            local_executor_probe=local_executor_probe,
            root=base,
        )
        for row in confirmed_raw
    ]
    mitigated_confirmed = [row for row in confirmed if row.get("mitigated")]
    resolved_confirmed = [row for row in confirmed if row.get("resolved_historical")]
    historical_uncorroborated = [row for row in confirmed if row.get("historical_uncorroborated")]
    active_confirmed = [row for row in confirmed if row.get("current_block_corroborated")]

    standalone_llama_blocks_operation = bool(llama_probe.get("installed") and not llama_probe.get("ok") and not local_executor_probe.get("ok"))
    if active_confirmed or native_failures or standalone_llama_blocks_operation:
        status = "blocked"
    elif mitigated_confirmed or resolved_confirmed or historical_uncorroborated or integrity:
        status = "review"
    elif native_marked:
        status = "native_marked"
    elif marked:
        status = "marked"
    elif not windows_events.get("ok"):
        status = "partial"
    else:
        status = "clear"
    report = {
        "ok": True,
        "supported": True,
        "platform": platform.system(),
        "root": str(base),
        "status": status,
        "generated_at": _utc_now(),
        "elapsed_ms": round((monotonic() - started) * 1000),
        "scanned_files": int(motw.get("scanned_files") or 0),
        "scan_truncated": bool(motw.get("truncated")),
        "extension_counts": motw.get("extension_counts") or {},
        "motw_current": marked,
        "motw_native_current": native_marked,
        "motw_python_current": python_marked,
        "motw_script_current": script_marked,
        "motw_other_current": other_marked,
        "motw_core_current": core_marked,
        "motw_venv_current": venv_marked,
        "motw_counts": {
            "total": len(marked),
            "native": len(native_marked),
            "python": len(python_marked),
            "script": len(script_marked),
            "other": len(other_marked),
            "core": len(core_marked),
            "venv": len(venv_marked),
        },
        "confirmed_block_events": confirmed,
        "active_block_events": active_confirmed,
        "resolved_historical_block_events": resolved_confirmed,
        "mitigated_block_events": mitigated_confirmed,
        "historical_uncorroborated_block_events": historical_uncorroborated,
        "integrity_events": integrity,
        "native_import_health": native_health,
        "native_llama_runtime_probe": llama_probe,
        "local_llm_executor_probe": local_executor_probe,
        "native_import_failures": native_failures,
        "event_logs": windows_events.get("logs") or [],
        "event_log_ok": bool(windows_events.get("ok")),
        "event_log_error": windows_events.get("error"),
        "limitations": [
            "Zone.Identifier (MOTW) proves the file is currently marked as Internet/Restricted origin; it does not prove Windows will refuse every use of that file.",
            "CodeIntegrity/AppLocker events are immutable historical evidence that a block happened; they are only called active when present evidence corroborates the block (current MOTW, a failing active native import probe, or a failing JARVIS llama runtime load probe with no healthy configured local compatibility executor).",
            "Events with no extractable path or with an existing but currently healthy/unmarked artifact remain visible as historical/unconfirmed review evidence; they do not fail the security baseline by themselves.",
            "Smart App Control/App Control enforcement blocks are read from CodeIntegrity event 3077; AppLocker blocks use 8004/8007.",
            "Policy {0283ac0f-fff1-49ae-ada1-8a933130cad6} is identified as Smart App Control VerifiedAndReputableDesktop.",
            "PyAV native blocks can be marked mitigated for JARVIS microphone STT because Core 0.19.4 supplies decoded NumPy PCM to faster-whisper; the historical Windows block event remains in the report.",
            "This audit is read-only and never unblocks files, removes Zone.Identifier, changes App Control policy or alters a file.",
        ],
    }
    if save_report:
        try:
            report_path = base / "memory" / "windows_block_audit.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["report_path"] = str(report_path)
        except Exception:
            pass
    return report


def format_windows_block_audit(
    report: dict[str, Any],
    *,
    detail: str = "standard",
) -> str:
    if not report.get("supported", True):
        return "WINDOWS BLOCK AUDIT — indisponível fora do Windows."

    if not report.get("ok"):
        return (
            "WINDOWS BLOCK AUDIT — erro: "
            f"{report.get('error') or 'UNKNOWN'}"
        )

    counts = report.get("motw_counts") or {}
    motw = report.get("motw_current") or []
    native = report.get("motw_native_current") or []
    python_rows = report.get("motw_python_current") or []
    scripts = report.get("motw_script_current") or []
    blocked = report.get("confirmed_block_events") or []
    active_rows = report.get("active_block_events")
    active_blocked = (
        report.get("confirmed_block_events") or []
        if active_rows is None
        else active_rows or []
    )
    mitigated_blocked = report.get("mitigated_block_events") or []
    resolved_blocked = report.get("resolved_historical_block_events") or []
    historical_uncorroborated = report.get("historical_uncorroborated_block_events") or []
    integrity = report.get("integrity_events") or []
    native_health = report.get("native_import_health") or {}
    native_components = native_health.get("components") or {}
    native_failures = report.get("native_import_failures") or []
    llama_probe = report.get("native_llama_runtime_probe") or {}
    local_executor_probe = report.get("local_llm_executor_probe") or {}

    status = str(report.get("status") or "unknown").upper()
    lines = [
        "WINDOWS BLOCK AUDIT",
        (
            f"Estado: {status} · "
            f"Ficheiros analisados: {report.get('scanned_files', 0)} · "
            f"MOTW total: {len(motw)} "
            f"(nativos {len(native)} · py {len(python_rows)} · scripts {len(scripts)}) · "
            f"Bloqueios ativos: {len(active_blocked)} · "
            f"Resolvidos/históricos: {len(resolved_blocked)} · "
            f"Históricos sem corroboração atual: {len(historical_uncorroborated)} · "
            f"Mitigados: {len(mitigated_blocked)} · "
            f"Integridade: {len(integrity)} · "
            f"Native imports falhados: {len(native_failures)} · "
            f"{report.get('elapsed_ms', 0)} ms"
        ),
    ]
    llama_state = "OK" if llama_probe.get("ok") else (llama_probe.get("returncode_hex") or llama_probe.get("error") or "N/A")
    executor_state = "OK" if local_executor_probe.get("ok") else ("OFFLINE" if local_executor_probe.get("allowed") else "DISABLED")
    lines.append(f"Executor LLM local: native={llama_state} · ollama-compat={executor_state} · external AI=OFF")

    if active_blocked:
        lines.append("")
        lines.append("BLOQUEIOS ATIVOS/NAO MITIGADOS PELO CORE")
        for row in active_blocked[:30]:
            paths = row.get("paths") or []
            lines.append(
                "- "
                f"{row.get('source')} · Event {row.get('id')} · "
                f"{row.get('time_created') or '-'} · "
                + (", ".join(paths) if paths else "caminho não extraído")
            )

    if resolved_blocked:
        lines.append("")
        lines.append("BLOQUEIOS RESOLVIDOS/HISTORICOS — ARTEFACTO JA NAO EXISTE")
        for row in resolved_blocked[:30]:
            paths = row.get("paths") or []
            lines.append(
                "- "
                f"{row.get('source')} · Event {row.get('id')} · "
                f"{row.get('time_created') or '-'} · "
                + (", ".join(paths) if paths else "caminho não extraído")
            )

    if historical_uncorroborated:
        lines.append("")
        lines.append("EVENTOS HISTORICOS SEM CORROBORACAO DE BLOQUEIO ATUAL")
        for row in historical_uncorroborated[:30]:
            paths = row.get("paths") or []
            lines.append(
                "- "
                f"{row.get('source')} · Event {row.get('id')} · "
                f"{row.get('time_created') or '-'} · "
                f"{row.get('resolution') or 'sem evidencia atual'} · "
                + (", ".join(paths) if paths else "caminho não extraído")
            )

    if mitigated_blocked:
        lines.append("")
        lines.append("BLOQUEIOS HISTORICOS MITIGADOS NO CORE")
        for row in mitigated_blocked[:30]:
            paths = row.get("paths") or []
            lines.append(
                "- "
                f"{row.get('source')} · {row.get('dependency') or 'dependencia'} · "
                f"{row.get('mitigation') or 'mitigacao configurada'} · "
                + (", ".join(paths) if paths else "caminho não extraído")
            )

    if llama_probe.get("installed"):
        lines.append("")
        llama_state = "OK" if llama_probe.get("ok") else "FAILED"
        llama_detail = llama_probe.get("returncode_hex") or llama_probe.get("error") or ""
        lines.append("JARVIS NATIVE LLM RUNTIME")
        lines.append(f"- llama-server: {llama_state}" + (f" · {llama_detail}" if llama_detail else ""))

    if native_components:
        lines.append("")
        lines.append("NATIVE IMPORT HEALTH")
        for name in ("numpy", "sounddevice", "ctranslate2", "faster_whisper_pcm"):
            row = native_components.get(name)
            if not row:
                continue
            state = str(row.get("status") or "unknown").upper()
            detail_text = row.get("detail") or row.get("error") or ""
            lines.append(f"- {name}: {state}" + (f" · {detail_text}" if detail_text else ""))

    if native:
        lines.append("")
        lines.append("MOTW EM BINÁRIOS NATIVOS — REVER")
        for row in native[:30]:
            lines.append(
                "- "
                f"{row.get('relative_path')} · "
                f"ZoneId={row.get('zone_id')} ({row.get('zone')})"
            )

    if detail == "full" and (python_rows or scripts):
        lines.append("")
        lines.append("MOTW EM CÓDIGO/SCRIPTS — METADATA DE ORIGEM")
        for row in (python_rows + scripts)[:60]:
            lines.append(
                "- "
                f"{row.get('relative_path')} · "
                f"ZoneId={row.get('zone_id')} ({row.get('zone')})"
            )

    if integrity and detail in {"full", "raw"}:
        lines.append("")
        lines.append("EVENTOS DE INTEGRIDADE")
        for row in integrity[:30]:
            paths = row.get("paths") or []
            lines.append(
                "- "
                f"{row.get('source')} · Event {row.get('id')} · "
                + (", ".join(paths) if paths else "caminho não extraído")
            )

    if not active_blocked and not integrity and not native and motw:
        lines.append("")
        lines.append(
            "Nota: os ficheiros têm Mark-of-the-Web, mas não há "
            "evidência de bloqueio confirmado do Windows nesta auditoria."
        )

    if not motw and not active_blocked and not resolved_blocked and not historical_uncorroborated and not mitigated_blocked and not integrity and not native_failures:
        lines.append(
            "Nenhum MOTW atual nem bloqueio recente do Core foi encontrado."
        )

    if not report.get("event_log_ok", True):
        lines.append("")
        lines.append(
            "Nota: os logs CodeIntegrity/AppLocker não puderam "
            f"ser lidos completamente ({report.get('event_log_error') or 'erro desconhecido'})."
        )

    if detail == "full":
        lines.append("")
        lines.append("LIMITAÇÕES")
        for item in report.get("limitations") or []:
            lines.append(f"- {item}")

    if detail == "raw":
        return json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )

    return "\n".join(lines)

def _startup_cache_path(root: Path) -> Path:
    return root / "memory" / STARTUP_CACHE_NAME


def _startup_tree_signal(root: Path) -> dict[str, Any]:
    """Cheap metadata fingerprint for files that can change startup security."""
    specs = (
        (root / "jarvis_core", {".py"}),
        (root / "runtime" / "llama.cpp", {".exe", ".dll"}),
        (root / ".venv", {".exe", ".dll", ".pyd"}),
    )
    rows: dict[str, Any] = {}
    for base, extensions in specs:
        count = 0
        total_size = 0
        max_mtime_ns = 0
        mixed = 0
        if base.exists():
            for current, dirs, files in os.walk(base):
                dirs[:] = sorted(name for name in dirs if name.lower() not in EXCLUDED_DIRS)
                files = sorted(files)
                for name in files:
                    path = Path(current) / name
                    if path.suffix.lower() not in extensions:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    count += 1
                    total_size += int(stat.st_size)
                    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)))
                    max_mtime_ns = max(max_mtime_ns, mtime_ns)
                    mixed ^= (mtime_ns ^ int(stat.st_size) ^ count) & 0xFFFFFFFFFFFFFFFF
        try:
            key = str(base.relative_to(root)).replace("\\", "/")
        except ValueError:
            key = str(base)
        rows[key] = {
            "count": count,
            "total_size": total_size,
            "max_mtime_ns": max_mtime_ns,
            "mixed": mixed,
        }

    sentinels = (
        "release_manifest.json",
        "settings.json",
        "jarvis.py",
        "run.ps1",
        "runtime/llama.cpp/jarvis_runtime_provenance.json",
        "memory/security/appcontrol/jarvis_appcontrol_trust_state.json",
        ".venv/pyvenv.cfg",
    )
    sentinel_rows: dict[str, Any] = {}
    for relative in sentinels:
        path = root / relative
        try:
            stat = path.stat()
            sentinel_rows[relative] = {
                "exists": True,
                "size": int(stat.st_size),
                "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
            }
        except OSError:
            sentinel_rows[relative] = {"exists": False}
    return {"trees": rows, "sentinels": sentinel_rows}


def _startup_cache_report_is_safe(report: dict[str, Any]) -> bool:
    if not report.get("ok") or not report.get("supported", True):
        return False
    if report.get("active_block_events"):
        return False
    if report.get("native_import_failures"):
        return False
    llama = report.get("native_llama_runtime_probe") or {}
    if llama.get("installed") and not llama.get("ok"):
        return False
    return True


def _startup_cache_ttl_seconds() -> float:
    raw = os.environ.get("JARVIS_STARTUP_SECURITY_CACHE_SECONDS", "")
    try:
        value = float(raw) if raw.strip() else STARTUP_CACHE_TTL_SECONDS
    except (TypeError, ValueError):
        value = STARTUP_CACHE_TTL_SECONDS
    return max(0.0, min(value, STARTUP_CACHE_MAX_TTL_SECONDS))


def _startup_high_risk_motw_present(root: Path) -> bool:
    # A cache hit never trusts fresh Internet-zone marking on the principal
    # execution boundaries. This check is tiny compared with the full tree scan.
    for relative in (
        "runtime/llama.cpp/llama-server.exe",
        "runtime/llama.cpp/llama-server-impl.dll",
        ".venv/Scripts/python.exe",
        "run.ps1",
        "jarvis.py",
    ):
        path = root / relative
        if not path.exists():
            continue
        zone = read_zone_identifier(path)
        if zone and zone.get("currently_marked_from_internet"):
            return True
    return False


def _load_startup_cache(root: Path) -> dict[str, Any] | None:
    ttl = _startup_cache_ttl_seconds()
    if os.name != "nt" or ttl <= 0:
        return None
    path = _startup_cache_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    if int(payload.get("schema") or 0) != STARTUP_CACHE_SCHEMA:
        return None
    try:
        created = datetime.fromisoformat(str(payload.get("created_at") or "").replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None
    if age < 0 or age > ttl:
        return None
    report = payload.get("report")
    if not isinstance(report, dict) or not _startup_cache_report_is_safe(report):
        return None
    if payload.get("fingerprint") != _startup_tree_signal(root):
        return None
    if _startup_high_risk_motw_present(root):
        return None
    cached = dict(report)
    cached["startup_cache_hit"] = True
    cached["startup_cache_age_seconds"] = round(age, 1)
    cached["full_audit_elapsed_ms"] = report.get("elapsed_ms")
    return cached


def _save_startup_cache(root: Path, report: dict[str, Any]) -> None:
    if os.name != "nt" or not _startup_cache_report_is_safe(report):
        return
    try:
        path = _startup_cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": STARTUP_CACHE_SCHEMA,
            "created_at": _utc_now(),
            "fingerprint": _startup_tree_signal(root),
            "report": report,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def startup_preflight(*, root: str | Path | None = None) -> dict[str, Any]:
    started = monotonic()
    base = Path(root or _default_root()).resolve()
    cached = _load_startup_cache(base)
    if cached is not None:
        cached["startup_preflight_elapsed_ms"] = round((monotonic() - started) * 1000)
        return cached

    report = audit_windows_blocked_files(
        root=base, event_days=14, event_timeout_seconds=5.0,
        max_files=20000, save_report=True,
    )
    report["startup_cache_hit"] = False
    report["startup_preflight_elapsed_ms"] = round((monotonic() - started) * 1000)
    _save_startup_cache(base, report)
    return report


def format_startup_preflight(
    report: dict[str, Any],
) -> str:
    if not report.get("supported", True):
        return ""

    if not report.get("ok"):
        return (
            "[PREFLIGHT] Windows Block Audit: "
            f"ERRO ({report.get('error') or 'UNKNOWN'})"
        )

    counts = report.get("motw_counts") or {}
    motw = int(counts.get("total") or 0)
    native = int(counts.get("native") or 0)
    python_count = int(counts.get("python") or 0)
    scripts = int(counts.get("script") or 0)
    blocked = len(report.get("confirmed_block_events") or [])
    active_rows = report.get("active_block_events")
    active_blocked = len(
        (report.get("confirmed_block_events") or [])
        if active_rows is None
        else (active_rows or [])
    )
    mitigated_blocked = len(report.get("mitigated_block_events") or [])
    resolved_blocked = len(report.get("resolved_historical_block_events") or [])
    historical_uncorroborated = len(report.get("historical_uncorroborated_block_events") or [])
    integrity = len(report.get("integrity_events") or [])
    native_failures = len(report.get("native_import_failures") or [])
    llama_probe = report.get("native_llama_runtime_probe") or {}
    llama_failed = bool(llama_probe.get("installed") and not llama_probe.get("ok"))

    if active_blocked or native_failures or llama_failed:
        level = "BLOQUEIO"
    elif mitigated_blocked or resolved_blocked or historical_uncorroborated or integrity or native:
        level = "REVER"
    elif motw:
        level = "INFO"
    else:
        level = "OK"

    if level == "OK":
        startup_ms = report.get("startup_preflight_elapsed_ms", report.get("elapsed_ms", 0))
        cache = " | cache=HIT" if report.get("startup_cache_hit") else ""
        return (
            "[PREFLIGHT] Windows Block Audit: OK | "
            f"{report.get('scanned_files', 0)} ficheiros | "
            f"{startup_ms} ms{cache}"
        )

    cache = " | cache=HIT" if report.get("startup_cache_hit") else ""
    return (
        f"[PREFLIGHT] Windows Block Audit: {level}{cache} | "
        f"MOTW={motw} (nativos={native}, py={python_count}, scripts={scripts}) | "
        f"bloqueios ativos={active_blocked} | resolvidos={resolved_blocked} | historicos_sem_corrob={historical_uncorroborated} | mitigados={mitigated_blocked} | "
        f"integridade={integrity} | native_failures={native_failures} | llama_runtime_failed={int(llama_failed)} | "
        "usa /security blocked files para detalhes"
    )

def get_windows_block_audit(detail: str = "standard") -> dict[str, Any]:
    mode = str(detail or "standard").strip().lower()
    if mode not in {"standard", "full", "raw"}:
        mode = "standard"
    report = audit_windows_blocked_files()
    report["detail"] = mode
    return report
