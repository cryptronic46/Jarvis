from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

from jarvis_core.security.policy import RiskLevel
from jarvis_core.services.cyber_range import classify_cyber_target
from jarvis_core.services.kali_bridge import (
    get_kali_bridge_status,
    run_kali_nmap_service_scan,
    run_kali_whatweb_fingerprint,
    run_kali_nikto_safe_web_scan,
)
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


DEFAULT_PORTS = [21, 22, 23, 25, 53, 80, 110, 139, 143, 443, 445, 3306, 3389, 5432, 8080, 8443]


class PurpleTeamOrchestrator:
    """Bounded Purple Team coordinator for OWNER-authorized LAB targets.

    0.23 deliberately coordinates discovery/fingerprinting/audit profiles only.
    It does not add exploitation, payload delivery, persistence or arbitrary
    command execution. Those boundaries remain in KaliBridge itself.
    """

    def __init__(self, context: SkillContext) -> None:
        self.context = context
        self.report_path = Path(getattr(
            context.settings, "purple_team_report_path", "memory/purple_team_last.json"
        ))
        self.report_path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _recommendations(services: list[dict[str, Any]], web_reports: list[dict[str, Any]]) -> list[dict[str, str]]:
        recs: list[dict[str, str]] = []
        seen: set[str] = set()

        def add(key: str, severity: str, finding: str, recommendation: str, verification: str) -> None:
            if key in seen:
                return
            seen.add(key)
            recs.append({
                "severity": severity,
                "finding": finding,
                "recommendation": recommendation,
                "verification": verification,
            })

        for row in services:
            try:
                port = int(row.get("port"))
            except Exception:
                continue
            product = " ".join(str(row.get(k) or "") for k in ("name", "product", "version")).strip()
            if port == 23:
                add("telnet", "high", f"Telnet exposto ({product or 'porta 23'}).", "Desativar Telnet e substituir por SSH com autenticação forte.", "Repetir Nmap e confirmar porta 23 fechada.")
            elif port == 21:
                add("ftp", "medium", f"FTP exposto ({product or 'porta 21'}).", "Se não for necessário, remover FTP; caso seja, exigir TLS e restringir origens/contas.", "Repetir scan e validar configuração/necessidade do serviço.")
            elif port == 445:
                add("smb", "medium", "SMB acessível no alvo LAB.", "Confirmar versão SMB, desativar SMBv1, aplicar patches e restringir 445 por firewall ao mínimo necessário.", "Repetir scan e auditoria SMB autorizada; validar firewall/SMBv1.")
            elif port == 3389:
                add("rdp", "medium", "RDP acessível no alvo LAB.", "Restringir RDP, exigir NLA/MFA quando aplicável, patching e regras de firewall específicas.", "Repetir scan e validar NLA/política do host.")
            elif port in {3306, 5432, 1433}:
                add(f"db{port}", "medium", f"Serviço de base de dados exposto na porta {port}.", "Limitar a interface/origens necessárias e impedir exposição desnecessária a outros segmentos.", "Repetir scan a partir da Kali e confirmar a superfície pretendida.")
            elif port in {80, 443, 8080, 8443}:
                add("web", "info", f"Serviço web exposto na porta {port}.", "Rever fingerprint, headers, configuração TLS e achados do scanner web antes de alterar o host.", "Repetir WhatWeb/Nikto após mitigação.")

        for report in web_reports:
            nikto = str(report.get("nikto", {}).get("report") or "").lower()
            if "x-frame-options" in nikto and "not present" in nikto:
                add("xframe", "low", "Nikto sinalizou ausência de X-Frame-Options.", "Definir proteção anti-clickjacking adequada (CSP frame-ancestors e/ou X-Frame-Options).", "Repetir Nikto/inspecionar headers HTTP.")
            if "x-content-type-options" in nikto and "not set" in nikto:
                add("nosniff", "low", "Nikto sinalizou ausência de X-Content-Type-Options.", "Adicionar X-Content-Type-Options: nosniff quando compatível.", "Repetir auditoria de headers.")
        return recs

    def run(self, target: str, ports: list[int] | None = None, include_web_audit: bool = True) -> dict[str, Any]:
        authority = classify_cyber_target(target)
        if not authority.get("authorized") or authority.get("scope") != "LAB":
            return {
                "ok": False,
                "error": "PURPLE_TEAM_TARGET_NOT_LAB",
                "target": target,
                "authority": authority,
            }
        bridge = get_kali_bridge_status()
        if not bridge.get("ok") or not bridge.get("configured") or not bridge.get("ready_scope"):
            return {"ok": False, "error": "KALI_BRIDGE_NOT_READY", "bridge": bridge}
        selected_ports = ports if ports else list(DEFAULT_PORTS)
        selected_ports = [int(p) for p in selected_ports][:64]
        started = datetime.now().astimezone().isoformat(timespec="seconds")
        self.context.events.emit("PURPLE_TEAM_STARTED", target=authority.get("ip"), ports=selected_ports)

        nmap = run_kali_nmap_service_scan(authority["ip"], selected_ports)
        if not nmap.get("ok"):
            report = {
                "ok": False,
                "error": "PURPLE_TEAM_DISCOVERY_FAILED",
                "target": authority.get("ip"),
                "started_at": started,
                "nmap": nmap,
            }
            self._save(report)
            return report

        services = list(nmap.get("open_services") or [])
        web_reports: list[dict[str, Any]] = []
        if include_web_audit:
            web_ports = []
            for row in services:
                try:
                    port = int(row.get("port"))
                except Exception:
                    continue
                service_name = str(row.get("name") or "").lower()
                if port in {80, 443, 8080, 8443} or "http" in service_name:
                    web_ports.append(port)
            for port in web_ports[:4]:
                https = port in {443, 8443}
                fingerprint = run_kali_whatweb_fingerprint(authority["ip"], port, https)
                nikto = run_kali_nikto_safe_web_scan(authority["ip"], port, https)
                web_reports.append({
                    "port": port,
                    "https": https,
                    "whatweb": fingerprint,
                    "nikto": nikto,
                })

        recommendations = self._recommendations(services, web_reports)
        completed = datetime.now().astimezone().isoformat(timespec="seconds")
        report = {
            "ok": True,
            "mode": "bounded_purple_team",
            "scope": "LAB",
            "target": authority.get("ip"),
            "started_at": started,
            "completed_at": completed,
            "phases": [
                "authority_revalidation",
                "service_discovery",
                "web_fingerprinting" if web_reports else "web_fingerprinting_skipped",
                "defensive_interpretation",
            ],
            "nmap": nmap,
            "open_services": services,
            "web_reports": web_reports,
            "recommendations": recommendations,
            "validation_instruction": "Aplica a mitigação no LAB e usa validate_purple_team_mitigation para repetir os mesmos testes.",
            "boundaries": [
                "no exploitation",
                "no payload delivery",
                "no persistence",
                "no arbitrary Kali shell",
                "LAB targets only",
            ],
        }
        self._save(report)
        self.context.events.emit(
            "PURPLE_TEAM_FINISHED",
            target=authority.get("ip"),
            open_services=len(services),
            web_services=len(web_reports),
            recommendations=len(recommendations),
        )
        return report

    def validate(self, target: str = "") -> dict[str, Any]:
        previous = self.last_report()
        if not previous.get("ok"):
            return {"ok": False, "error": "NO_PREVIOUS_PURPLE_TEAM_REPORT"}
        wanted = str(target or previous.get("target") or "").strip()
        ports = []
        for row in previous.get("nmap", {}).get("requested_ports") or []:
            try:
                ports.append(int(row))
            except Exception:
                pass
        if not ports:
            ports = [int(row.get("port")) for row in previous.get("open_services") or [] if row.get("port")]
        current = self.run(wanted, ports or None, include_web_audit=True)
        if not current.get("ok"):
            return current
        before = {int(row.get("port")) for row in previous.get("open_services") or [] if row.get("port")}
        after = {int(row.get("port")) for row in current.get("open_services") or [] if row.get("port")}
        return {
            "ok": True,
            "target": wanted,
            "before_open_ports": sorted(before),
            "after_open_ports": sorted(after),
            "closed_since_previous": sorted(before - after),
            "new_since_previous": sorted(after - before),
            "current_report": current,
        }

    def _save(self, report: dict[str, Any]) -> None:
        self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def last_report(self) -> dict[str, Any]:
        try:
            data = json.loads(self.report_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"ok": False, "error": "INVALID_REPORT"}
        except FileNotFoundError:
            return {"ok": False, "error": "NO_REPORT"}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__, "message": str(exc)}

    def status(self) -> dict[str, Any]:
        last = self.last_report()
        return {
            "ok": True,
            "report_path": str(self.report_path),
            "last_target": last.get("target") if isinstance(last, dict) else None,
            "last_completed_at": last.get("completed_at") if isinstance(last, dict) else None,
            "profiles": ["nmap_services", "whatweb_fingerprint", "nikto_safe_web"],
            "lab_only": True,
            "arbitrary_shell": False,
            "exploitation": False,
        }


class PurpleTeamSkill(Skill):
    skill_id = "purple_team"
    name = "Purple Team Orchestrator"
    version = "1.0.0"
    description = "Coordinate bounded LAB recon, web audit, defensive interpretation and retest."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.service = PurpleTeamOrchestrator(context)
        context.services["purple_team"] = self.service

    def tools(self) -> list[SkillTool]:
        markers = ("purple team", "purple", "testa a vm", "audita a vm", "laboratório", "laboratorio", "kali", "pentest", "retest", "mitigação", "mitigacao")
        return [
            SkillTool("get_purple_team_status", "Read Purple Team orchestration status and safety boundaries.", self.service.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("run_purple_team_assessment", "Coordinate bounded discovery/fingerprinting/web audit only against an OWNER-authorized LAB target, then produce defensive recommendations.", self.service.run, {"type":"object","properties":{"target":{"type":"string"},"ports":{"type":"array","items":{"type":"integer","minimum":1,"maximum":65535},"maxItems":64},"include_web_audit":{"type":"boolean"}},"required":["target"]}, RiskLevel.LOW, markers),
            SkillTool("get_last_purple_team_report", "Read the most recent local Purple Team LAB report.", self.service.last_report, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("validate_purple_team_mitigation", "Repeat the previous bounded LAB assessment after mitigation and compare exposed ports/results.", self.service.validate, {"type":"object","properties":{"target":{"type":"string"}}}, RiskLevel.LOW, markers),
        ]

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.service.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return PurpleTeamSkill(context)
