from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import Event, Thread, RLock
from typing import Any
import json
import os
import platform

import psutil

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SystemGuardianService:
    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.baseline_path = Path(getattr(context.settings, "guardian_baseline_path", "memory/guardian_baseline.json"))
        self.state_path = Path(getattr(context.settings, "guardian_state_path", "memory/guardian_state.json"))
        self.interval = max(60.0, float(getattr(context.settings, "guardian_interval_seconds", 120.0)))
        self.alert_cooldown = max(60.0, float(getattr(context.settings, "guardian_alert_cooldown_seconds", 900.0)))
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = RLock()

    @staticmethod
    def _startup_entries() -> list[dict[str, Any]]:
        if platform.system().lower() != "windows":
            return []
        try:
            import winreg
        except Exception:
            return []
        locations = [
            ("HKCU", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            ("HKCU", winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
            ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"),
        ]
        rows: list[dict[str, Any]] = []
        for hive_name, hive, key_name in locations:
            try:
                with winreg.OpenKey(hive, key_name, 0, winreg.KEY_READ) as key:
                    index = 0
                    while True:
                        try:
                            name, value, _typ = winreg.EnumValue(key, index)
                        except OSError:
                            break
                        rows.append({"hive": hive_name, "key": key_name, "name": str(name), "command": str(value)})
                        index += 1
            except OSError:
                continue
        rows.sort(key=lambda r: (r["hive"], r["key"], r["name"].lower()))
        return rows

    @staticmethod
    def _listeners() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            conns = []
        for conn in conns:
            if str(conn.status).upper() != "LISTEN" or not conn.laddr:
                continue
            ip = str(getattr(conn.laddr, "ip", conn.laddr[0] if conn.laddr else ""))
            port = int(getattr(conn.laddr, "port", conn.laddr[1] if conn.laddr else 0))
            pid = conn.pid
            proc_name = None
            exe = None
            if pid:
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name()
                    exe = proc.exe()
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    pass
            rows.append({"ip": ip, "port": port, "pid": pid, "process": proc_name, "exe": exe})
        rows.sort(key=lambda r: (r["port"], str(r.get("exe") or "")))
        return rows

    @staticmethod
    def _processes() -> list[dict[str, Any]]:
        rows = []
        for proc in psutil.process_iter(attrs=["pid", "name", "exe"]):
            try:
                exe = proc.info.get("exe")
                rows.append({"pid": proc.info.get("pid"), "name": proc.info.get("name"), "exe": exe})
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
        return rows

    @staticmethod
    def _release_integrity() -> dict[str, Any]:
        manifest_path = Path("release_manifest.json")
        if not manifest_path.is_file():
            return {"ok": False, "error": "MANIFEST_NOT_FOUND"}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": "MANIFEST_INVALID", "message": str(exc)}
        mismatches = []
        missing = []
        checked = 0
        # Runtime guardian checks the Core code/defaults plus executable entry
        # points. Tests/audit docs are not security-critical at runtime.
        for row in manifest.get("files") or []:
            rel = str(row.get("path") or "").replace("\\", "/")
            if not (rel.startswith("jarvis_core/") or rel in {"jarvis.py", "run.ps1", "update_core.ps1"}):
                continue
            path = Path(rel)
            if not path.is_file():
                missing.append(rel)
                continue
            checked += 1
            actual = sha256(path.read_bytes()).hexdigest()
            if actual.lower() != str(row.get("sha256") or "").lower():
                mismatches.append(rel)
        return {"ok": not missing and not mismatches, "checked": checked, "missing": missing, "mismatches": mismatches}

    def snapshot(self) -> dict[str, Any]:
        return {
            "captured_at": _now(),
            "startup": self._startup_entries(),
            "listeners": self._listeners(),
            "processes": self._processes(),
            "release_integrity": self._release_integrity(),
        }

    @staticmethod
    def _key_startup(row: dict[str, Any]) -> str:
        return f"{row.get('hive')}|{row.get('key')}|{row.get('name')}|{row.get('command')}"

    @staticmethod
    def _key_listener(row: dict[str, Any]) -> str:
        return f"{row.get('ip')}:{row.get('port')}|{str(row.get('exe') or row.get('process') or '').lower()}"

    @staticmethod
    def _severity_counts(alerts: list[dict[str, Any]]) -> dict[str, int]:
        counts = {"critical": 0, "high": 0, "attention": 0, "other": 0}
        for alert in alerts:
            severity = str(alert.get("severity") or "other").strip().lower()
            if severity not in counts:
                severity = "other"
            counts[severity] += 1
        counts["total"] = sum(counts.values())
        return counts

    @staticmethod
    def _highest_severity(counts: dict[str, int]) -> str:
        for severity in ("critical", "high", "attention", "other"):
            if int(counts.get(severity) or 0) > 0:
                return severity
        return "none"

    @staticmethod
    def _alert_fingerprint(alert: dict[str, Any]) -> str:
        payload = {
            "code": alert.get("code"),
            "severity": alert.get("severity"),
            "evidence": alert.get("evidence") or alert.get("process") or {},
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        return sha256(raw).hexdigest()[:24]

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def create_baseline(self) -> dict[str, Any]:
        snap = self.snapshot()
        payload = {"created_at": _now(), "snapshot": snap}
        with self._lock:
            self.baseline_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.context.events.emit("GUARDIAN_BASELINE_CREATED", listeners=len(snap["listeners"]), startup=len(snap["startup"]))
        return {"ok": True, **payload}

    def _load_baseline(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.baseline_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    @staticmethod
    def _suspicious_process(row: dict[str, Any]) -> dict[str, Any] | None:
        exe = str(row.get("exe") or "")
        if not exe:
            return None
        low = exe.lower().replace("/", "\\")
        risky_locations = ("\\temp\\", "\\downloads\\", "\\appdata\\local\\temp\\")
        if any(marker in low for marker in risky_locations):
            return {
                "severity": "attention",
                "code": "PROCESS_FROM_TRANSIENT_LOCATION",
                "message": "Processo em execução a partir de uma localização transitória; requer contexto, não prova malware.",
                "process": row,
            }
        return None

    def scan(self) -> dict[str, Any]:
        baseline = self._load_baseline()
        if not baseline:
            created = self.create_baseline()
            return {"ok": True, "baseline_created": True, "alerts": [], "baseline": created}
        current = self.snapshot()
        old = baseline.get("snapshot") or {}
        old_start = {self._key_startup(row) for row in old.get("startup") or []}
        current_start = {self._key_startup(row) for row in current.get("startup") or []}
        old_listen = {self._key_listener(row) for row in old.get("listeners") or []}
        current_listen = {self._key_listener(row) for row in current.get("listeners") or []}
        alerts: list[dict[str, Any]] = []

        for key in sorted(current_start - old_start):
            row = next((x for x in current["startup"] if self._key_startup(x) == key), None)
            alerts.append({
                "severity": "high",
                "code": "NEW_STARTUP_PERSISTENCE",
                "message": "Nova entrada de arranque automático desde a baseline.",
                "evidence": row,
            })
        for key in sorted(current_listen - old_listen):
            row = next((x for x in current["listeners"] if self._key_listener(x) == key), None)
            alerts.append({
                "severity": "attention",
                "code": "NEW_LISTENER",
                "message": "Novo socket em escuta desde a baseline; validar se corresponde a software esperado.",
                "evidence": row,
            })
        integrity = current.get("release_integrity") or {}
        if not integrity.get("ok"):
            alerts.append({
                "severity": "critical",
                "code": "JARVIS_RELEASE_INTEGRITY_CHANGED",
                "message": "Ficheiros controlados do JARVIS não correspondem ao manifesto da release.",
                "evidence": integrity,
            })
        suspicious = [self._suspicious_process(row) for row in current.get("processes") or []]
        alerts.extend([row for row in suspicious if row])
        # De-duplicate process alerts by executable path to prevent noise.
        dedup: list[dict[str, Any]] = []
        seen = set()
        for alert in alerts:
            key = (alert.get("code"), str((alert.get("process") or alert.get("evidence") or {}).get("exe") or alert.get("evidence") or ""))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(alert)
        alerts = dedup[:50]
        previous = self._load_state()
        previous_notifications = previous.get("notification_state") or {}
        now_dt = datetime.now().astimezone()
        now_iso = now_dt.isoformat(timespec="seconds")
        notification_state: dict[str, Any] = {}
        notify_alerts: list[dict[str, Any]] = []
        for alert in alerts:
            fingerprint = self._alert_fingerprint(alert)
            prior = previous_notifications.get(fingerprint) if isinstance(previous_notifications, dict) else None
            prior = prior if isinstance(prior, dict) else {}
            first_seen = str(prior.get("first_seen_at") or now_iso)
            occurrences = max(0, int(prior.get("occurrences") or 0)) + 1
            last_notified = str(prior.get("last_notified_at") or "")
            should_notify = not last_notified
            if last_notified:
                try:
                    last_dt = datetime.fromisoformat(last_notified)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.astimezone()
                    should_notify = (now_dt - last_dt).total_seconds() >= self.alert_cooldown
                except Exception:
                    should_notify = True
            alert["fingerprint"] = fingerprint
            alert["first_seen_at"] = first_seen
            alert["last_seen_at"] = now_iso
            alert["occurrences"] = occurrences
            alert["notification_suppressed"] = not should_notify
            if should_notify:
                notify_alerts.append(alert)
                last_notified = now_iso
            notification_state[fingerprint] = {
                "first_seen_at": first_seen,
                "last_seen_at": now_iso,
                "last_notified_at": last_notified or None,
                "occurrences": occurrences,
            }
        severity_counts = self._severity_counts(alerts)
        state = {
            "ok": True,
            "baseline_created": False,
            "checked_at": now_iso,
            "alerts": alerts,
            "notification_state": notification_state,
            "notified_alert_count": len(notify_alerts),
            "suppressed_alert_count": max(0, len(alerts) - len(notify_alerts)),
            "severity_counts": severity_counts,
            "summary": {
                "new_startup_entries": len(current_start - old_start),
                "new_listeners": len(current_listen - old_listen),
                "integrity_ok": bool(integrity.get("ok")),
                "process_count": len(current.get("processes") or []),
            },
            "current": current,
        }
        with self._lock:
            self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if notify_alerts:
            self.context.events.emit(
                "SYSTEM_GUARDIAN_ALERT",
                count=len(notify_alerts),
                active_count=len(alerts),
                alerts=notify_alerts[:10],
                severity_counts=severity_counts,
                highest_severity=self._highest_severity(severity_counts),
                cooldown_seconds=self.alert_cooldown,
            )
        elif alerts:
            self.context.events.emit(
                "SYSTEM_GUARDIAN_ALERT_COOLDOWN",
                active_count=len(alerts),
                suppressed_count=len(alerts),
                cooldown_seconds=self.alert_cooldown,
            )
        else:
            self.context.events.emit("SYSTEM_GUARDIAN_OK", checked_at=state["checked_at"])
        return state

    def status(self) -> dict[str, Any]:
        baseline = self._load_baseline()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
        return {
            "ok": True,
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval,
            "alert_cooldown_seconds": self.alert_cooldown,
            "baseline_exists": bool(baseline),
            "baseline_created_at": baseline.get("created_at") if baseline else None,
            "last_check": state.get("checked_at"),
            "alerts": state.get("alerts") or [],
            "severity_counts": state.get("severity_counts") or self._severity_counts(state.get("alerts") or []),
            "monitors": ["startup persistence", "listening sockets", "transient-path processes", "JARVIS release integrity"],
        }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="jarvis-system-guardian", daemon=True)
        self._thread.start()
        self.context.events.emit("SYSTEM_GUARDIAN_STARTED", interval_seconds=self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self.context.events.emit("SYSTEM_GUARDIAN_STOPPED")

    def _loop(self) -> None:
        # First pass creates baseline only if none exists; otherwise it verifies.
        while not self._stop.wait(self.interval):
            try:
                self.scan()
            except Exception as exc:
                self.context.events.emit("SYSTEM_GUARDIAN_ERROR", error=f"{type(exc).__name__}: {exc}")


class SystemGuardianSkill(Skill):
    skill_id = "system_guardian"
    name = "System Guardian"
    version = "1.0.0"
    description = "Continuous local monitoring for persistence, listeners, suspicious locations and Core integrity."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = SystemGuardianService(context)
        context.services["system_guardian"] = self.service

    def tools(self) -> list[SkillTool]:
        markers = ("guardian", "vigia", "monitoriza", "segurança contínua", "seguranca continua", "processo estranho", "arranque", "startup", "persistência", "persistencia", "integridade")
        return [
            SkillTool("get_system_guardian_status", "Read continuous System Guardian status and current alerts.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("run_system_guardian_scan", "Run a read-only System Guardian comparison against its local baseline.", self.service.scan, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("create_system_guardian_baseline", "Replace the System Guardian baseline with the current known-good state. Use only when the OWNER explicitly asks.", self.service.create_baseline, {"type":"object","properties":{}}, RiskLevel.CONFIRM, markers),
        ]

    def start(self) -> None:
        if bool(getattr(self.context.settings, "guardian_enabled", True)):
            self.service.start()
        self.started = True

    def stop(self) -> None:
        self.service.stop(); self.started = False

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return SystemGuardianSkill(context)
