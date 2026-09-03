from __future__ import annotations

from pathlib import Path
from typing import Any
import re


def _status_word(value: str | None) -> str:
    value = str(value or "").upper()
    return {
        "READY": "Pronto",
        "NOT_CONFIGURED": "Não configurado",
        "ERROR": "Erro",
    }.get(value, value.title() if value else "Desconhecido")


def format_profile_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui ler o perfil."

    active = data.get("active_profile") or {}
    profiles = data.get("profiles") or []
    role = str(active.get("role") or "").lower()
    role_text = "Proprietário" if role == "owner" else "Restrito"

    lines = [
        "PERFIL",
        f"{active.get('display_name') or 'Utilizador'} · {role_text}",
        f"Tratamento: {active.get('address_as') or 'Senhor'}",
        (
            "Permissões: acesso total"
            if active.get("allowed_tools") == ["*"]
            else f"Permissões: {len(active.get('allowed_tools') or [])} ferramentas autorizadas"
        ),
        (
            "Voice ID: associado ao perfil"
            if active.get("voice_profile")
            else "Voice ID: ainda não associado"
        ),
        (
            "Autenticação automática por voz: ativa"
            if data.get("voice_binding_enforcement")
            else "Autenticação automática por voz: em observação"
        ),
    ]
    restricted = sum(
        1
        for row in profiles
        if str(row.get("role") or "").lower() == "restricted"
    )
    if restricted:
        lines.append(f"Perfis restritos configurados: {restricted}")

    lines.append("Detalhes: /profile status raw")
    return "\n".join(lines)


def format_profile_permissions(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"Não consegui ler as permissões: {data.get('error','erro')}."

    tools = data.get("allowed_tools") or []
    routines = data.get("allowed_routines") or []
    return "\n".join([
        "PERMISSÕES",
        f"Perfil: {data.get('profile')}",
        f"Função: {data.get('role')}",
        "Ferramentas: acesso total" if tools == ["*"] else f"Ferramentas autorizadas: {len(tools)}",
        "Rotinas: acesso total" if routines == ["*"] else f"Rotinas autorizadas: {len(routines)}",
        "Detalhes: /profile perms raw",
    ])


def format_network_inventory(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui atualizar o inventário da rede."

    devices = data.get("devices") or []
    active = [row for row in devices if row.get("active")]
    inactive = [row for row in devices if not row.get("active")]
    new_active = [
        row
        for row in data.get("new_devices") or []
        if row.get("active")
    ]

    lines = [
        "REDE — INVENTÁRIO",
        f"Ativos: {len(active)} · Conhecidos: {len(devices)}",
    ]
    if active:
        lines.append("Agora na rede:")
        for row in active[:8]:
            label = row.get("label") or "Sem nome"
            lines.append(
                f"- {label} · {row.get('ip') or 'IP desconhecido'}"
            )
    else:
        lines.append("Nenhum dispositivo ativo conhecido.")

    if new_active:
        lines.append(f"Novos ativos nesta leitura: {len(new_active)}")
    if inactive:
        lines.append(f"Conhecidos mas inativos: {len(inactive)}")

    lines.append(
        "Nomear: /network name IP Nome · Detalhes: /network inventory raw"
    )
    return "\n".join(lines)


def format_watch_baseline(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui criar a baseline."

    fp = data.get("fingerprint") or {}
    return "\n".join([
        "SECURITY WATCH — BASELINE CRIADA",
        f"Administradores adicionais: {len(fp.get('other_admin_sids') or [])}",
        f"Sessões remotas: {len(fp.get('remote_sessions') or [])}",
        f"Software de acesso remoto: {len(fp.get('remote_access_software') or [])}",
        f"Firewall: {'OK' if fp.get('firewall_all_enabled') is True else 'Atenção'}",
        f"Defender: {'OK' if fp.get('defender_realtime_enabled') is True else 'Atenção'}",
        f"RDP: {'Ativo' if fp.get('rdp_enabled') is True else 'Desativado' if fp.get('rdp_enabled') is False else 'Não confirmado'}",
        f"Assistência Remota: {'Ativa' if fp.get('remote_assistance_enabled') is True else 'Desativada' if fp.get('remote_assistance_enabled') is False else 'Não confirmada'}",
        f"Dispositivos LAN ativos registados: {len(fp.get('active_lan_macs') or [])}",
        "A partir de agora, alterações relevantes serão comparadas com esta baseline.",
        "Detalhes: /watch baseline raw",
    ])


def format_watch_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui ler o Security Watch."

    alerts = data.get("alerts") or []
    lines = [
        "SECURITY WATCH",
        f"Baseline: {'Ativa' if data.get('baseline_exists') else 'Ainda não criada'}",
        f"Última verificação: {data.get('last_check') or 'Ainda não realizada'}",
        f"Alertas: {len(alerts)}",
    ]
    if alerts:
        for alert in alerts[:5]:
            lines.append(
                f"- {str(alert.get('severity') or 'info').upper()}: "
                f"{alert.get('message')}"
            )
    else:
        lines.append("Nenhuma alteração de segurança pendente.")
    lines.append("Detalhes: /watch status raw")
    return "\n".join(lines)


def format_watch_check(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui verificar a baseline."

    if data.get("baseline_created"):
        return "\n".join([
            "SECURITY WATCH",
            "Ainda não existia baseline; foi criada agora.",
            "A próxima verificação poderá detetar alterações.",
            "Detalhes: /watch check raw",
        ])

    alerts = data.get("alerts") or []
    lines = [
        "SECURITY WATCH — VERIFICAÇÃO",
        f"Alterações relevantes: {len(alerts)}",
    ]
    if alerts:
        for alert in alerts[:8]:
            lines.append(
                f"- {str(alert.get('severity') or 'info').upper()}: "
                f"{alert.get('message')}"
            )
    else:
        lines.append("Sem alterações relevantes face à baseline.")
    lines.append("Detalhes: /watch check raw")
    return "\n".join(lines)


def format_file_index(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("message") or "Não consegui indexar os ficheiros."

    roots = []
    for root in data.get("roots") or []:
        raw = str(root).rstrip("/\\")
        leaf = re.split(r"[\\/]+", raw)[-1] if raw else raw
        roots.append(leaf or raw)
    return "\n".join([
        "FICHEIROS — ÍNDICE PRONTO",
        f"Ficheiros indexados: {data.get('indexed', 0)}",
        f"Ignorados por erro/permissão: {data.get('skipped', 0)}",
        "Pastas: " + (", ".join(roots) if roots else "Nenhuma"),
        "Pesquisar: /files find TEXTO",
        "Detalhes: /files index raw",
    ])


def format_integrations(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui ler as integrações."

    rows = [
        ("Agenda local", data.get("local_agenda")),
        ("Google Calendar", data.get("google_calendar")),
        ("Email", data.get("email")),
        ("Smart Home", data.get("smart_home")),
    ]
    lines = ["INTEGRAÇÕES"]
    ready = 0
    for label, value in rows:
        value = value or {}
        if value.get("configured") is True or value.get("status") == "READY":
            ready += 1
        lines.append(f"{label}: {_status_word(value.get('status'))}")
    lines.append(f"Prontas: {ready}/{len(rows)}")
    lines.append("Detalhes: /integrations raw")
    return "\n".join(lines)


def format_dashboard_preview(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui criar a pré-visualização do dashboard."

    profile = data.get("profile") or {}
    privacy = data.get("privacy") or {}
    env = data.get("environment") or {}
    weather = env.get("weather") or {}
    marine = env.get("marine") or {}
    pc = data.get("pc_health") or {}
    memory = pc.get("memory") or {}
    gpu = pc.get("gpu") or {}
    agenda = data.get("agenda") or {}
    watch = data.get("security_watch") or {}
    network = data.get("network") or {}
    integrations = data.get("integrations") or {}

    integration_rows = [
        integrations.get("local_agenda") or {},
        integrations.get("google_calendar") or {},
        integrations.get("email") or {},
        integrations.get("smart_home") or {},
    ]
    ready = sum(
        1
        for row in integration_rows
        if row.get("configured") is True or row.get("status") == "READY"
    )
    alerts = watch.get("alerts") or []
    location = (env.get("location") or {}).get("label") or "Local"

    return "\n".join([
        "DASHBOARD — PRÉ-VISUALIZAÇÃO",
        (
            f"{profile.get('address_as') or 'Senhor'} "
            f"{profile.get('display_name') or ''} · "
            f"{str(profile.get('role') or '').title()}"
        ).strip(),
        (
            f"{location}: {weather.get('temperature_c','?')} °C · "
            f"{weather.get('relative_humidity_percent','?')}% humidade · "
            f"{weather.get('condition','desconhecido')}"
        ),
        (
            f"Mar: {marine.get('state','desconhecido')} · "
            f"{marine.get('wave_height_m','?')} m"
        ),
        (
            f"PC: {str(pc.get('overall') or 'desconhecido').upper()} · "
            f"CPU {pc.get('cpu_percent','?')}% · "
            f"RAM {memory.get('percent','?')}% · "
            f"GPU {gpu.get('temperature_c','?')} °C"
        ),
        (
            f"Segurança: {'baseline ativa' if watch.get('baseline_exists') else 'sem baseline'} · "
            f"{len(alerts)} alerta(s)"
        ),
        f"Rede: {network.get('active_count',0)} dispositivo(s) ativo(s)",
        (
            f"Agenda: {agenda.get('today_count',0)} hoje · "
            f"{agenda.get('pending_count',0)} pendente(s)"
        ),
        (
            f"Privacidade: {'modo privado' if privacy.get('privacy_mode') else 'normal'} · "
            f"Pesquisa externa {'permitida' if privacy.get('external_network_research_allowed', privacy.get('cloud_allowed')) else 'bloqueada'}"
        ),
        f"Integrações: {ready}/{len(integration_rows)} prontas",
        "Dados técnicos para a futura UI: /dashboard raw",
    ])


def format_routines(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui listar as rotinas."
    rows = data.get("routines") or []
    lines = ["ROTINAS"]
    for row in rows:
        lines.append(f"- {row.get('id')} · {row.get('label')}")
    if not rows:
        lines.append("Nenhuma rotina configurada.")
    return "\n".join(lines)


def format_memory_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui ler a memória."
    profile = data.get("profile") or {}
    return "\n".join([
        "MEMÓRIA",
        f"Perfil: {profile.get('name','Tiago')}",
        f"Factos guardados: {data.get('fact_count',0)}",
        "Armazenamento: local",
        "Detalhes: /memory status raw",
    ])


def format_cyber_knowledge_status(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui ler a Cyber Knowledge Vault."

    sources = data.get("sources") or []
    official = sum(
        int(row.get("documents") or 0)
        for row in sources
        if str(row.get("trust") or "").startswith("official")
    )
    curated = sum(
        int(row.get("documents") or 0)
        for row in sources
        if row.get("trust") == "curated"
    )
    user_docs = sum(
        int(row.get("documents") or 0)
        for row in sources
        if row.get("trust") == "user-provided"
    )
    sync = data.get("sync_state") or {}
    return "\n".join([
        "CYBER KNOWLEDGE VAULT",
        f"Documentos: {data.get('documents',0)}",
        f"Fontes oficiais: {official} registos",
        f"Base curada JARVIS: {curated}",
        f"Documentos locais importados: {user_docs}",
        f"Índice full-text: {'Ativo' if data.get('fts5') else 'Fallback SQL'}",
        f"Base de dados: {data.get('database_mb',0)} MB",
        f"Última atualização: {sync.get('last_successful_sync') or 'ainda não sincronizada online'}",
        "Atualizar: /cyber knowledge sync",
        "ATT&CK completo: /cyber knowledge sync full",
    ])


def format_cyber_knowledge_search(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Pesquisa inválida."
    rows = data.get("results") or []
    if not rows:
        return "Não encontrei conhecimento local para essa pesquisa."

    lines = [f"CYBER KNOWLEDGE — {len(rows)} resultado(s)"]
    for row in rows[:8]:
        source = row.get("publisher") or row.get("source_id") or "Fonte"
        ext = row.get("external_id") or ""
        suffix = f" · {ext}" if ext and ext != "root" else ""
        lines.append(
            f"- {row.get('title')} · {source}{suffix}"
        )
    lines.append("O JARVIS pode usar estes registos nas respostas técnicas.")
    return "\n".join(lines)


def format_cyber_knowledge_sync(data: dict[str, Any]) -> str:
    results = data.get("results") or []
    lines = [
        "CYBER KNOWLEDGE — SINCRONIZAÇÃO",
        (
            f"Fontes: {data.get('sources_ok',0)} OK · "
            f"{data.get('sources_failed',0)} falharam"
        ),
    ]
    for row in results:
        status = "OK" if row.get("ok") else "ERRO"
        detail = (
            f"{row.get('documents',0)} registos"
            if row.get("ok")
            else row.get("message") or row.get("error") or "erro"
        )
        lines.append(
            f"- {status} · {row.get('source_name') or row.get('source_id')}: {detail}"
        )
    stats = data.get("stats") or {}
    lines.append(f"Total guardado: {stats.get('documents',0)} documentos")
    return "\n".join(lines)
