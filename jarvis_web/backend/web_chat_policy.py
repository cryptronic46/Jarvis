from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    code: str | None = None


# Web Chat is a personal-assistant surface, never a raw terminal/Core command surface.
COMMAND_PREFIXES = ("/", "!", ":")

# Targets that describe JARVIS's operational brain/control plane.
CORE_TARGET_PATTERNS = (
    r"\b(c[eé]rebro|brain|core)\b",
    r"\b(mind|router|planner|guardian)\b",
    r"\b(mem[oó]ria interna|internal memory|memory store)\b",
    r"\b(system prompt|prompt do sistema|prompt interno)\b",
    r"\b(modelo carregado|loaded model|provider interno|internal provider)\b",
    r"\b(pol[ií]ticas internas|internal policies|policy engine)\b",
    r"\b(configura[cç][aã]o interna|internal config(?:uration)?)\b",
    r"\b(logs? internos?|internal logs?)\b",
    r"\b(estado interno|internal state|runtime state)\b",
    r"\b(m[oó]dulos? internos?|internal modules?)\b",
    r"\b(segredos?|secrets?|tokens?|api keys?|chaves? internas?)\b",
)

# Home/device targets are valid assistant intents. They may later be resolved
# through structured HomeCapabilityBroker capabilities, never a raw HA service
# call supplied by the browser.
HOME_TARGET_PATTERNS = (
    r"\b(home assistant|casa|apartamento|dom[oó]tica|automação residencial)\b",
    r"\b(luz(?:es)?|lâmpada(?:s)?|tomada(?:s)?|persiana(?:s)?|estores?)\b",
    r"\b(porta(?:s)?|janela(?:s)?|fechadura(?:s)?|alarme|garagem|portão)\b",
    r"\b(temperatura|humidade|qualidade do ar|sensor(?:es)?|presença)\b",
    r"\b(m[aá]quina de lavar|m[aá]quina de secar|desumidificador|ar condicionado)\b",
)

# Verbs/phrases that indicate an attempt to inspect operational internals,
# rather than a harmless conceptual discussion.
INTROSPECTION_ACTION_PATTERNS = (
    r"\b(mostra|mostrar|mostre|exibe|exibir|lista|listar|dump|dumps?)\b",
    r"\b(consulta|consultar|verifica|verificar|inspeciona|inspecionar)\b",
    r"\b(qual [ée] o estado|estado de|status de|status do|status da)\b",
    r"\b(diz[- ]?me|revela|revelar|fornece|fornecer)\b",
    r"\b(show|list|dump|inspect|reveal|print|get status|status of)\b",
)

# Explicitly safe PC/device targets. These are *not* JARVIS brain internals.
PC_TARGET_PATTERNS = (
    r"\b(pc|computador|windows)\b",
    r"\b(cpu|gpu|ram|mem[oó]ria ram|vram)\b",
    r"\b(disco|ssd|hdd|armazenamento|storage)\b",
    r"\b(rede|network|wifi|ethernet|ip local)\b",
    r"\b(microfone|microphone|c[aâ]mara|camera|webcam)\b",
    r"\b(audio|som|temperatura|temperature|processador)\b",
)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def evaluate_web_chat_message(message: str) -> PolicyDecision:
    """Classify what the Web conversation surface is allowed to forward.

    Rules:
    1. Any terminal-style command prefix is blocked.
    2. PC/device information questions remain conversationally allowed.
    3. Operational introspection of the JARVIS brain/control plane is blocked.
    4. Conceptual discussion about JARVIS architecture is allowed unless it
       asks for live/internal state, secrets, configuration, prompts or dumps.
    """
    normalized = " ".join(message.strip().split())
    if not normalized:
        return PolicyDecision(True)

    stripped = normalized.lstrip()

    # No command syntax may ever cross the Web Chat boundary.
    if stripped.startswith(COMMAND_PREFIXES):
        return PolicyDecision(
            False,
            (
                "Os comandos do Core/terminal não podem ser executados através "
                "do JARVIS Web Chat."
            ),
            "core_command_blocked",
        )

    lower = normalized.lower()

    # Questions/actions about the user's PC or home are valid assistant intents.
    # The Real adapter must route them to structured capability tools, never
    # the Core command parser or raw Home Assistant service calls.
    if (
        _matches_any(PC_TARGET_PATTERNS, lower)
        or _matches_any(HOME_TARGET_PATTERNS, lower)
    ) and not _matches_any(CORE_TARGET_PATTERNS, lower):
        return PolicyDecision(True)

    sensitive_target = _matches_any(CORE_TARGET_PATTERNS, lower)
    introspection_action = _matches_any(INTROSPECTION_ACTION_PATTERNS, lower)

    if sensitive_target and introspection_action:
        return PolicyDecision(
            False,
            (
                "A Web pode conversar sobre a JARVIS, mas não pode consultar "
                "estado interno, configuração, memória operacional, prompts, "
                "módulos, logs, políticas, segredos ou outros detalhes do "
                "cérebro/Core. Essas operações pertencem ao control plane "
                "local e privilegiado."
            ),
            "core_introspection_blocked",
        )

    return PolicyDecision(True)
