from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import ipaddress
import json
import re
import shutil
import subprocess

from jarvis_core.core.subprocess_text import decode_subprocess_stream
import xml.etree.ElementTree as ET

from jarvis_core.services.cyber_range import cyber_range_manager


_USERNAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,31}$")
MAX_SCAN_PORTS = 64
DEFAULT_SERVICE_PORTS = [21, 22, 25, 53, 80, 110, 139, 143, 443, 445, 3306, 3389, 5432, 8080, 8443]
WEB_PORTS = {80, 443, 8000, 8008, 8080, 8081, 8443, 8888, 9000, 9443}


@dataclass(frozen=True, slots=True)
class KaliProfile:
    id: str
    binary: str
    purpose: str
    active_test: bool = True


PROFILES: dict[str, KaliProfile] = {
    "nmap_services": KaliProfile(
        "nmap_services",
        "/usr/bin/nmap",
        "bounded TCP service/version discovery",
    ),
    "whatweb_fingerprint": KaliProfile(
        "whatweb_fingerprint",
        "/usr/bin/whatweb",
        "single-target web technology fingerprinting without redirects",
    ),
    "nikto_safe_web": KaliProfile(
        "nikto_safe_web",
        "/usr/bin/nikto",
        "bounded web misconfiguration/information checks without exploit/DoS tuning",
    ),
    "owner_machine_defensive_services": KaliProfile(
        "owner_machine_defensive_services",
        "/usr/bin/nmap",
        "bounded defensive TCP service inventory of the OWNER machine",
    ),
}


class KaliBridgeManager:
    """Owner-configured SSH bridge into an authorized Kali LAB machine.

    There is intentionally no arbitrary remote shell primitive. Every remote
    command is assembled by the Core from a fixed profile and validated scalar
    arguments. Both the Kali host and each test target are reclassified by the
    Cyber Range immediately before execution.
    """

    def __init__(
        self,
        state_path: str | Path = "memory/kali_bridge.json",
        *,
        enabled: bool = True,
        ssh_executable: str = "ssh",
        connect_timeout_seconds: float = 5.0,
        command_timeout_seconds: float = 120.0,
        output_max_chars: int = 30000,
        known_hosts_path: str | Path = "memory/kali_known_hosts",
        vm_provider: str = "auto",
        vm_identifier: str = "",
        vm_visible: bool = True,
        activity_log_path: str | Path = "memory/kali_activity.jsonl",
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled = bool(enabled)
        self.ssh_executable = str(ssh_executable or "ssh")
        self.connect_timeout_seconds = max(1.0, min(float(connect_timeout_seconds), 20.0))
        self.command_timeout_seconds = max(10.0, min(float(command_timeout_seconds), 300.0))
        self.output_max_chars = max(2000, min(int(output_max_chars), 100000))
        self.known_hosts_path = Path(known_hosts_path)
        self.vm_provider = str(vm_provider or "auto").strip().lower()
        self.vm_identifier = str(vm_identifier or "").strip()
        self.vm_visible = bool(vm_visible)
        self.activity_log_path = Path(activity_log_path)
        self._lock = RLock()
        self._state = self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "version": 2,
            "configured": False,
            "host": None,
            "username": None,
            "port": 22,
            "key_path": None,
            "configured_at": None,
            "authority": None,
            "vm_provider": None,
            "vm_identifier": None,
            "vm_visible": True,
            "vm_configured_at": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return self._default_state()
        if not isinstance(raw, dict):
            return self._default_state()
        state = self._default_state()
        state.update({k: raw.get(k) for k in state})
        return state

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _literal_ip(value: str) -> str:
        raw = str(value or "").strip().split("%", 1)[0]
        try:
            return str(ipaddress.ip_address(raw))
        except ValueError as exc:
            raise ValueError("LITERAL_IP_REQUIRED") from exc

    def _activity(self, event: str, **data: Any) -> None:
        row = {"timestamp": self._now(), "event": event, **data}
        self.activity_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.activity_log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def _which_any(candidates: list[str]) -> str | None:
        for item in candidates:
            path = shutil.which(item)
            if path:
                return path
            p = Path(item)
            if p.is_file():
                return str(p)
        return None

    def _vm_backend(self) -> tuple[str, str] | None:
        provider = self.vm_provider
        if provider in {"auto", "virtualbox"}:
            exe = self._which_any([
                "VBoxManage.exe", "VBoxManage",
                r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe",
            ])
            if exe:
                return "virtualbox", exe
        if provider in {"auto", "vmware"}:
            exe = self._which_any([
                "vmrun.exe", "vmrun",
                r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
                r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
            ])
            if exe:
                return "vmware", exe
        return None

    def configure_vm(self, provider: str, identifier: str, visible: bool = True) -> dict[str, Any]:
        wanted = str(provider or "auto").strip().lower()
        if wanted not in {"auto", "virtualbox", "vmware"}:
            return {"ok": False, "error": "INVALID_KALI_VM_PROVIDER"}
        ident = str(identifier or "").strip().strip('"')
        if not ident:
            return {"ok": False, "error": "KALI_VM_IDENTIFIER_REQUIRED"}
        if wanted == "vmware" and not Path(ident).is_file():
            return {"ok": False, "error": "KALI_VMX_NOT_FOUND", "path": ident}
        with self._lock:
            state = self._load()
            state["vm_provider"] = wanted
            state["vm_identifier"] = ident
            state["vm_visible"] = bool(visible)
            state["vm_configured_at"] = self._now()
            self._state = state
            self._save()
        self.vm_provider = wanted
        self.vm_identifier = ident
        self.vm_visible = bool(visible)
        self._activity("vm_configured", provider=wanted, identifier=ident, visible=bool(visible))
        return {"ok": True, "provider": wanted, "identifier": ident, "visible": bool(visible)}

    def vm_status(self) -> dict[str, Any]:
        state = self._state_copy()
        provider = str(state.get("vm_provider") or self.vm_provider or "auto")
        identifier = str(state.get("vm_identifier") or self.vm_identifier or "")
        visible = bool(state.get("vm_visible") if state.get("vm_identifier") else self.vm_visible)
        old_provider, old_identifier, old_visible = self.vm_provider, self.vm_identifier, self.vm_visible
        self.vm_provider, self.vm_identifier, self.vm_visible = provider, identifier, visible
        try:
            backend = self._vm_backend()
        finally:
            self.vm_provider, self.vm_identifier, self.vm_visible = old_provider, old_identifier, old_visible
        return {
            "ok": True,
            "configured": bool(identifier),
            "provider": backend[0] if backend else provider,
            "backend_found": bool(backend),
            "identifier": identifier or None,
            "visible": visible,
            "activity_log": str(self.activity_log_path),
        }

    def start_vm(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "KALI_BRIDGE_DISABLED"}
        state = self._state_copy()
        self.vm_provider = str(state.get("vm_provider") or self.vm_provider or "auto")
        self.vm_identifier = str(state.get("vm_identifier") or self.vm_identifier or "")
        self.vm_visible = bool(state.get("vm_visible") if state.get("vm_identifier") else self.vm_visible)
        if not self.vm_identifier:
            return {"ok": False, "error": "KALI_VM_NOT_CONFIGURED"}
        backend = self._vm_backend()
        if not backend:
            return {"ok": False, "error": "KALI_VM_PROVIDER_NOT_FOUND"}
        provider, exe = backend
        if provider == "virtualbox":
            argv = [exe, "startvm", self.vm_identifier, "--type", "gui" if self.vm_visible else "headless"]
        else:
            vmx = Path(self.vm_identifier)
            if not vmx.is_file():
                return {"ok": False, "error": "KALI_VMX_NOT_FOUND", "path": self.vm_identifier}
            argv = [exe, "start", str(vmx), "gui" if self.vm_visible else "nogui"]
        self._activity("vm_start_requested", provider=provider, identifier=self.vm_identifier, visible=self.vm_visible)
        completed = subprocess.run(argv, capture_output=True, timeout=45, check=False)
        stdout_text = decode_subprocess_stream(completed.stdout)
        stderr_text = decode_subprocess_stream(completed.stderr)
        ok = completed.returncode == 0 or "already" in stderr_text.lower()
        self._activity("vm_start_result", provider=provider, ok=ok, returncode=completed.returncode)
        watch = self.open_activity_console() if ok and self.vm_visible else {"ok": False, "skipped": True}
        return {"ok": ok, "provider": provider, "visible": self.vm_visible,
                "returncode": completed.returncode, "stdout": stdout_text[-2000:],
                "stderr": stderr_text[-2000:], "activity_console": watch}

    def open_activity_console(self) -> dict[str, Any]:
        self.activity_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.activity_log_path.touch(exist_ok=True)
        ps = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not ps:
            return {"ok": False, "error": "POWERSHELL_NOT_FOUND"}
        script = f"Get-Content -LiteralPath '{str(self.activity_log_path).replace(chr(39), chr(39)*2)}' -Wait -Tail 25"
        try:
            subprocess.Popen([ps, "-NoExit", "-Command", script], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}
        self._activity("activity_console_opened")
        return {"ok": True, "path": str(self.activity_log_path)}

    def configure(
        self,
        host: str,
        username: str,
        port: int = 22,
        key_path: str = "",
    ) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "KALI_BRIDGE_DISABLED"}
        try:
            ip = self._literal_ip(host)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        decision = cyber_range_manager().classify(ip)
        if decision.get("scope") != "LAB" or not decision.get("authorized"):
            return {
                "ok": False,
                "error": "KALI_HOST_NOT_AUTHORIZED_LAB",
                "decision": decision,
            }

        user = str(username or "").strip()
        if not _USERNAME_RE.fullmatch(user):
            return {"ok": False, "error": "INVALID_KALI_USERNAME"}

        try:
            ssh_port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": "INVALID_SSH_PORT"}
        if not 1 <= ssh_port <= 65535:
            return {"ok": False, "error": "INVALID_SSH_PORT"}

        normalized_key: str | None = None
        if str(key_path or "").strip():
            key = Path(str(key_path).strip().strip('"')).expanduser()
            if not key.exists() or not key.is_file():
                return {
                    "ok": False,
                    "error": "SSH_KEY_NOT_FOUND",
                    "key_path": str(key),
                }
            normalized_key = str(key.resolve())

        with self._lock:
            self._state = {
                "version": 1,
                "configured": True,
                "host": ip,
                "username": user,
                "port": ssh_port,
                "key_path": normalized_key,
                "configured_at": self._now(),
                "authority": "owner_cli",
            }
            self._save()
        return {
            "ok": True,
            "configured": True,
            "host": ip,
            "username": user,
            "port": ssh_port,
            "key_configured": bool(normalized_key),
            "authority": "owner_cli",
        }

    def clear(self) -> dict[str, Any]:
        with self._lock:
            existed = bool(self._state.get("configured"))
            self._state = self._default_state()
            self._save()
        return {"ok": True, "cleared": existed}

    def _state_copy(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def _bridge_decision(self) -> dict[str, Any]:
        state = self._state_copy()
        if not self.enabled:
            return {"ok": False, "error": "KALI_BRIDGE_DISABLED", "state": state}
        if not state.get("configured"):
            return {"ok": False, "error": "KALI_BRIDGE_NOT_CONFIGURED", "state": state}
        host = str(state.get("host") or "")
        decision = cyber_range_manager().classify(host)
        if decision.get("scope") != "LAB" or not decision.get("authorized"):
            return {
                "ok": False,
                "error": "KALI_HOST_NO_LONGER_AUTHORIZED_LAB",
                "decision": decision,
                "state": state,
            }
        return {"ok": True, "state": state, "decision": decision}

    def _target_decision(self, target: str) -> dict[str, Any]:
        try:
            ip = self._literal_ip(target)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        decision = cyber_range_manager().classify(ip)
        if decision.get("scope") != "LAB" or not decision.get("authorized"):
            return {
                "ok": False,
                "error": "TARGET_NOT_AUTHORIZED_LAB",
                "decision": decision,
            }
        return {"ok": True, "target": ip, "decision": decision}

    def _owner_defensive_target_decision(self, target: str) -> dict[str, Any]:
        """Authorize only an address currently owned by this JARVIS machine.

        This deliberately does not reuse LAB authority. OWNER_MACHINE_DEFENSIVE
        is a separate bounded defensive scope and never makes the target an
        authorized attack/lab target.
        """
        try:
            ip = self._literal_ip(target)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        decision = cyber_range_manager().classify(ip)
        if decision.get("scope") != "OWNER_MACHINE":
            return {
                "ok": False,
                "error": "TARGET_NOT_OWNER_MACHINE_DEFENSIVE",
                "decision": decision,
            }
        return {"ok": True, "target": ip, "decision": decision}

    def _ssh_path(self) -> str | None:
        raw = self.ssh_executable
        if Path(raw).is_file():
            return str(Path(raw))
        return shutil.which(raw)

    def _ssh_argv(self, state: dict[str, Any], remote_args: list[str]) -> list[str]:
        ssh_path = self._ssh_path()
        if not ssh_path:
            raise RuntimeError("OPENSSH_CLIENT_NOT_FOUND")
        self.known_hosts_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            ssh_path,
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={int(round(self.connect_timeout_seconds))}",
            "-o", "ConnectionAttempts=1",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={self.known_hosts_path}",
            "-o", "LogLevel=ERROR",
            "-p", str(int(state.get("port") or 22)),
        ]
        key_path = str(state.get("key_path") or "").strip()
        if key_path:
            argv.extend(["-i", key_path])
        argv.append(f"{state.get('username')}@{state.get('host')}")
        argv.extend(remote_args)
        return argv

    def _run_remote(
        self,
        remote_args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        bridge = self._bridge_decision()
        if not bridge.get("ok"):
            return bridge
        state = bridge["state"]
        try:
            argv = self._ssh_argv(state, list(remote_args))
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}

        timeout = max(
            5.0,
            min(float(timeout_seconds or self.command_timeout_seconds), 300.0),
        )
        profile_name = Path(str(remote_args[0] if remote_args else "remote")).name
        self._activity(
            "remote_action_started",
            profile=profile_name,
            host=state.get("host"),
            arguments=[str(x) for x in remote_args[1:12]],
        )
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": "KALI_COMMAND_TIMEOUT",
                "timeout_seconds": timeout,
            }
        except OSError as exc:
            return {
                "ok": False,
                "error": "KALI_SSH_EXECUTION_FAILED",
                "message": str(exc),
            }

        stdout = decode_subprocess_stream(completed.stdout)[: self.output_max_chars]
        stderr = decode_subprocess_stream(completed.stderr)[: min(self.output_max_chars, 10000)]
        self._activity(
            "remote_action_finished",
            profile=profile_name,
            host=state.get("host"),
            returncode=int(completed.returncode),
            ok=completed.returncode == 0,
        )
        return {
            "ok": completed.returncode == 0,
            "returncode": int(completed.returncode),
            "stdout": stdout,
            "stderr": stderr,
        }

    def status(self) -> dict[str, Any]:
        bridge = self._bridge_decision()
        state = bridge.get("state") or self._state_copy()
        key_path = str(state.get("key_path") or "").strip()
        return {
            "ok": True,
            "enabled": self.enabled,
            "configured": bool(state.get("configured")),
            "ready_scope": bool(bridge.get("ok")),
            "scope_error": None if bridge.get("ok") else bridge.get("error"),
            "host": state.get("host"),
            "username": state.get("username"),
            "port": state.get("port"),
            "key_configured": bool(key_path),
            "ssh_client_available": bool(self._ssh_path()),
            "model_can_configure": False,
            "arbitrary_remote_shell": False,
            "execution_profiles": {
                key: {
                    "binary": profile.binary,
                    "purpose": profile.purpose,
                }
                for key, profile in PROFILES.items()
            },
        }

    def doctor(self) -> dict[str, Any]:
        bridge = self._bridge_decision()
        if not bridge.get("ok"):
            return bridge
        if not self._ssh_path():
            return {"ok": False, "error": "OPENSSH_CLIENT_NOT_FOUND"}
        result = self._run_remote(["/bin/echo", "JARVIS_KALI_BRIDGE_OK"], timeout_seconds=15)
        if not result.get("ok"):
            result["error"] = result.get("error") or "KALI_SSH_CONNECTION_FAILED"
            return result
        marker = str(result.get("stdout") or "").strip()
        return {
            "ok": marker == "JARVIS_KALI_BRIDGE_OK",
            "connected": marker == "JARVIS_KALI_BRIDGE_OK",
            "host": bridge["state"].get("host"),
            "username": bridge["state"].get("username"),
            "message": marker,
        }

    def inventory(self) -> dict[str, Any]:
        bridge = self._bridge_decision()
        if not bridge.get("ok"):
            return bridge
        checks = {
            "nmap": ["/usr/bin/nmap", "--version"],
            "whatweb": ["/usr/bin/whatweb", "--version"],
            "nikto": ["/usr/bin/nikto", "-Version"],
        }
        items: dict[str, Any] = {}
        for name, args in checks.items():
            result = self._run_remote(args, timeout_seconds=20)
            combined = (str(result.get("stdout") or "") + "\n" + str(result.get("stderr") or "")).strip()
            first_line = combined.splitlines()[0][:300] if combined else ""
            items[name] = {
                "available": bool(result.get("ok")),
                "version": first_line or None,
                "returncode": result.get("returncode"),
            }
        return {
            "ok": True,
            "host": bridge["state"].get("host"),
            "tools": items,
            "executable_profiles": sorted(PROFILES),
        }

    @staticmethod
    def _normalize_ports(ports: list[int] | None) -> list[int]:
        values = DEFAULT_SERVICE_PORTS if not ports else ports
        result: list[int] = []
        for raw in values:
            try:
                port = int(raw)
            except (TypeError, ValueError):
                continue
            if not 1 <= port <= 65535 or port in result:
                continue
            result.append(port)
            if len(result) >= MAX_SCAN_PORTS:
                break
        return result

    @staticmethod
    def _parse_nmap_xml(xml_text: str) -> list[dict[str, Any]]:
        text = str(xml_text or "").strip()
        if not text:
            return []
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
        services: list[dict[str, Any]] = []
        for port_node in root.findall(".//host/ports/port"):
            state_node = port_node.find("state")
            if state_node is None or state_node.get("state") != "open":
                continue
            service_node = port_node.find("service")
            row: dict[str, Any] = {
                "protocol": port_node.get("protocol"),
                "port": int(port_node.get("portid") or 0),
                "state": "open",
            }
            if service_node is not None:
                for key in ("name", "product", "version", "extrainfo", "tunnel"):
                    value = service_node.get(key)
                    if value:
                        row[key] = value[:300]
            services.append(row)
        return services

    def nmap_service_scan(
        self,
        target: str,
        ports: list[int] | None = None,
    ) -> dict[str, Any]:
        auth = self._target_decision(target)
        if not auth.get("ok"):
            return auth
        target_ip = auth["target"]
        port_list = self._normalize_ports(ports)
        if not port_list:
            return {"ok": False, "error": "NO_VALID_PORTS"}
        remote = [
            PROFILES["nmap_services"].binary,
            "-Pn",
            "-sT",
            "-sV",
            "--version-light",
            "-T3",
            "--max-retries", "1",
            "--host-timeout", "90s",
            "-oX", "-",
            "-p", ",".join(str(p) for p in port_list),
            target_ip,
        ]
        result = self._run_remote(remote, timeout_seconds=110)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error") or "NMAP_FAILED",
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
                "target": target_ip,
                "scope": "LAB",
            }
        services = self._parse_nmap_xml(str(result.get("stdout") or ""))
        return {
            "ok": True,
            "profile": "nmap_services",
            "scope": "LAB",
            "target": target_ip,
            "ports_requested": port_list,
            "open_services": services,
            "open_port_count": len(services),
            "evidence_source": "nmap XML via Kali SSH bridge",
            "limitations": [
                "TCP connect scan only; no exploit scripts, spoofing or evasion flags.",
                "Only explicitly OWNER-authorized LAB targets are accepted.",
            ],
        }

    def owner_machine_defensive_service_audit(
        self,
        target: str,
        ports: list[int] | None = None,
    ) -> dict[str, Any]:
        auth = self._owner_defensive_target_decision(target)
        if not auth.get("ok"):
            return auth
        bridge = self._bridge_decision()
        if not bridge.get("ok"):
            return bridge
        target_ip = auth["target"]
        port_list = self._normalize_ports(ports)[:32]
        if not port_list:
            return {"ok": False, "error": "NO_VALID_PORTS"}
        remote = [
            PROFILES["owner_machine_defensive_services"].binary,
            "-Pn", "-n", "-sT", "-sV", "--version-light", "-T2",
            "--max-retries", "1", "--host-timeout", "45s",
            "-oX", "-", "-p", ",".join(str(p) for p in port_list), target_ip,
        ]
        result = self._run_remote(remote, timeout_seconds=65)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error") or "OWNER_DEFENSIVE_NMAP_FAILED",
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
                "target": target_ip,
                "scope": "OWNER_MACHINE_DEFENSIVE",
            }
        services = self._parse_nmap_xml(str(result.get("stdout") or ""))
        return {
            "ok": True,
            "profile": "owner_machine_defensive_services",
            "scope": "OWNER_MACHINE_DEFENSIVE",
            "target": target_ip,
            "ports_requested": port_list,
            "open_services": services,
            "open_port_count": len(services),
            "evidence_source": "bounded nmap XML via Kali SSH bridge",
            "limitations": [
                "OWNER_MACHINE only; LAB authorization is not reused.",
                "TCP connect/version-light only; maximum 32 ports.",
                "No scripts, exploitation, spoofing, evasion or destructive flags.",
            ],
        }

    @staticmethod
    def _web_url(target_ip: str, port: int, https: bool) -> str:
        host = f"[{target_ip}]" if ":" in target_ip else target_ip
        scheme = "https" if https else "http"
        return f"{scheme}://{host}:{port}/"

    def whatweb_fingerprint(
        self,
        target: str,
        port: int = 80,
        https: bool = False,
    ) -> dict[str, Any]:
        auth = self._target_decision(target)
        if not auth.get("ok"):
            return auth
        try:
            web_port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": "INVALID_WEB_PORT"}
        if not 1 <= web_port <= 65535:
            return {"ok": False, "error": "INVALID_WEB_PORT"}
        target_ip = auth["target"]
        url = self._web_url(target_ip, web_port, bool(https))
        remote = [
            PROFILES["whatweb_fingerprint"].binary,
            "--aggression", "1",
            "--follow-redirect=never",
            "--max-redirects=0",
            "--no-cookies",
            url,
        ]
        result = self._run_remote(remote, timeout_seconds=45)
        if not result.get("ok"):
            return {
                "ok": False,
                "error": result.get("error") or "WHATWEB_FAILED",
                "returncode": result.get("returncode"),
                "stderr": result.get("stderr"),
                "target": target_ip,
                "scope": "LAB",
            }
        return {
            "ok": True,
            "profile": "whatweb_fingerprint",
            "scope": "LAB",
            "target": target_ip,
            "port": web_port,
            "https": bool(https),
            "url": url,
            "fingerprint": str(result.get("stdout") or "").strip()[:12000],
            "redirect_policy": "never",
        }

    def nikto_safe_web_scan(
        self,
        target: str,
        port: int = 80,
        https: bool = False,
    ) -> dict[str, Any]:
        auth = self._target_decision(target)
        if not auth.get("ok"):
            return auth
        try:
            web_port = int(port)
        except (TypeError, ValueError):
            return {"ok": False, "error": "INVALID_WEB_PORT"}
        if not 1 <= web_port <= 65535:
            return {"ok": False, "error": "INVALID_WEB_PORT"}
        target_ip = auth["target"]
        remote = [
            PROFILES["nikto_safe_web"].binary,
            "-host", target_ip,
            "-port", str(web_port),
            "-ask", "no",
            "-nointeractive",
            "-nolookup",
            "-nocheck",
            "-nocookies",
            "-maxtime", "90s",
            "-timeout", "6",
            "-Tuning", "123bde",
        ]
        if bool(https):
            remote.append("-ssl")
        result = self._run_remote(remote, timeout_seconds=110)
        # Nikto may use non-zero status for findings/runtime conditions; preserve
        # its output as evidence while distinguishing transport failure.
        if result.get("error"):
            return {
                "ok": False,
                "error": result.get("error"),
                "target": target_ip,
                "scope": "LAB",
            }
        output = (str(result.get("stdout") or "") + "\n" + str(result.get("stderr") or "")).strip()
        return {
            "ok": True,
            "profile": "nikto_safe_web",
            "scope": "LAB",
            "target": target_ip,
            "port": web_port,
            "https": bool(https),
            "returncode": result.get("returncode"),
            "report": output[:20000],
            "tuning": "123bde",
            "excluded_by_profile": [
                "DoS tuning",
                "command-execution tuning",
                "SQL-injection tuning",
                "evasion modes",
                "redirect following",
            ],
        }


def format_kali_bridge_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"Kali Bridge indisponível: {data.get('error', 'erro desconhecido')}"
    state = "READY" if data.get("configured") and data.get("ready_scope") else "NOT READY"
    host = data.get("host") or "não configurado"
    return "\n".join([
        "KALI EXECUTION BRIDGE",
        f"Estado: {state}",
        f"Host: {host}",
        f"SSH client: {'OK' if data.get('ssh_client_available') else 'em falta'}",
        "Perfis: nmap_services | whatweb_fingerprint | nikto_safe_web",
        "Shell remoto arbitrário: BLOQUEADO",
        "Configuração pelo modelo: BLOQUEADA (OWNER CLI apenas)",
    ])


def format_kali_inventory(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"Inventário Kali falhou: {data.get('error', 'erro desconhecido')}"
    lines = [f"KALI TOOLS — {data.get('host')}"]
    for name, row in (data.get("tools") or {}).items():
        lines.append(
            f"- {name}: {'READY' if row.get('available') else 'indisponível'}"
            + (f" | {row.get('version')}" if row.get('version') else "")
        )
    return "\n".join(lines)


def format_kali_scan(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return (
            f"Teste Kali bloqueado/falhou: {data.get('error', 'erro desconhecido')}"
            + (f" | {data.get('stderr')}" if data.get('stderr') else "")
        )
    profile = data.get("profile")
    if profile == "nmap_services":
        lines = [f"NMAP LAB — {data.get('target')}"]
        services = data.get("open_services") or []
        if not services:
            lines.append("- Nenhum serviço aberto encontrado nas portas testadas.")
        for row in services:
            detail = " ".join(
                str(row.get(k)) for k in ("name", "product", "version", "extrainfo") if row.get(k)
            ).strip()
            lines.append(f"- {row.get('port')}/{row.get('protocol')}: {detail or 'serviço não identificado'}")
        return "\n".join(lines)
    if profile == "whatweb_fingerprint":
        return f"WHATWEB LAB — {data.get('url')}\n{data.get('fingerprint') or 'Sem fingerprint.'}"
    if profile == "nikto_safe_web":
        return f"NIKTO LAB — {data.get('target')}:{data.get('port')}\n{data.get('report') or 'Sem achados reportados.'}"
    return json.dumps(data, ensure_ascii=False, indent=2)


_MANAGER: KaliBridgeManager | None = None


def set_kali_bridge_manager(manager: KaliBridgeManager) -> None:
    global _MANAGER
    _MANAGER = manager


def kali_bridge_manager() -> KaliBridgeManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = KaliBridgeManager()
    return _MANAGER


def get_kali_bridge_status() -> dict[str, Any]:
    return kali_bridge_manager().status()


def get_kali_tool_inventory() -> dict[str, Any]:
    return kali_bridge_manager().inventory()


def run_kali_nmap_service_scan(
    target: str,
    ports: list[int] | None = None,
) -> dict[str, Any]:
    return kali_bridge_manager().nmap_service_scan(target, ports)

def run_kali_owner_machine_defensive_audit(
    target: str,
    ports: list[int] | None = None,
) -> dict[str, Any]:
    return kali_bridge_manager().owner_machine_defensive_service_audit(target, ports)


def run_kali_whatweb_fingerprint(
    target: str,
    port: int = 80,
    https: bool = False,
) -> dict[str, Any]:
    return kali_bridge_manager().whatweb_fingerprint(target, port, https)


def run_kali_nikto_safe_web_scan(
    target: str,
    port: int = 80,
    https: bool = False,
) -> dict[str, Any]:
    return kali_bridge_manager().nikto_safe_web_scan(target, port, https)


def get_kali_vm_status() -> dict[str, Any]:
    return kali_bridge_manager().vm_status()

def start_kali_vm() -> dict[str, Any]:
    return kali_bridge_manager().start_vm()

def open_kali_activity_console() -> dict[str, Any]:
    return kali_bridge_manager().open_activity_console()
