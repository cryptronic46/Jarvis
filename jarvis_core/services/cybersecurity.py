from __future__ import annotations

from typing import Any

from jarvis_core.tools.security_audit import run_security_audit


CURRICULUM = [
    {"id": 1, "topic": "Identidade, contas, UAC e privilégios"},
    {"id": 2, "topic": "TCP/IP, sub-redes, gateway, ARP, DNS e DHCP"},
    {"id": 3, "topic": "Portas, sockets, processos e serviços"},
    {"id": 4, "topic": "Firewall e Microsoft Defender"},
    {"id": 5, "topic": "RDP, SMB e acesso remoto"},
    {"id": 6, "topic": "Event Logs e investigação no Windows"},
    {"id": 7, "topic": "Persistência e arranque automático"},
    {"id": 8, "topic": "Patching, vulnerabilidades e hardening"},
    {"id": 9, "topic": "Inventário e segurança da rede doméstica"},
    {"id": 10, "topic": "Baselines e deteção de alterações"},
    {"id": 11, "topic": "Testes éticos em ambiente autorizado"},
    {"id": 12, "topic": "Resposta a incidentes"},
]


def get_cyber_mentor_status() -> dict[str, Any]:
    return {
        "ok": True,
        "role": "cybersecurity_teacher_and_local_auditor",
        "language": "pt-PT",
        "authorized_default_scope": [
            "este PC Windows",
            "a rede local do utilizador",
            "laboratórios/ambientes explicitamente autorizados",
        ],
        "teaching_style": [
            "conceito",
            "estado no sistema quando relevante",
            "evidência",
            "risco",
            "teste seguro",
            "recomendação",
            "verificação",
        ],
        "audit_principles": [
            "OWNER defines the objective; Core enforces target scope",
            "LAB permits controlled active tests after explicit scope authorization",
            "OWNER_MACHINE remains defensive-audit/hardening scope",
            "read-only first",
            "evidence before conclusions",
            "separate fact from inference",
            "do not call normal Internet traffic an intrusion",
            "prefer native Windows/local evidence",
        ],
        "curriculum_topics": len(CURRICULUM),
    }


def get_cyber_curriculum() -> dict[str, Any]:
    return {"ok": True, "curriculum": CURRICULUM}


def get_cybersecurity_posture() -> dict[str, Any]:
    audit = run_security_audit()
    if not audit.get("ok"):
        return audit

    summary = audit.get("summary") or {}
    posture = audit.get("windows_security") or {}
    network = audit.get("network") or {}
    defender = posture.get("defender") or {}

    observations = []

    observations.append({
        "topic": "least_privilege",
        "state": (
            "good"
            if summary.get("only_current_enabled_admin_detected") is True
            else "attention"
        ),
        "evidence": (
            "Só o utilizador atual foi confirmado como administrador habilitado."
            if summary.get("only_current_enabled_admin_detected") is True
            else "Existem outros administradores habilitados ou de estado indeterminado."
        ),
        "teaching_point": (
            "Menos contas administrativas reduzem a superfície de abuso de privilégios."
        ),
    })

    rdp = posture.get("rdp_enabled")
    observations.append({
        "topic": "rdp",
        "state": "good" if rdp is False else "attention" if rdp is True else "unknown",
        "evidence": (
            "RDP está desativado."
            if rdp is False
            else "RDP está ativo."
            if rdp is True
            else "Estado do RDP não confirmado."
        ),
        "teaching_point": (
            "Um serviço remoto desnecessário desligado reduz a superfície de ataque."
        ),
    })

    firewall = posture.get("firewall") or []
    firewall_ok = bool(
        firewall
        and all(row.get("enabled") is True for row in firewall)
    )
    observations.append({
        "topic": "firewall",
        "state": "good" if firewall_ok else "attention",
        "evidence": (
            "Todos os perfis de Firewall reportam ativos."
            if firewall_ok
            else "Nem todos os perfis de Firewall foram confirmados ativos."
        ),
        "teaching_point": (
            "A firewall aplica regras ao tráfego e deve ser interpretada em conjunto com os serviços expostos."
        ),
    })

    defender_rt = defender.get("real_time_protection_enabled")
    observations.append({
        "topic": "defender",
        "state": (
            "good"
            if defender_rt is True
            else "attention"
            if defender_rt is False
            else "unknown"
        ),
        "evidence": (
            "Proteção em tempo real ativa."
            if defender_rt is True
            else "Proteção em tempo real desativada."
            if defender_rt is False
            else "Estado do Defender não confirmado."
        ),
        "teaching_point": (
            "Antimalware é apenas uma camada; patching, privilégios e comportamento continuam importantes."
        ),
    })

    remote = bool(summary.get("active_remote_access_detected"))
    observations.append({
        "topic": "remote_access",
        "state": "attention" if remote else "good",
        "evidence": (
            f"RDP/remoto={summary.get('remote_interactive_session_count',0)}, "
            f"SMB={summary.get('smb_session_count',0)}."
            if remote
            else "Não há sessão RDP/SMB ativa detetada."
        ),
        "teaching_point": (
            "Sessões remotas são evidência muito mais forte de acesso humano do que simples ligações HTTPS."
        ),
    })

    counts = network.get("counts") or {}
    return {
        "ok": True,
        "level": summary.get("level") or "ok",
        "observations": observations,
        "network_context": {
            "active_lan_devices": counts.get(
                "lan_devices_active",
                counts.get("lan_devices", 0),
            ),
            "public_established_connections": counts.get(
                "public_established",
                0,
            ),
        },
        "next_lessons": [
            "Identidade/UAC e privilégio mínimo",
            "Portas/processos e ligações de rede",
            "Event Logs e evidência",
        ],
    }


def format_cyber_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Modo professor de cibersegurança indisponível."
    return "\n".join([
        "CIBERSEGURANÇA",
        "Papel: Professor + Auditor local",
        "Âmbito: OWNER_MACHINE defensivo + LAB explicitamente autorizado",
        "Método: evidência → risco → explicação → teste seguro → recomendação",
        "Auditoria: READ_ONLY primeiro",
        f"Currículo: {data.get('curriculum_topics',0)} módulos",
        "Começar: /cyber curriculum",
    ])


def format_cyber_curriculum(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui carregar o currículo."
    lines = ["CURRÍCULO DE CIBERSEGURANÇA"]
    for row in data.get("curriculum") or []:
        lines.append(f"{row.get('id')}. {row.get('topic')}")
    lines.append(
        "Exemplo: «Jarvis, ensina-me o módulo 3 usando o meu PC como exemplo.»"
    )
    return "\n".join(lines)


def format_cyber_posture(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui avaliar a postura."

    level = {
        "ok": "OK",
        "attention": "ATENÇÃO",
        "critical": "CRÍTICO",
    }.get(str(data.get("level") or "ok").lower(), "OK")

    lines = [
        "CIBERSEGURANÇA — POSTURA",
        f"Estado: {level}",
    ]
    for row in data.get("observations") or []:
        symbol = {
            "good": "OK",
            "attention": "ATENÇÃO",
            "unknown": "DESCONHECIDO",
        }.get(row.get("state"), "INFO")
        lines.append(
            f"- {symbol} · {row.get('topic')}: {row.get('evidence')}"
        )
    lines.append(
        "Diga «Jarvis, explica esta auditoria como professor» para transformar os achados numa aula."
    )
    return "\n".join(lines)
