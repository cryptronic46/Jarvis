from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from time import sleep, monotonic
from threading import Thread, RLock

from jarvis_core import __version__
from jarvis_core.core.config import Settings
from jarvis_core.core.events import Event, EventBus
from jarvis_core.core.tool_registry import ToolRegistry
from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.fast_router import FastCommandRouter
from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.core.generation_result import GenerationStatus
from jarvis_core.security.policy import SecurityPolicy
from jarvis_core.skills import SkillContext, SkillManager
from jarvis_core.services.learning_followup import (
    get_learning_followup_context,
)
from jarvis_core.services.telemetry import TelemetryService
from jarvis_core.services.silence_latch import SilenceLatchService
from jarvis_core.services.activity_trace import ActivityTraceService
from jarvis_core.services.idle_mind import IdleMindService
from jarvis_core.services.user_memory import store as user_memory_store
from jarvis_core.services.request_intent import sanitize_assistant_text
from jarvis_core.services.profiles import manager as profile_manager
from jarvis_core.services.context_store import context_store
from jarvis_core.services.agenda import agenda_store
from jarvis_core.services.reminders import ReminderService
from jarvis_core.services.security_watch import SecurityWatchService
from jarvis_core.services.routines import routine_manager
from jarvis_core.services.network_inventory import network_inventory
from jarvis_core.services.file_index import configure_file_index
from jarvis_core.services.integrations import integration_registry
from jarvis_core.tools.pc_health import format_pc_health
from jarvis_core.services.presentation import (
    format_profile_status,
    format_profile_permissions,
    format_network_inventory,
    format_watch_baseline,
    format_watch_status,
    format_watch_check,
    format_file_index,
    format_integrations,
    format_dashboard_preview,
    format_routines,
    format_memory_status,
    format_cyber_knowledge_status,
    format_cyber_knowledge_search,
    format_cyber_knowledge_sync,
)
from jarvis_core.services.cybersecurity import (
    get_cyber_mentor_status,
    get_cyber_curriculum,
    get_cybersecurity_posture,
    format_cyber_status,
    format_cyber_curriculum,
    format_cyber_posture,
)
from jarvis_core.services.cyber_knowledge import (
    CyberKnowledgeService,
    configure_cyber_knowledge_egress,
    cyber_vault,
)
from jarvis_core.services.book_library import (
    BookLibraryService,
    configure_book_library,
    format_book_library_search,
    format_book_library_status,
    format_book_library_sync,
)
from jarvis_core.services.system_cyber_audit import (
    analyze_system_cybersecurity,
    format_system_cyber_audit,
)
from jarvis_core.services.deep_network_inspection import (
    inspect_network_deep,
    format_deep_network_inspection,
)
from jarvis_core.services.cyber_range import (
    CyberRangeManager,
    set_cyber_range_manager,
    format_cyber_range_status,
    format_lab_probe,
)
from jarvis_core.services.kali_bridge import (
    KaliBridgeManager,
    set_kali_bridge_manager,
    format_kali_bridge_status,
    format_kali_inventory,
    format_kali_scan,
)
from jarvis_core.services.companion_presence import CompanionPresenceService
from jarvis_core.services.relational_presence import relational_presence
from jarvis_core.services.semantic_intent import (
    local_pdf_library_sync_requested,
    resolve_semantic_request,
)
from jarvis_core.services.synthetic_self import synthetic_self
from jarvis_core.services.personal_cognition import (
    personal_cognition,
    ProactivePresenceService,
)
from jarvis_core.services.performance import PerformanceGovernor
from jarvis_core.services.local_research import LocalResearchEngine
from jarvis_core.services.windows_block_audit import (
    audit_windows_blocked_files,
    format_windows_block_audit,
)
from jarvis_core.services.learning_gap import (
    freshness_days_for_topic,
    knowledge_state,
)
from jarvis_core.services.autonomy import (
    AutonomyGuardian,
    authorized_learning,
    set_autonomy_guardian,
)
from jarvis_core.services.external_learning import (
    configure_external_learning_runtime,
)
from jarvis_core.tools.environment_tools import configure_environment_egress
from jarvis_core.tools.security_audit import (
    format_security_overview,
    format_security_full,
    format_network_overview,
    format_network_devices,
)
from jarvis_core.tools.windows_actions import AppRegistry
from jarvis_core.runtime import (
    JarvisRuntime,
    ProcessRequestResult,
    route_runtime_request,
)
from jarvis_core.bootstrap import build_application





BANNER_TEMPLATE = """
========================================
 JARVIS CORE {version}
========================================
"""


def local_pdf_library_learning_requested(text: str) -> bool:
    """Compatibility wrapper around the semantic PDF-library classifier."""
    return local_pdf_library_sync_requested(text)


VISIBLE_EVENTS = {
    "INPUT_RECEIVED":"INPUT",
    "THINKING_STARTED":"CORE",
    "MODEL_REQUEST":"LLM",
    "TOOL_CALLS_REQUESTED":"ROUTER",
    "TOOL_EXECUTING":"TOOL",
    "TOOL_FINISHED":"TOOL",
    "RESPONSE_READY":"CORE",
    "MODEL_ERROR":"ERROR",
    "CONFIRMATION_REQUIRED":"SEC",
    "TOOL_BLOCKED":"SEC",
    "FRESHNESS_GUARD_TRIGGERED":"GUARD",
    "FAST_PATH_HIT":"FAST",
    "LLM_PRELOADED":"WARM",
    "LLM_PRELOAD_FAILED":"WARM",
    "HYBRID_ROUTE":"ROUTE",
    "CLOUD_REQUEST":"CLOUD",
    "CLOUD_RESPONSE":"CLOUD",
    "CLOUD_ERROR":"CLOUD",
    "CLOUD_FALLBACK_LOCAL":"ROUTE",
    "LOCAL_ERROR_ESCALATION":"ROUTE",
    "CLOUD_LOCAL_TOOL_REQUEST":"CLOUD",
    "EPISTEMIC_GAP_ASSESSED":"LEARN",
    "AUTHORIZED_EXTERNAL_LEARNING_STORED":"LEARN",
    "EXPERT_CLOUD_REQUEST":"EXPERT",
    "EXPERT_CLOUD_RESPONSE":"EXPERT",
    "EXPERT_CLOUD_ERROR":"EXPERT",
    "LOCAL_EXPERT_SYNTHESIS_STARTED":"EXPERT",
    "LOCAL_EXPERT_SYNTHESIS_FINISHED":"EXPERT",
    "LOCAL_EXPERT_SYNTHESIS_ERROR":"EXPERT",
    "SILENCE_LATCHED":"SILENCE",
    "SILENCE_RELEASED":"SILENCE",
    "SILENCE_OUTPUT_SUPPRESSED":"SILENCE",
    "PROACTIVE_MESSAGE":"MIND",
    "DESKTOP_INTEGRATION_READY":"DESKTOP",
    "DESKTOP_INTEGRATION_ERROR":"DESKTOP",
    "DESKTOP_SCREEN_CAPTURED":"DESKTOP",
    "SKILL_LOADED":"SKILL",
    "SKILL_LOAD_FAILED":"SKILL",
    "SYSTEM_GUARDIAN_STARTED":"GUARDIAN",
    "SYSTEM_GUARDIAN_ALERT":"GUARDIAN",
    "SYSTEM_GUARDIAN_OK":"GUARDIAN",
    "SYSTEM_GUARDIAN_ERROR":"GUARDIAN",
    "TASK_PLAN_CREATED":"PLAN",
    "TASK_PLAN_PROGRESS":"PLAN",
    "TASK_PLAN_WAITING_CONFIRMATION":"PLAN",
    "TASK_PLAN_FAILED":"PLAN",
    "TASK_PLAN_ADAPTED":"PLAN",
    "PURPLE_TEAM_STARTED":"PURPLE",
    "PURPLE_TEAM_FINISHED":"PURPLE",
    "VISION_CAPTURED":"VISION",
    "VISION_ANALYZED":"VISION",
    "SELF_REPAIR_STARTED":"REPAIR",
    "SELF_REPAIR_FINISHED":"REPAIR",
    "LIVE_CORE_STATE_STARTED":"HUD",
}


def event_printer(event: Event) -> None:
    label = VISIBLE_EVENTS.get(event.name)
    if not label:
        return
    detail = ""
    if event.name in {"TOOL_EXECUTING","TOOL_FINISHED"}:
        detail = f" {event.data.get('tool')}"
        if event.name == "TOOL_FINISHED":
            detail += " [OK]" if event.data.get("ok") else " [ERROR]"
    elif event.name == "MODEL_REQUEST":
        detail = f" round={event.data.get('round')}"
    elif event.name == "TOOL_CALLS_REQUESTED":
        detail = f" {event.data.get('count')} tool call(s)"
    elif event.name == "CONFIRMATION_REQUIRED":
        detail = f" {event.data.get('tool')} token={event.data.get('token')}"
    elif event.name == "FAST_PATH_HIT":
        detail = f" route={event.data.get('route')} tool={event.data.get('tool')}"
    elif event.name == "HYBRID_ROUTE":
        detail = (
            f" {event.data.get('route')} "
            f"reason={event.data.get('reason')} "
            f"web={event.data.get('web')}"
        )
    elif event.name == "CLOUD_REQUEST":
        detail = (
            f" model={event.data.get('model')} "
            f"web={event.data.get('web')} deep={event.data.get('deep')}"
        )
    elif event.name == "CLOUD_RESPONSE":
        detail = (
            f" model={event.data.get('model')} "
            f"{event.data.get('elapsed_ms')}ms "
            f"in={event.data.get('input_tokens')} "
            f"out={event.data.get('output_tokens')} "
            f"~${event.data.get('estimated_usd')}"
        )
    elif event.name == "LLM_PRELOADED":
        detail = f" {event.data.get('elapsed_ms')}ms"
    print(f"  [{label:<6}] {event.name}{detail}")


QUICK_TEST_PATTERNS = (
    "test_quiet_terminal.py",
    "test_local_voice_retired.py",
    "test_speed_contract.py",
    "test_runtime_request_pipeline.py",
    "test_memory1_recall_fast_router_guard.py",
)


def run_quick_tests() -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[1]
    total_tests = 0
    completed_patterns = []

    for pattern in QUICK_TEST_PATTERNS:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
                "-p",
                pattern,
                "-q",
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
            errors="replace",
        )

        output = "\n".join(
            part.strip()
            for part in (
                result.stdout,
                result.stderr,
            )
            if part and part.strip()
        )

        match = re.search(
            r"Ran\s+(\d+)\s+tests?",
            output,
        )

        count = (
            int(match.group(1))
            if match is not None
            else 0
        )

        if result.returncode != 0:
            return {
                "ok": False,
                "pattern": pattern,
                "tests": total_tests + count,
                "completed_patterns": tuple(
                    completed_patterns
                ),
                "output": output[-4000:],
            }

        total_tests += count
        completed_patterns.append(pattern)

    return {
        "ok": True,
        "tests": total_tests,
        "patterns": len(completed_patterns),
    }


def help_text() -> str:
    return """
JARVIS \u2014 Terminal t\u00e9cnico

ESSENCIAL
  /status              estado operacional do JARVIS
  /health              estado do c\u00e9rebro/runtime local
  /version             vers\u00e3o do Core
  /memory status       estado da mem\u00f3ria
  /learning status     estado da aprendizagem autorizada

DIAGN\u00d3STICO
  /test quick          smoke-test r\u00e1pido do Core
  /debug on|off        mostrar/ocultar eventos t\u00e9cnicos
  /debug status        estado do debug
  /events              \u00faltimos eventos persistidos
  /telemetry           \u00faltima amostra de telemetria
  /speed               resumo de desempenho
  /vram status         modelos/runtime residentes

SEGURAN\u00c7A / RECUPERA\u00c7\u00c3O
  /security scan       resumo de seguran\u00e7a
  /security blocked files
                       bloqueios Windows atuais
  /repair diagnose     diagn\u00f3stico do JARVIS
  /repair safe         repara\u00e7\u00e3o local segura

AUTORIZA\u00c7\u00d5ES
  /pending             a\u00e7\u00f5es \u00e0 espera de confirma\u00e7\u00e3o
  /confirm TOKEN       confirmar a\u00e7\u00e3o pendente
  /cancel TOKEN        cancelar a\u00e7\u00e3o pendente

COMANDOS
  /help all            cat\u00e1logo completo
  /commands            alias de /help all
  /quit                desligar o Core
""".strip()




def help_text_full() -> str:
    return """
Comandos:
  /help             ajuda
  /health           testar cérebro local JARVIS/modelo
  /version          mostrar versão do Core
  /tools            ferramentas e risco
  /apps             aplicações autorizadas
  /appcheck APP     diagnosticar localização de uma aplicação
  /companion status estado da presença social adaptativa
  /companion on|off ativar/desativar iniciativa social
  /companion flirt on|off permitir/bloquear flirt contextual
  /companion intensity 0..1 intensidade máxima do flirt
  /av cameras       listar câmaras locais disponíveis
  /av camera N      fixar a câmara pelo índice
  /silence status   estado do silêncio conversacional latched
  /silence on|off   silenciar/libertar saída conversacional
  /activity on|off  mostrar/ocultar trace seguro em tempo real
  /activity status  estado + atividade recente (sem chain-of-thought)
  /activity last    últimas decisões/ações observáveis
  /memory status    estado da memória local
  /memory show      mostrar factos guardados
  /profile status   resumo do perfil atual
  /profile status raw detalhe técnico do perfil
  /profile use ID   trocar perfil manualmente (teste)
  /profile perms    permissões do perfil atual
  /watch status     estado do Security Watch
  /watch baseline   criar baseline de segurança
  /watch baseline raw detalhe técnico da baseline
  /watch check      comparar sistema com a baseline
  /pc checkup       check-up de saúde do PC
  /routine list     listar rotinas
  /routine run NOME executar rotina
  /files index      indexar ficheiros locais
  /files index raw  detalhe técnico do índice
  /files find TEXTO procurar ficheiros
  /files recent     ficheiros recentes
  /agenda today     agenda de hoje
  /agenda upcoming  próximos itens
  /agenda add DATA HORA TITULO
  /task add TITULO  criar tarefa local
  /task done ID     concluir tarefa
  /lock             bloquear sessão Windows
  /integrations     resumo das integrações
  /integrations raw detalhe técnico das integrações
  /dashboard data   pré-visualização clean do dashboard
  /dashboard raw    snapshot JSON para futura UI
  /cyber status     papel professor/auditor de cibersegurança
  /cyber curriculum módulos de aprendizagem
  /cyber audit      postura local explicável
  /cyber analyze system análise completa + knowledge vault
  /cyber analyze system full relatório completo e explicável
  /cyber analyze system raw JSON técnico completo
  /cyber inspect network inspeção profunda de listeners/conexões
  /cyber inspect network full detalhe processo/assinatura/firewall
  /cyber inspect network raw JSON técnico completo
  /cyber lab status estado e alvos autorizados do Cyber Range
  /cyber lab add IP_OU_CIDR [NOME] autorizar alvo/rede privada de laboratório
  /cyber lab remove IP_OU_CIDR remover autorização de laboratório
  /cyber lab classify IP classificar alvo antes de testar
  /cyber lab probe IP [P1,P2,...] sondagem TCP controlada em LAB
  /cyber kali status estado da ponte SSH controlada para Kali LAB
  /cyber kali configure IP USER [PORT] [KEY] configurar Kali (OWNER CLI)
  /cyber kali doctor testar ligação SSH sem executar ferramentas ofensivas
  /cyber kali inventory verificar Nmap/WhatWeb/Nikto instalados
  /cyber kali nmap IP [P1,P2,...] descoberta de serviços limitada em LAB
  /cyber kali whatweb IP PORT [https] fingerprint web sem redirects em LAB
  /cyber kali nikto IP PORT [https] auditoria web limitada em LAB
  /cyber kali vm status estado/configuração da VM Kali
  /cyber kali vm configure PROVIDER IDENTIFIER configurar VirtualBox/VMware
  /cyber kali vm start arrancar Kali em modo gráfico
  /cyber kali vm watch abrir consola visível de atividade
  /cyber kali clear remover configuração da ponte Kali
  /mind idle         snapshot instantâneo do estado funcional em idle
  /mind idle reflect reflexão local de alto nível (sem chain-of-thought; unload imediato)
  /mind status       estado de aprendizagem, iniciativa e self-model
  /mind profile      o que o JARVIS aprendeu localmente sobre ti
  /mind reflect      reflexão limitada sobre objetivos/projetos/temas
  /mind self         self-model funcional e limites de consciência
  /mind state        estado sintético: affect, drives, preferências e intenções
  /mind why          motivo da última mensagem espontânea
  /mind learning on|off aprendizagem pessoal local
  /mind proactive on|off iniciativa espontânea
  /autonomy status      autoridade, permissões e modo de autonomia
  /autonomy pending     pedidos autónomos à espera da tua decisão
  /autonomy history     auditoria recente de pedidos/autorizações
  /learning status      estado da biblioteca de aprendizagem web autorizada
  /learning topic TEXTO estado KNOWN/STALE/UNKNOWN de um tema
  /learning search TEXTO pesquisar o que o JARVIS já estudou
  /autonomy revoke      revogar todos os pedidos/grants atuais
  /authorize TOKEN      autorizar uma ação autónoma exata, uma vez
  /deny TOKEN           recusar uma ação autónoma
  /cyber knowledge status estado da base de conhecimento
  /cyber knowledge search TEXTO pesquisar conhecimento armazenado
  /cyber knowledge sync atualizar fontes oficiais
  /cyber knowledge sync full incluir MITRE ATT&CK completo
  /cyber knowledge ingest FICHEIRO importar documento local
  /books status          estado da biblioteca privada de PDFs
  /books sync            indexar livros novos ou alterados
  /books sync force      reconstruir todo o índice dos livros
  /books search TEXTO    pesquisar passagens com livro e página
  /security scan    resumo filtrado da segurança do PC/rede
  /security scan full relatório completo mas legível
  /security scan raw  JSON técnico bruto da auditoria
  /security admins  resumo das contas/admins
  /security sessions resumo das sessões locais/remotas
  /security posture resumo de Firewall, Defender e acesso remoto
  /security blocked files verificar DLL/PYD/EXE/PY/PS1 bloqueados pelo Windows
  /security blocked files full incluir eventos de integridade/limitações
  /security blocked files raw JSON técnico completo
  /network status   estado simples da ligação
  /network devices  dispositivos ativos na LAN
  /network devices all todos os dispositivos conhecidos
  /network status full detalhe técnico completo da rede
  /desktop agent status estado do Desktop Agent
  /desktop observe  janela ativa, cursor e dimensões do ecrã
  /desktop windows  listar janelas visíveis
  /desktop screenshot capturar ecrã localmente
  /vision status    estado do modelo visual local
  /vision capture   capturar ecrã para visão
  /vision analyze [PEDIDO] analisar ecrã com modelo visual local (se configurado)
  /vision camera [PEDIDO] capturar/analisar webcam local
  /guardian status  estado do System Guardian
  /guardian scan    verificar persistência/listeners/integridade agora
  /guardian baseline criar nova baseline (requer confirmação)
  /purple status    estado do Purple Team Orchestrator
  /purple run IP [P1,P2,...] auditoria LAB coordenada
  /purple retest [IP] repetir teste após mitigação
  /planner status   estado do Autonomous Task Planner
  /planner run OBJETIVO criar e executar plano seguro
  /planner list     planos locais recentes
  /planner resume ID retomar plano pausado
  /planner adapt ID adaptar plano falhado com evidência
  /memory graph     estado da memória relacional
  /repair diagnose  auto-diagnóstico do JARVIS
  /repair safe      aplicar reparações locais seguras
  /skills status    skills carregadas e ferramentas modulares
  /skills discover  pacotes externos encontrados (não os carrega)
  /skills trust DIR confiar digest exato de uma skill externa (OWNER)
  /skills untrust ID remover confiança externa
  /telemetry        última amostra de telemetria
  /speed            resumo rápido de desempenho
  /perf status      estado do Resource Governor
  /perf auto        perfil automático (recomendado)
  /perf fast        prioridade máxima à latência
  /perf balanced    equilíbrio qualidade/velocidade
  /perf deep        raciocínio/local context máximo
  /perf eco         minimizar CPU/GPU/RAM
  /perf release     libertar todos os modelos JARVIS da VRAM agora
  /vram status      runtime/modelos locais JARVIS residentes
  /vram release     libertar imediatamente a VRAM usada pela IA local
  /research status  estado da pesquisa direta + síntese local
  /research test    testar pesquisa pública sem IA externa
  /research TEXT    pesquisa direta na web + síntese Qwen local
  /web TEXT         alias de /research TEXT
  /local TEXT       forçar Qwen local
  /cloud status     confirma que IA externa está HARD BLOCKED
  /cloud diagnose   confirma que IA externa está HARD BLOCKED
  /warmup           pré-carregar o modelo local Qwen
  /debug on         mostrar eventos técnicos no terminal
  /debug off        ocultar eventos técnicos (predefinição)
  /debug status     estado do modo de diagnóstico
  /events           últimos eventos guardados
  /pending          ações à espera de confirmação
  /confirm TOKEN    executar ação confirmada
  /cancel TOKEN     cancelar ação pendente
  /clear            limpar contexto
  /quit             sair

Experimenta:
  Como está a minha GPU agora?
  Abre o Spotify.
  Abre o Brave.
  Coloca o volume a 30%.
  Silencia o áudio.
  Fecha o Discord.
""".strip()



def main() -> None:
    # The updater preserves settings.json. Normalize/add the current schema on
    # every startup so current schema migrations and legacy-setting
    # retirement apply without overwriting custom OWNER choices.
    # Terminal display state remains transport-local.
    debug_terminal = {
        "enabled": False
    }

    bootstrap = build_application()
    application = bootstrap.application
    context = bootstrap.context

    settings = application.settings
    events = application.events
    brain = application.brain
    telemetry = application.telemetry
    performance = application.performance
    activity_trace = (
        application.activity_trace
    )
    autonomy = application.autonomy
    kali_bridge = application.kali_bridge
    cyber_knowledge = (
        application.cyber_knowledge
    )

    memory = context.memory
    profiles = context.profiles
    user_address = context.user_address
    agenda = context.agenda
    routines = context.routines
    inventory = context.inventory
    integrations = context.integrations
    book_library = context.book_library
    cognition = context.cognition
    self_engine = context.self_engine
    security = context.security
    apps = context.apps
    cyber_range = context.cyber_range
    tools = context.tools
    memory1_store = context.memory1_store
    research_engine = (
        context.research_engine
    )
    skill_context = context.skill_context
    skills = context.skills
    hybrid_brain = context.hybrid_brain
    command_lock = context.command_lock
    silence_latch = context.silence_latch

    # These symbols remain available to legacy terminal/admin command
    # handlers while Core construction itself is owned by bootstrap.py.
    from jarvis_core.memory.enums import (
        MemoryAuthority,
        SourceType,
    )
    from jarvis_core.memory.interpreter import (
        InterpreterContext,
        MemoryOperation,
    )
    from jarvis_core.memory.model_adapter import (
        MemoryModelContractError,
        MemoryModelInvocationError,
        utc_now,
    )
    from jarvis_core.memory.errors import (
        MemoryAvailabilityError,
    )
    from jarvis_core.memory.resolution_plan import (
        build_memory_resolution_plan,
        remember_plan_has_ambiguous_identity,
    )
    from jarvis_core.memory.write_executor import (
        TrustedWriteExecutionContext,
        execute_memory_resolution_plan,
    )

    def current_address() -> str:
        return (
            profiles.active().get(
                "address_as"
            )
            or user_address
        )

    def is_silence_command(
        value: str,
    ) -> bool:
        normalized = (
            str(value or "")
            .lower()
            .replace("-", " ")
        )
        normalized = " ".join(
            normalized.split()
        )
        compact = normalized.replace(
            " ",
            "",
        )

        return (
            "calate" in compact
            or "para de falar" in normalized
            or normalized in {
                "silencio",
                "sil?ncio",
                "fica calada",
                "fica em silencio",
                "fica em sil?ncio",
            }
        )

    def read_tool(
        name: str,
        arguments: dict | None = None,
    ):
        raw = tools.execute(
            name,
            arguments or {},
        )

        try:
            return json.loads(
                raw
            )

        except Exception:
            return {
                "ok": False,
                "error":
                    "INVALID_TOOL_RESULT",
                "raw": raw,
            }


    open_owner_kali_session = (
        application.open_owner_kali_session
    )

    owner_authorized_cyber_sync = (
        application.owner_authorized_cyber_sync
    )


    def semantic_context_inputs():
        return application.semantic_context_inputs()

    def process_request(
        user_text: str,
        *,
        source: str = "terminal",
    ) -> ProcessRequestResult:
        return application.process_request(
            user_text,
            source=source,
        )











    def terminal_event_printer(event: Event) -> None:
        if debug_terminal["enabled"]:
            event_printer(event)

    # Always subscribe the gate so /debug on/off works without restart.
    # EventBus itself keeps writing events to logs/events.jsonl while quiet.
    events.subscribe(terminal_event_printer)

    application.start_runtime_services()



    ok, msg = brain.health_check()

    try:
        memory1_store.assert_readable()
        memory_startup_status = "READY"
    except Exception:
        memory_startup_status = "ATTENTION"

    try:
        security.pending()
        security_startup_status = "READY"
    except Exception:
        security_startup_status = "ATTENTION"

    print(BANNER_TEMPLATE.format(version=__version__))
    print("Core      : READY")
    print(
        f"Brain     : {'READY' if ok else 'ATTENTION'} "
        f"| {settings.model}"
    )
    print(
        f"Memory    : {memory_startup_status} | Memory 1.0"
    )
    print(
        f"Security  : {security_startup_status}"
    )
    print("Web       : NOT INTEGRATED")
    print("Debug     : OFF | /debug on")

    if not ok:
        print(f"Warning   : {msg}")

    print()

    def proactive_callback(
        message: str,
        reason: str,
        candidate: dict,
    ) -> None:
        if silence_latch.active():
            silence_latch.mark_suppressed_response("proactive")
            return
        final_message = message
        topic = str(
            candidate.get(
                "autonomy_learning_topic"
            )
            or ""
        ).strip()

        if (
            topic
            and settings.autonomy_enabled
            and settings.autonomy_proactive_learning_enabled
            and research_engine.available()
        ):
            query = (
                "Pesquisa na Internet fontes públicas atuais sobre "
                f"{topic}. Resume o que é mais útil para o meu objetivo, "
                "distingue factos de inferências e não inventes dados."
            )
            gate = autonomy.request(
                capability="external_learning",
                payload={
                    "topic": topic,
                    "query": query,
                    "deep": False,
                    "scope":
                        "single_research_session",
                },
                reason=reason,
                description=(
                    "pesquisar e aprender externamente sobre "
                    f"{topic[:220]}"
                ),
                action="external_learning",
                source="proactive_presence",
            )
            if gate.get("pending"):
                final_message = (
                    message
                    + "\n"
                    + str(gate.get("message") or "")
                )

        events.emit(
            "PROACTIVE_MESSAGE",
            reason=reason,
            chars=len(final_message),
        )
        print(f"\nJARVIS > {final_message}\n")

    proactive_service = ProactivePresenceService(
        proactive_callback,
        interval_seconds=settings.proactive_interval_seconds,
        startup_delay_seconds=settings.proactive_startup_delay_seconds,
        min_interval_minutes=settings.proactive_min_interval_minutes,
        idle_seconds=settings.proactive_idle_seconds,
        quiet_start_hour=settings.proactive_quiet_start_hour,
        quiet_end_hour=settings.proactive_quiet_end_hour,
        max_per_hour=settings.proactive_max_per_hour,
        cognition=cognition,
    )

    def companion_output_callback(message: str, decision: dict) -> None:
        if silence_latch.active():
            silence_latch.mark_suppressed_response("proactive")
            return
        events.emit(
            "COMPANION_MESSAGE",
            tone=decision.get("tone"),
            reason=decision.get("reason"),
            chars=len(message),
        )
        print(f"\nJARVIS > {message}\n")

    companion_service = CompanionPresenceService(
        brain.plan_companion_initiative,
        companion_output_callback,
        state_path=settings.companion_state_path,
        enabled=settings.companion_enabled,
        check_interval_seconds=settings.companion_check_interval_seconds,
        startup_delay_seconds=settings.companion_startup_delay_seconds,
        decision_cooldown_seconds=settings.companion_decision_cooldown_seconds,
        min_interval_minutes=settings.companion_min_interval_minutes,
        idle_seconds=settings.companion_idle_seconds,
        quiet_start_hour=settings.companion_quiet_start_hour,
        quiet_end_hour=settings.companion_quiet_end_hour,
        max_per_hour=settings.companion_max_per_hour,
        max_chars=settings.companion_max_chars,
    )

    idle_mind = IdleMindService(
        settings=settings,
        cognition=cognition,
        activity_trace=activity_trace,
        companion_service=companion_service,
        silence_latch=silence_latch,
        planner_provider=lambda: skill_context.services.get("task_planner"),
        reflection_provider=brain.plan_idle_reflection,
    )

    def reminder_callback(message: str) -> None:
        if silence_latch.active():
            silence_latch.mark_suppressed_response("proactive")
            return
        print(f"\nJARVIS > {message}\n")

    reminder_service = ReminderService(
        events,
        callback=reminder_callback,
        interval_seconds=settings.reminder_interval_seconds,
    )
    security_watch_service = SecurityWatchService(
        events,
        interval_seconds=settings.security_watch_interval_seconds,
        resource_guard=performance.should_defer_background,
    )
    cyber_knowledge_service = CyberKnowledgeService(
        events,
        enabled=(
            settings.cyber_knowledge_enabled
            and settings.cyber_knowledge_auto_sync
        ),
        startup_delay_seconds=(
            settings.cyber_knowledge_startup_delay_seconds
        ),
        interval_hours=settings.cyber_knowledge_sync_interval_hours,
        resource_guard=performance.should_defer_background,
    )
    book_library_service = BookLibraryService(
        events,
        book_library,
        enabled=(
            settings.book_library_enabled
            and settings.book_library_auto_sync
        ),
        startup_delay_seconds=settings.book_library_startup_delay_seconds,
        interval_seconds=settings.book_library_sync_interval_seconds,
        resource_guard=performance.should_defer_background,
    )
    if settings.reminders_enabled:
        reminder_service.start()
    if settings.security_watch_enabled:
        security_watch_service.start()
    cyber_knowledge_service.start()
    book_library_service.start()
    proactive_service.start()
    companion_service.start()
    if settings.skills_enabled:
        skills.start_all()


    def execute_owner_authorization(
        token: str,
    ) -> None:
        approved = autonomy.authorize(
            token
        )
        if not approved.get("ok"):
            print(
                "JARVIS >",
                json.dumps(
                    approved,
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            return

        grant = approved.get(
            "authorization"
        ) or {}
        action = str(
            grant.get("action")
            or ""
        )
        payload = dict(
            grant.get("payload")
            or {}
        )

        print(
            "JARVIS > Autorização aceite para esta ação exata. "
            "Não cria permissão permanente."
        )

        if not settings.autonomy_auto_execute_after_authorize:
            return

        if action == "execute_tool":
            tool_name = str(payload.get("tool") or "").strip()
            tool_args = dict(payload.get("arguments") or {})
            if not tool_name:
                print("JARVIS > A autorização não contém uma ferramenta válida.")
                return
            # Consume the one-shot authorization before execution so it cannot
            # be replayed. This bypasses only the active profile gate and the
            # redundant CONFIRM gate; CRITICAL tools and each tool's own scope
            # validation remain non-bypassable.
            gate = autonomy.request(
                capability="tool_override",
                payload={"tool": tool_name, "arguments": tool_args},
                reason="owner_authorized_tool_override",
                description=f"executar a ferramenta {tool_name} autorizada pelo OWNER",
                action="execute_tool",
                source="authorization_executor",
            )
            if not gate.get("allowed"):
                print("JARVIS > Não consegui consumir a autorização exata; não executei a ferramenta.")
                return
            result = tools.execute(
                tool_name,
                tool_args,
                bypass_confirmation=True,
                bypass_profile_permission=True,
            )
            print(f"JARVIS > {result}")
            return

        if action == "resume_query":
            query = str(
                payload.get("query")
                or ""
            ).strip()
            if not query:
                return

            with command_lock:
                result = process_request(
                    query
                )
                print(
                    f"\nJARVIS > {result.answer}\n"
                )
            return

        if action in {"external_learning", "external_learning_resume_query"}:
            topic = str(
                payload.get("topic")
                or ""
            ).strip()

            query = str(
                payload.get("query")
                or ""
            ).strip()

            source_url = str(
                payload.get("source_url")
                or ""
            ).strip()

            if not topic or not query:
                print(
                    "JARVIS > A autorizacao aprovada nao contem um "
                    "escopo de aprendizagem externa valido."
                )
                return

            tool_arguments = {
                "topic": topic,
                "query": query,
                "source_text": "",
                "deep": bool(
                    payload.get("deep")
                ),
                "scope": str(
                    payload.get("scope")
                    or "single_research_session"
                ),
                "source_url": source_url,
                "standing_public_web_read_only_grant":
                    False,
                "authority_mode":
                    "approved_grant",
                "authorization_token": str(
                    grant.get("token")
                    or token
                ).strip().upper(),
                "authorization_action":
                    action,
                "authorized_payload":
                    dict(payload),
            }

            raw_result = tools.execute(
                "execute_authorized_external_learning",
                tool_arguments,
                bypass_confirmation=True,
                bypass_profile_permission=True,
            )

            try:
                result = json.loads(
                    raw_result
                )
            except Exception:
                result = {
                    "ok": False,
                    "error":
                        "INVALID_EXTERNAL_LEARNING_TOOL_RESULT",
                    "raw": raw_result,
                }

            if not result.get("ok"):
                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                return

            summary = str(
                result.get("summary")
                or ""
            ).strip()

            message = (
                "Aprendizagem externa autorizada concluida e "
                "guardada localmente sobre: "
                f"{topic}. "
                "A execucao passou pelo ToolRegistry e consumiu "
                "o grant exato aprovado pelo OWNER."
            )

            if summary:
                print(
                    f"\nJARVIS > {summary}\n"
                )

            print(
                f"JARVIS > {message}"
            )

            if (
                action
                == "external_learning_resume_query"
            ):
                original_query = str(
                    payload.get(
                        "original_query"
                    )
                    or ""
                ).strip()

                if original_query:
                    print(
                        "JARVIS > Estudo local atualizado. "
                        "Vou tentar novamente o pedido original "
                        "usando o conhecimento validado."
                    )

                    with command_lock:
                        result = process_request(
                            original_query
                        )

                        print(
                            f"\nJARVIS > {result.answer}\n"
                        )


            return

        if action == "cloud_reasoning":
            print("JARVIS > Outra inteligência artificial está bloqueada no Core. A autorização não será executada.")
            events.emit("EXTERNAL_AI_HARD_BLOCK", source="authorization_executor")
            return

    try:
        while True:
            try:
                text = input(f"{current_address()} > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nJARVIS > A desligar.")
                break

            if not text:
                continue

            if text.startswith("\\"):
                text = "/" + text[1:]

            lower = text.lower()

            # Resolve explicit OWNER textual addressing before specialized intent
            # parsers.  In 0.26.2 this happened only near the generic model
            # route, so a valid authorization such as
            # "Jarvis, tens a minha autorização ..." could be parsed against
            # the unstripped JARVIS address prefix or bypass the local authority path.
            # Slash commands remain usable while silent without implicitly
            # releasing the latch.
            if (
                silence_latch.active()
                and not is_silence_command(text)
                and not lower.startswith("/")
            ):
                jarvis_prefix_match = re.match(
                    r"^\s*jarvis(?=$|[\s,;:!?.-])[\s,;:!?.-]*(.*)$",
                    text,
                    flags=re.IGNORECASE,
                )
                if jarvis_prefix_match is not None:
                    silence_latch.release(source="explicit_terminal_address")
                    text = str(jarvis_prefix_match.group(1) or "").strip()
                    if not text:
                        print("JARVIS > Diga, Senhor.")
                        continue
                    lower = text.lower()
                else:
                    silence_latch.release(source="explicit_terminal_input")

            if is_silence_command(text):
                silence_latch.latch(reason="owner_interrupt", source="terminal")
                continue

            if lower == "/silence status":
                print("JARVIS >", json.dumps(silence_latch.status(), ensure_ascii=False, indent=2))
                continue
            if lower in {"/silence off", "/silence release"}:
                print("JARVIS >", json.dumps(silence_latch.release(source="owner_cli"), ensure_ascii=False, indent=2))
                continue
            if lower == "/silence on":
                print("JARVIS >", json.dumps(silence_latch.latch(reason="owner_cli", source="terminal"), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity on":
                print("JARVIS >", json.dumps(activity_trace.set_live(True), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity off":
                print("JARVIS >", json.dumps(activity_trace.set_live(False), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity status":
                print("JARVIS >", json.dumps(activity_trace.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity last":
                print("JARVIS >", json.dumps(activity_trace.last(), ensure_ascii=False, indent=2))
                continue

            if lower in {"/quit", "/qquit", "/exit", "sair"}:
                print("JARVIS > Núcleo desligado.")
                break
            if lower == "/help":
                print(help_text())
                continue
            if lower in {"/help all", "/commands"}:
                print(help_text_full())
                continue

            if lower == "/status":
                brain_ok, brain_msg = brain.health_check()

                try:
                    memory1_store.assert_readable()
                    memory1_revision = (
                        memory1_store.canonical_revision()
                    )
                    memory1_status = (
                        f"READY | rev={memory1_revision}"
                    )
                except Exception as exc:
                    memory1_status = (
                        "ATTENTION | "
                        f"{type(exc).__name__}"
                    )

                try:
                    security_pending = len(
                        security.pending()
                    )
                    security_status = (
                        f"READY | pending={security_pending}"
                    )
                except Exception as exc:
                    security_status = (
                        "ATTENTION | "
                        f"{type(exc).__name__}"
                    )

                try:
                    research_status = (
                        "READY"
                        if research_engine.available()
                        else "OFF"
                    )
                except Exception as exc:
                    research_status = (
                        "ATTENTION | "
                        f"{type(exc).__name__}"
                    )

                print("JARVIS STATUS")
                print(
                    f"Core      : READY | {__version__}"
                )
                print(
                    f"Brain     : "
                    f"{'READY' if brain_ok else 'ATTENTION'} "
                    f"| {settings.model}"
                )
                print(
                    f"Memory1   : {memory1_status}"
                )
                print(
                    f"Security  : {security_status}"
                )
                print(
                    f"Research  : {research_status}"
                )
                print(
                    "Debug     : "
                    + (
                        "ON"
                        if debug_terminal["enabled"]
                        else "OFF"
                    )
                )
                print("Web       : NOT INTEGRATED")

                if not brain_ok:
                    print(f"Warning   : {brain_msg}")

                continue

            if lower == "/test quick":
                print(
                    "JARVIS > QUICK TEST: running..."
                )

                result = run_quick_tests()

                if result.get("ok"):
                    print(
                        "JARVIS > QUICK TEST: OK | "
                        f"{result.get('tests')} tests | "
                        f"{result.get('patterns')} suites"
                    )
                else:
                    print(
                        "JARVIS > QUICK TEST: FAILED | "
                        f"{result.get('pattern')}"
                    )

                    output = str(
                        result.get("output") or ""
                    ).strip()

                    if output:
                        print(output)

                continue

            if lower == "/health":
                ok, msg = brain.health_check()
                print(f"JARVIS > {'OK' if ok else 'ATENÇÃO'}: {msg}"); continue
            if lower == "/version":
                print(f"JARVIS > Core {__version__}"); continue
            if lower == "/clear":
                hybrid_brain.clear_history()
                print("JARVIS > Contexto da sessão local e legacy cloud limpo. A memória persistente mantém-se."); continue
            if lower == "/tools":
                for t in tools.describe():
                    print(f"- {t['name']} [{t['risk']}]\n  {t['description']}")
                continue
            if lower == "/apps":
                print(json.dumps(apps.list_apps(), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/appcheck "):
                app_name = text.split(maxsplit=1)[1].strip()
                print(json.dumps(apps.diagnose(app_name), ensure_ascii=False, indent=2))
                continue
            if lower == "/companion status":
                print("JARVIS >", json.dumps(companion_service.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/companion on":
                settings.companion_enabled = True
                companion_service.set_enabled(True)
                Settings.update_file_values({"companion_enabled": True})
                print("JARVIS > Presença social adaptativa ativada.")
                continue
            if lower == "/companion off":
                settings.companion_enabled = False
                companion_service.set_enabled(False)
                Settings.update_file_values({"companion_enabled": False})
                print("JARVIS > Presença social adaptativa desativada.")
                continue
            if lower == "/av cameras":
                vision_service = skill_context.services.get("vision")
                result = (
                    vision_service.list_cameras()
                    if vision_service is not None
                    else {"ok": False, "error": "VISION_SERVICE_UNAVAILABLE"}
                )
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/av camera "):
                raw_index = text[len("/av camera "):].strip()
                vision_service = skill_context.services.get("vision")
                try:
                    index = int(raw_index)
                    if vision_service is None:
                        raise RuntimeError("VISION_SERVICE_UNAVAILABLE")
                    result = vision_service.set_camera_index(index)
                    if result.get("ok"):
                        settings.vision_camera_index = int(result["camera_index"])
                        Settings.update_file_values({"vision_camera_index": settings.vision_camera_index})
                except Exception as exc:
                    result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue

            if lower == "/memory status":
                print(f"JARVIS >\n{format_memory_status(memory.status())}")
                continue
            if lower == "/memory status raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        memory.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/memory show":
                print("JARVIS >", json.dumps(memory.recall(limit=50), ensure_ascii=False, indent=2))
                continue

            if lower == "/profile status":
                print(f"JARVIS >\n{format_profile_status(profiles.status())}")
                continue
            if lower == "/profile status raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        profiles.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/profile perms":
                print(f"JARVIS >\n{format_profile_permissions(profiles.permissions())}")
                continue
            if lower == "/profile perms raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        profiles.permissions(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower.startswith("/profile use "):
                pid = text.split(maxsplit=2)[2].strip()
                print("JARVIS >", json.dumps(profiles.activate(pid), ensure_ascii=False, indent=2))
                continue

            if lower == "/watch status":
                result = read_tool("get_security_watch_status")
                print(f"JARVIS >\n{format_watch_status(result)}")
                continue
            if lower == "/watch status raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool("get_security_watch_status"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/watch baseline":
                result = read_tool("create_security_baseline")
                print(f"JARVIS >\n{format_watch_baseline(result)}")
                continue
            if lower == "/watch baseline raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool("create_security_baseline"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/watch check":
                result = read_tool("check_security_watch")
                print(f"JARVIS >\n{format_watch_check(result)}")
                continue
            if lower == "/watch check raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool("check_security_watch"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/pc checkup":
                result = read_tool("get_pc_health")
                print(f"JARVIS >\n{format_pc_health(result)}")
                continue

            if lower == "/routine list":
                print(f"JARVIS >\n{format_routines(routines.list())}")
                continue
            if lower.startswith("/routine run "):
                name = text.split(maxsplit=2)[2].strip()
                result = read_tool("run_routine", {"name": name})
                if result.get("ok"):
                    print(f"JARVIS > {result.get('label', name)} ativado.")
                else:
                    print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue

            if lower == "/files index":
                result = read_tool("build_local_file_index")
                print(f"JARVIS >\n{format_file_index(result)}")
                continue
            if lower == "/files index raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool("build_local_file_index"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower.startswith("/files find "):
                query = text.split(maxsplit=2)[2].strip()
                result = read_tool("search_local_files", {"query": query, "limit": 20})
                rows = result.get("results") or []
                if not rows:
                    print("JARVIS > Não encontrei ficheiros correspondentes.")
                else:
                    print("JARVIS >")
                    for row in rows[:20]:
                        print(f"- {row.get('name')} | {row.get('path')}")
                continue
            if lower == "/files recent":
                result = read_tool("list_recent_local_files", {"limit": 15})
                print("JARVIS >")
                for row in result.get("results") or []:
                    print(f"- {row.get('name')} | {row.get('modified')}")
                continue

            if lower == "/agenda today":
                result = agenda.list_items("today", limit=20)
                print("JARVIS >")
                if not result.get("items"):
                    print("Sem itens para hoje.")
                for row in result.get("items") or []:
                    print(f"- [{row.get('id')}] {row.get('when') or 'sem hora'} | {row.get('title')}")
                continue
            if lower == "/agenda upcoming":
                result = agenda.list_items("upcoming", limit=30)
                print("JARVIS >")
                if not result.get("items"):
                    print("Sem itens pendentes.")
                for row in result.get("items") or []:
                    print(f"- [{row.get('id')}] {row.get('when') or 'sem hora'} | {row.get('title')}")
                continue
            if lower.startswith("/agenda add "):
                raw = text[len("/agenda add "):].strip()
                parts = raw.split(maxsplit=2)
                if len(parts) < 3:
                    print("JARVIS > Usa: /agenda add YYYY-MM-DD HH:MM Título")
                else:
                    result = agenda.add(parts[2], parts[0] + " " + parts[1], "event")
                    print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/task add "):
                result = agenda.add(text[len("/task add "):].strip(), kind="task")
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/task done "):
                item_id = text.split(maxsplit=2)[2].strip()
                print("JARVIS >", json.dumps(agenda.complete(item_id), ensure_ascii=False, indent=2))
                continue

            if lower == "/lock":
                result = read_tool("lock_workstation")
                if not result.get("ok"):
                    print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue

            if lower == "/integrations":
                print(f"JARVIS >\n{format_integrations(integrations.status())}")
                continue
            if lower == "/integrations raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        integrations.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/dashboard data":
                result = read_tool("get_dashboard_snapshot")
                print(f"JARVIS >\n{format_dashboard_preview(result)}")
                continue
            if lower == "/dashboard raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool("get_dashboard_snapshot"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/network inventory":
                result = inventory.refresh()
                print(f"JARVIS >\n{format_network_inventory(result)}")
                continue
            if lower == "/network inventory raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        inventory.refresh(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower in {"/mind idle", "/idle mind"}:
                print("JARVIS >", json.dumps(idle_mind.snapshot(), ensure_ascii=False, indent=2))
                continue
            if lower in {"/mind idle reflect", "/idle mind reflect", "/mind now"}:
                print("JARVIS >", json.dumps(idle_mind.reflect(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind status":
                print("JARVIS >", json.dumps(cognition.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind profile":
                print("JARVIS >", json.dumps(cognition.profile(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind reflect":
                print("JARVIS >", json.dumps(cognition.reflection(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind self":
                print("JARVIS >", json.dumps(cognition.self_model(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind state":
                print("JARVIS >", json.dumps(self_engine.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind why":
                print("JARVIS >", json.dumps(cognition.last_proactive_reason(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind learning on":
                print("JARVIS >", json.dumps(cognition.set_mode(learning_enabled=True), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind learning off":
                print("JARVIS >", json.dumps(cognition.set_mode(learning_enabled=False), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind proactive on":
                print("JARVIS >", json.dumps(cognition.set_mode(proactive_enabled=True), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind proactive off":
                print("JARVIS >", json.dumps(cognition.set_mode(proactive_enabled=False), ensure_ascii=False, indent=2))
                continue
            if lower == "/learning status":
                learning_status = authorized_learning().status()
                learning_status.update({
                    "epistemic_learning_enabled": bool(getattr(settings, "epistemic_learning_enabled", True)),
                    "request_scoped_rag_enabled": bool(getattr(settings, "epistemic_learning_rag_enabled", True)),
                    "default_stale_days": int(getattr(settings, "epistemic_learning_stale_days", 120)),
                    "external_expert_enabled": bool(getattr(settings, "expert_escalation_enabled", True)),
                    "external_expert_available": bool(cloud_brain.available()),
                    "policy": "learning_first_owner_gated",
                })
                print("JARVIS >", json.dumps(learning_status, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/learning topic "):
                topic = text[len("/learning topic "):].strip()
                stale_days = freshness_days_for_topic(
                    topic,
                    int(getattr(settings, "epistemic_learning_stale_days", 120)),
                )
                print(
                    "JARVIS >",
                    json.dumps(
                        knowledge_state(authorized_learning(), topic, stale_days=stale_days),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower.startswith("/learning search "):
                query = text[len("/learning search "):].strip()
                print(
                    "JARVIS >",
                    json.dumps(authorized_learning().search(query, limit=5), ensure_ascii=False, indent=2),
                )
                continue

            if lower == "/cyber lab status":
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_range_status(cyber_range.status())}"
                )
                continue
            if lower.startswith("/cyber lab add "):
                raw = text[len("/cyber lab add "):].strip()
                parts = raw.split(maxsplit=1)
                target = parts[0] if parts else ""
                label = parts[1] if len(parts) > 1 else ""
                result = cyber_range.add_lab_scope(target, label)
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cyber lab remove "):
                target = text[len("/cyber lab remove "):].strip()
                result = cyber_range.remove_lab_scope(target)
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cyber lab classify "):
                target = text[len("/cyber lab classify "):].strip()
                result = cyber_range.classify(target)
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cyber lab probe "):
                raw = text[
                    len("/cyber lab probe "):
                ].strip()

                parts = raw.split(
                    maxsplit=1
                )

                target = (
                    parts[0]
                    if parts
                    else ""
                )

                ports = None

                if len(parts) > 1:
                    ports = []

                    for item in (
                        parts[1]
                        .replace(" ", "")
                        .split(",")
                    ):
                        try:
                            ports.append(
                                int(item)
                            )
                        except ValueError:
                            pass

                scoped = (
                    cyber_range
                    .build_probe_authorization_scope(
                        target,
                        ports,
                    )
                )

                if not scoped.get("ok"):
                    result = scoped
                else:
                    payload = dict(
                        scoped.get("payload")
                        or {}
                    )

                    try:
                        authorization = (
                            autonomy
                            .record_direct_authorization(
                                capability=
                                    "active_network_probe",
                                payload=payload,
                                description=(
                                    "executar sondagem TCP "
                                    "controlada no LAB "
                                    f"{payload.get('target')} "
                                    "nas portas "
                                    f"{payload.get('ports')}"
                                ),
                                source_text=text,
                            )
                        )
                    except Exception as exc:
                        authorization = {
                            "ok": False,
                            "authorized": False,
                            "error":
                                "OWNER_NETWORK_AUTHORITY_ERROR",
                            "message":
                                f"{type(exc).__name__}: {exc}",
                        }

                    if (
                        not isinstance(
                            authorization,
                            dict,
                        )
                        or not authorization.get(
                            "ok"
                        )
                        or not authorization.get(
                            "authorized",
                            False,
                        )
                    ):
                        result = {
                            "ok": False,
                            "error":
                                "OWNER_AUTHORIZED_NETWORK_SCOPE_FAILED",
                            "reason_code": str(
                                authorization.get(
                                    "error"
                                )
                                if isinstance(
                                    authorization,
                                    dict,
                                )
                                else ""
                            )
                            or
                            "OWNER_AUTHORIZED_NETWORK_SCOPE_FAILED",
                            "decision":
                                scoped.get(
                                    "decision"
                                ),
                        }
                    else:
                        execution_token = str(
                            authorization.get(
                                "execution_token"
                            )
                            or ""
                        )

                        if not execution_token:
                            result = {
                                "ok": False,
                                "error":
                                    "OWNER_NETWORK_EXECUTION_CREDENTIAL_MISSING",
                                "decision":
                                    scoped.get(
                                        "decision"
                                    ),
                            }
                        else:
                            result = (
                                cyber_range.probe(
                                    target,
                                    ports,
                                    execution_token=
                                        execution_token,
                                )
                            )

                print(
                    f"JARVIS >\n"
                    f"{format_lab_probe(result)}"
                )
                continue

            if lower.startswith("/cyber kali vm configure "):
                raw = text[len("/cyber kali vm configure "):].strip()
                parts = raw.split(maxsplit=1)
                if len(parts) != 2:
                    print("JARVIS > Usa: /cyber kali vm configure virtualbox NOME_VM  ou  /cyber kali vm configure vmware CAMINHO.vmx")
                    continue
                result = kali_bridge.configure_vm(parts[0], parts[1], True)
                print(f"JARVIS >\n{json.dumps(result, ensure_ascii=False, indent=2)}")
                continue
            if lower == "/cyber kali vm status":
                print(f"JARVIS >\n{json.dumps(kali_bridge.vm_status(), ensure_ascii=False, indent=2)}")
                continue
            if lower == "/cyber kali vm start":
                result = kali_bridge.start_vm()
                print(f"JARVIS >\n{json.dumps(result, ensure_ascii=False, indent=2)}")
                continue
            if lower == "/cyber kali vm watch":
                result = kali_bridge.open_activity_console()
                print(f"JARVIS >\n{json.dumps(result, ensure_ascii=False, indent=2)}")
                continue
            if lower == "/cyber kali status":
                print(f"JARVIS >\n{format_kali_bridge_status(kali_bridge.status())}")
                continue
            if lower == "/cyber kali doctor":
                opened = open_owner_kali_session(
                    profiles=[
                        "bridge_doctor",
                    ],
                    ports=[],
                    scope=
                        "KALI_BRIDGE_DIAGNOSTIC",
                    source_text=text,
                )

                if not opened.get("ok"):
                    result = opened
                else:
                    kali_session = str(
                        opened.get(
                            "session_token"
                        )
                        or ""
                    )

                    try:
                        result = (
                            kali_bridge.doctor(
                                session_token=
                                    kali_session,
                            )
                        )
                    finally:
                        kali_bridge.close_security_session(
                            kali_session
                        )

                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/cyber kali inventory":
                opened = open_owner_kali_session(
                    profiles=[
                        "bridge_inventory",
                    ],
                    ports=[],
                    scope=
                        "KALI_BRIDGE_DIAGNOSTIC",
                    source_text=text,
                )

                if not opened.get("ok"):
                    result = opened
                else:
                    kali_session = str(
                        opened.get(
                            "session_token"
                        )
                        or ""
                    )

                    try:
                        result = (
                            kali_bridge.inventory(
                                session_token=
                                    kali_session,
                            )
                        )
                    finally:
                        kali_bridge.close_security_session(
                            kali_session
                        )

                print(
                    f"JARVIS >\n"
                    f"{format_kali_inventory(result)}"
                )
                continue
            if lower == "/cyber kali clear":
                result = kali_bridge.clear()
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cyber kali configure "):
                raw = text[len("/cyber kali configure "):].strip()
                parts = raw.split(maxsplit=3)
                if len(parts) < 2:
                    print("JARVIS > Usa: /cyber kali configure IP USER [PORT] [KEY_PATH]")
                    continue
                host = parts[0]
                username = parts[1]
                port = 22
                key_path = ""
                if len(parts) >= 3:
                    try:
                        port = int(parts[2])
                    except ValueError:
                        print("JARVIS > A porta SSH tem de ser numérica. Exemplo: 22")
                        continue
                if len(parts) >= 4:
                    key_path = parts[3].strip().strip('"')
                result = kali_bridge.configure(host, username, port, key_path)
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cyber kali nmap "):
                raw = text[len("/cyber kali nmap "):].strip()
                parts = raw.split(maxsplit=1)
                target = parts[0] if parts else ""
                ports = None
                if len(parts) > 1:
                    ports = []
                    for item in parts[1].replace(" ", "").split(","):
                        try:
                            ports.append(int(item))
                        except ValueError:
                            pass
                effective_ports = (
                    kali_bridge._normalize_ports(
                        ports
                    )
                )

                opened = open_owner_kali_session(
                    target=target,
                    profiles=[
                        "nmap_services",
                    ],
                    ports=effective_ports,
                    scope="LAB",
                    source_text=text,
                )

                if not opened.get("ok"):
                    result = opened
                else:
                    kali_session = str(
                        opened.get(
                            "session_token"
                        )
                        or ""
                    )

                    try:
                        result = (
                            kali_bridge
                            .nmap_service_scan(
                                target,
                                effective_ports,
                                session_token=
                                    kali_session,
                            )
                        )
                    finally:
                        kali_bridge.close_security_session(
                            kali_session
                        )

                print(
                    f"JARVIS >\n"
                    f"{format_kali_scan(result)}"
                )
                continue
            if lower.startswith("/cyber kali whatweb "):
                raw = text[len("/cyber kali whatweb "):].strip()
                parts = raw.split()
                if len(parts) < 2:
                    print("JARVIS > Usa: /cyber kali whatweb IP PORT [https]")
                    continue
                target = parts[0]
                try:
                    port = int(parts[1])
                except ValueError:
                    print("JARVIS > Porta inválida.")
                    continue
                https = len(parts) >= 3 and parts[2].lower() in {"https", "ssl", "tls", "true", "1"}
                opened = open_owner_kali_session(
                    target=target,
                    profiles=[
                        "whatweb_fingerprint",
                    ],
                    ports=[port],
                    scope="LAB",
                    source_text=text,
                )

                if not opened.get("ok"):
                    result = opened
                else:
                    kali_session = str(
                        opened.get(
                            "session_token"
                        )
                        or ""
                    )

                    try:
                        result = (
                            kali_bridge
                            .whatweb_fingerprint(
                                target,
                                port,
                                https,
                                session_token=
                                    kali_session,
                            )
                        )
                    finally:
                        kali_bridge.close_security_session(
                            kali_session
                        )

                print(
                    f"JARVIS >\n"
                    f"{format_kali_scan(result)}"
                )
                continue
            if lower.startswith("/cyber kali nikto "):
                raw = text[len("/cyber kali nikto "):].strip()
                parts = raw.split()
                if len(parts) < 2:
                    print("JARVIS > Usa: /cyber kali nikto IP PORT [https]")
                    continue
                target = parts[0]
                try:
                    port = int(parts[1])
                except ValueError:
                    print("JARVIS > Porta inválida.")
                    continue
                https = len(parts) >= 3 and parts[2].lower() in {"https", "ssl", "tls", "true", "1"}
                opened = open_owner_kali_session(
                    target=target,
                    profiles=[
                        "nikto_safe_web",
                    ],
                    ports=[port],
                    scope="LAB",
                    source_text=text,
                )

                if not opened.get("ok"):
                    result = opened
                else:
                    kali_session = str(
                        opened.get(
                            "session_token"
                        )
                        or ""
                    )

                    try:
                        result = (
                            kali_bridge
                            .nikto_safe_web_scan(
                                target,
                                port,
                                https,
                                session_token=
                                    kali_session,
                            )
                        )
                    finally:
                        kali_bridge.close_security_session(
                            kali_session
                        )

                print(
                    f"JARVIS >\n"
                    f"{format_kali_scan(result)}"
                )
                continue

            if lower == "/cyber inspect network":
                result = inspect_network_deep("standard")
                print(
                    f"JARVIS >\n"
                    f"{format_deep_network_inspection(result)}"
                )
                continue
            if lower == "/cyber inspect listeners":
                result = inspect_network_deep("full")
                result["public_connections"] = []
                print(
                    f"JARVIS >\n"
                    f"{format_deep_network_inspection(result, full=True)}"
                )
                continue
            if lower == "/cyber inspect connections":
                result = inspect_network_deep("full")
                result["listeners"] = []
                print(
                    f"JARVIS >\n"
                    f"{format_deep_network_inspection(result, full=True)}"
                )
                continue
            if lower == "/cyber inspect network full":
                result = inspect_network_deep("full")
                print(
                    f"JARVIS >\n"
                    f"{format_deep_network_inspection(result, full=True)}"
                )
                continue
            if lower == "/cyber inspect network raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        inspect_network_deep("raw"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/cyber analyze system":
                result = analyze_system_cybersecurity("standard")
                print(
                    f"JARVIS >\n"
                    f"{format_system_cyber_audit(result)}"
                )
                continue
            if lower == "/cyber analyze system full":
                result = analyze_system_cybersecurity("full")
                print(
                    f"JARVIS >\n"
                    f"{format_system_cyber_audit(result, full=True)}"
                )
                continue
            if lower == "/cyber analyze system raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        analyze_system_cybersecurity("raw"),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/cyber knowledge status":
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_status(cyber_knowledge.stats())}"
                )
                continue
            if lower == "/cyber knowledge status raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        cyber_knowledge.stats(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower.startswith("/cyber knowledge search "):
                query = text[len("/cyber knowledge search "):].strip()
                result = cyber_knowledge.search(query, limit=8)
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_search(result)}"
                )
                continue
            if lower == "/cyber knowledge sync":
                result = owner_authorized_cyber_sync(
                    full=False,
                    source_text=text,
                )
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_sync(result)}"
                )
                continue
            if lower == "/cyber knowledge sync full":
                print(
                    "JARVIS > A sincronizar também o MITRE ATT&CK completo. "
                    "Esta fonte é bastante maior que as restantes."
                )
                result = owner_authorized_cyber_sync(
                    full=True,
                    source_text=text,
                )
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_sync(result)}"
                )
                continue
            if lower.startswith("/cyber knowledge sync source "):
                source_id = text[
                    len("/cyber knowledge sync source "):
                ].strip()
                result = owner_authorized_cyber_sync(
                    source_id=source_id,
                    source_text=text,
                )
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_sync(result)}"
                )
                continue
            if lower.startswith("/cyber knowledge ingest "):
                path = text[
                    len("/cyber knowledge ingest "):
                ].strip().strip('"')
                result = cyber_knowledge.ingest_local_file(path)
                if result.get("ok"):
                    print(
                        "JARVIS > Documento importado para a "
                        "Cyber Knowledge Vault."
                    )
                else:
                    print(
                        "JARVIS >",
                        json.dumps(
                            result,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                continue

            if lower == "/cyber status":
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_status(get_cyber_mentor_status())}"
                )
                continue
            if lower == "/cyber curriculum":
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_curriculum(get_cyber_curriculum())}"
                )
                continue
            if lower == "/cyber audit":
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_posture(get_cybersecurity_posture())}"
                )
                continue
            if lower == "/cyber audit raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        get_cybersecurity_posture(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower.startswith("/network name "):
                raw = text[len("/network name "):].strip(); parts = raw.split(maxsplit=1)
                if len(parts) < 2:
                    print("JARVIS > Usa: /network name IP-ou-MAC Nome")
                else:
                    print("JARVIS >", json.dumps(inventory.label(parts[0], parts[1]), ensure_ascii=False, indent=2))
                continue

            if lower == "/research status":
                print(
                    "JARVIS >",
                    json.dumps(
                        research_engine.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower in {"/cloud", "/cloud status", "/cloud test", "/cloud diagnose", "/cloud clear"}:
                print("JARVIS > External AI: HARD BLOCKED. O Core permite apenas Qwen local + pesquisa Web direta com síntese local.")
                continue

            if lower == "/speed":
                status = performance.status()
                pressure = status.get("pressure") or {}
                print(
                    "JARVIS > "
                    f"mode={status.get('mode')} | "
                    f"pressure={pressure.get('level')} | "
                    f"avg={status.get('average_latency_ms')}ms | "
                    f"GPU sample={status.get('gpu_sampling_seconds')}s | "
                    f"backend={settings.local_llm_backend} | "
                    f"brain=local-only-ai | research={'on' if research_engine.available() else 'off'} | external-ai=blocked | "
                    "selective-tools=ON"
                )
                continue

            if lower == "/perf status":
                print(
                    "JARVIS >",
                    json.dumps(
                        performance.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower in {
                "/perf auto",
                "/perf fast",
                "/perf balanced",
                "/perf deep",
                "/perf eco",
            }:
                mode = lower.split()[-1]
                result = performance.set_mode(mode)
                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower in {"/perf release", "/vram release"}:
                result = brain.release_all_models(
                    reason="manual_release",
                    include_configured=True,
                )
                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/vram status":
                print(
                    "JARVIS >",
                    json.dumps(
                        brain.residency_status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/warmup":
                result = {
                    "llm": brain.warmup(),
                }
                print(
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                continue
            if lower == "/security blocked files":
                result = audit_windows_blocked_files()
                print(
                    format_windows_block_audit(
                        result,
                        detail="standard",
                    )
                )
                continue
            if lower == "/security blocked files full":
                result = audit_windows_blocked_files()
                print(
                    format_windows_block_audit(
                        result,
                        detail="full",
                    )
                )
                continue
            if lower == "/security blocked files raw":
                result = audit_windows_blocked_files()
                print(
                    format_windows_block_audit(
                        result,
                        detail="raw",
                    )
                )
                continue

            if lower == "/security scan":
                result = read_tool("run_security_audit")
                print(f"JARVIS >\n{format_security_overview(result)}")
                continue
            if lower == "/security scan full":
                result = read_tool(
                    "run_security_audit"
                )
                print(
                    f"JARVIS >\n"
                    f"{format_security_full(result)}"
                )
                continue
            if lower == "/security scan raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool(
                            "run_security_audit"
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/security admins":
                result = read_tool(
                    "run_security_audit"
                )
                text = format_security_full(
                    result
                )
                start = text.find("CONTA")
                end = text.find("\n\nSESSÕES")
                section = (
                    text[start:end]
                    if start >= 0 and end > start
                    else text
                )
                print(f"JARVIS >\n{section}")
                continue
            if lower == "/security admins raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool(
                            "get_admin_accounts"
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/security sessions":
                result = read_tool(
                    "run_security_audit"
                )
                text = format_security_full(
                    result
                )
                start = text.find("SESSÕES")
                end = text.find("\n\nPROTEÇÃO")
                section = (
                    text[start:end]
                    if start >= 0 and end > start
                    else text
                )
                print(f"JARVIS >\n{section}")
                continue
            if lower == "/security sessions raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool(
                            "get_active_user_sessions"
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/security posture":
                result = read_tool(
                    "run_security_audit"
                )
                text = format_security_full(
                    result
                )
                start = text.find("PROTEÇÃO")
                end = text.find("\n\nREDE")
                section = (
                    text[start:end]
                    if start >= 0 and end > start
                    else text
                )
                print(f"JARVIS >\n{section}")
                continue
            if lower == "/security posture raw":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool(
                            "get_windows_security_posture"
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/network status":
                result = read_tool(
                    "get_network_security_snapshot",
                    {"connection_limit": 80},
                )
                print(f"JARVIS >\n{format_network_overview(result)}")
                continue
            if lower == "/network devices":
                result = read_tool(
                    "get_network_security_snapshot",
                    {"connection_limit": 20},
                )
                print(f"JARVIS >\n{format_network_devices(result)}")
                continue
            if lower == "/network devices all":
                result = read_tool(
                    "get_network_security_snapshot",
                    {"connection_limit": 20},
                )
                print(
                    f"JARVIS >\n"
                    f"{format_network_devices(result, include_stale=True)}"
                )
                continue
            if lower == "/network status full":
                print(
                    "JARVIS >",
                    json.dumps(
                        read_tool(
                            "get_network_security_snapshot",
                            {"connection_limit": 200},
                        ),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue


            if lower == "/desktop agent status":
                print("JARVIS >", json.dumps(read_tool("desktop_agent_status"), ensure_ascii=False, indent=2))
                continue
            if lower == "/desktop observe":
                print("JARVIS >", json.dumps(read_tool("desktop_observe"), ensure_ascii=False, indent=2))
                continue
            if lower == "/desktop windows":
                print("JARVIS >", json.dumps(read_tool("desktop_list_windows", {"limit": 30}), ensure_ascii=False, indent=2))
                continue
            if lower == "/desktop screenshot":
                print("JARVIS >", json.dumps(read_tool("desktop_capture_screen"), ensure_ascii=False, indent=2))
                continue

            if lower == "/vision status":
                print("JARVIS >", json.dumps(read_tool("get_vision_status"), ensure_ascii=False, indent=2))
                continue
            if lower == "/vision capture":
                print("JARVIS >", json.dumps(read_tool("capture_current_screen"), ensure_ascii=False, indent=2))
                continue
            if lower == "/vision analyze" or lower.startswith("/vision analyze "):
                prompt = text[len("/vision analyze"):].strip()
                args = {"fresh_capture": True}
                if prompt:
                    args["prompt"] = prompt
                print("JARVIS >", json.dumps(read_tool("analyze_current_screen", args), ensure_ascii=False, indent=2))
                continue
            if lower == "/vision camera" or lower.startswith("/vision camera "):
                prompt = text[len("/vision camera"):].strip()
                args = {}
                if prompt:
                    args["prompt"] = prompt
                print("JARVIS >", json.dumps(read_tool("analyze_camera_frame", args), ensure_ascii=False, indent=2))
                continue

            if lower in {"/books status", "/livros estado"}:
                print(
                    f"JARVIS >\n"
                    f"{format_book_library_status(book_library.stats())}"
                )
                continue
            if lower in {"/books sync", "/livros sincronizar"}:
                print(
                    f"JARVIS >\n"
                    f"{format_book_library_sync(book_library.sync())}"
                )
                continue
            if lower in {"/books sync force", "/livros sincronizar tudo"}:
                print(
                    f"JARVIS >\n"
                    f"{format_book_library_sync(book_library.sync(force=True))}"
                )
                continue
            if lower.startswith("/books search ") or lower.startswith("/livros pesquisar "):
                prefix = (
                    "/books search "
                    if lower.startswith("/books search ")
                    else "/livros pesquisar "
                )
                query = text[len(prefix):].strip()
                print(
                    f"JARVIS >\n"
                    f"{format_book_library_search(book_library.search(query, limit=8))}"
                )
                continue
            if lower == "/guardian status":
                print("JARVIS >", json.dumps(read_tool("get_system_guardian_status"), ensure_ascii=False, indent=2))
                continue
            if lower == "/guardian scan":
                print("JARVIS >", json.dumps(read_tool("run_system_guardian_scan"), ensure_ascii=False, indent=2))
                continue
            if lower == "/guardian baseline":
                print("JARVIS >", json.dumps(read_tool("create_system_guardian_baseline"), ensure_ascii=False, indent=2))
                continue

            if lower == "/purple status":
                print("JARVIS >", json.dumps(read_tool("get_purple_team_status"), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/purple run "):
                raw = text[len("/purple run "):].strip()
                parts = raw.split(maxsplit=1)
                args = {"target": parts[0]}
                if len(parts) > 1 and parts[1].strip():
                    try:
                        args["ports"] = [int(x.strip()) for x in parts[1].split(",") if x.strip()]
                    except ValueError:
                        print("JARVIS > Portas inválidas. Usa: /purple run IP 22,80,443")
                        continue
                print("JARVIS >", json.dumps(read_tool("run_purple_team_assessment", args), ensure_ascii=False, indent=2))
                continue
            if lower == "/purple retest" or lower.startswith("/purple retest "):
                target = text[len("/purple retest"):].strip()
                args = {"target": target} if target else {}
                print("JARVIS >", json.dumps(read_tool("validate_purple_team_mitigation", args), ensure_ascii=False, indent=2))
                continue

            if lower == "/planner status":
                print("JARVIS >", json.dumps(read_tool("get_task_planner_status"), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/planner run "):
                goal = text[len("/planner run "):].strip()
                print("JARVIS >", json.dumps(read_tool("run_autonomous_task", {"goal": goal}), ensure_ascii=False, indent=2))
                continue
            if lower == "/planner list":
                print("JARVIS >", json.dumps(read_tool("list_task_plans", {"limit": 10}), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/planner resume "):
                plan_id = text[len("/planner resume "):].strip()
                print("JARVIS >", json.dumps(read_tool("execute_task_plan", {"plan_id": plan_id}), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/planner adapt "):
                plan_id = text[len("/planner adapt "):].strip()
                print("JARVIS >", json.dumps(read_tool("adapt_task_plan", {"plan_id": plan_id}), ensure_ascii=False, indent=2))
                continue

            if lower == "/memory graph":
                print("JARVIS >", json.dumps(read_tool("get_memory_graph_status"), ensure_ascii=False, indent=2))
                continue

            if lower == "/repair diagnose":
                print("JARVIS >", json.dumps(read_tool("run_self_diagnostics"), ensure_ascii=False, indent=2))
                continue
            if lower == "/repair safe":
                print("JARVIS >", json.dumps(read_tool("run_safe_self_repair"), ensure_ascii=False, indent=2))
                continue

            if lower == "/skills status":
                print("JARVIS >", json.dumps(skills.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/skills discover":
                print("JARVIS >", json.dumps(skills.discover_external(), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/skills trust "):
                path = text[len("/skills trust "):].strip().strip('"')
                print("JARVIS >", json.dumps(skills.trust_external(path), ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/skills untrust "):
                skill_id = text[len("/skills untrust "):].strip()
                print("JARVIS >", json.dumps(skills.untrust_external(skill_id), ensure_ascii=False, indent=2))
                continue

            if lower == "/telemetry":
                print(json.dumps(telemetry.latest(), ensure_ascii=False, indent=2))
                continue
            if lower == "/debug on":
                debug_terminal["enabled"] = True
                print("JARVIS > Debug do terminal ativado.")
                continue
            if lower == "/debug off":
                debug_terminal["enabled"] = False
                print("JARVIS > Debug do terminal desativado.")
                continue
            if lower == "/debug status":
                state = "ON" if debug_terminal["enabled"] else "OFF"
                print(
                    f"JARVIS > Debug do terminal: {state}. "
                    "Os eventos continuam guardados em logs\\events.jsonl."
                )
                continue

            if lower == "/events":
                for e in events.recent(20):
                    print(f"{e.timestamp} | {e.name} | {json.dumps(e.data, ensure_ascii=False)}")
                continue
            if lower == "/autonomy status":
                print(
                    "JARVIS >",
                    json.dumps(
                        autonomy.status(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/autonomy pending":
                print(
                    "JARVIS >",
                    json.dumps(
                        {
                            "ok": True,
                            "pending": autonomy.pending(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/autonomy history":
                print(
                    "JARVIS >",
                    json.dumps(
                        {
                            "ok": True,
                            "history": autonomy.history(40),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/autonomy revoke":
                print(
                    "JARVIS >",
                    json.dumps(
                        autonomy.revoke_all(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower.startswith("/authorize "):
                token = text.split(
                    maxsplit=1
                )[1].strip()
                execute_owner_authorization(
                    token
                )
                continue

            if lower.startswith("/deny "):
                token = text.split(
                    maxsplit=1
                )[1].strip()
                result = autonomy.deny(
                    token
                )
                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            # Natural decisions also apply to the local SecurityPolicy queue.
            # They are consumed only when the choice is unambiguous across both
            # permission systems; a scoped sentence must name the pending action.
            decision_text = lower.strip(" .!?")
            local_approval = decision_text in {
                "sim", "podes", "pode", "autoriza", "autorizo",
                "sim podes", "sim pode", "sim autoriza", "sim autorizo",
                "podes fazer", "pode fazer", "tens a minha autorização",
                "tens a minha autorizacao", "tem a minha autorização",
                "tem a minha autorizacao", "sim podes fazer",
            } or bool(re.match(r"^(?:sim[,;]?\s*)?autorizo\b", decision_text))
            local_denial = decision_text in {
                "não", "nao", "agora não", "agora nao", "não autorizo",
                "nao autorizo", "recuso", "nego",
            } or bool(re.match(r"^(?:não|nao)\s+autorizo\b", decision_text))
            security_pending_rows = security.pending()
            autonomy_pending_rows = autonomy.pending()
            if (local_approval or local_denial) and security_pending_rows:
                total_pending = len(security_pending_rows) + len(autonomy_pending_rows)
                if total_pending != 1:
                    print("JARVIS > Tenho várias ações pendentes. Diga qual delas quer autorizar ou recusar.")
                    continue
                pending_action = security_pending_rows[0]
                scoped_terms = {
                    "close_application": ("fecha", "fechar", "encerra", "bloco de notas", "notepad"),
                    "desktop_type_text": ("escreve", "escrever", "texto"),
                    "desktop_hotkey": ("atalho", "tecla", "premir", "pressionar"),
                    "desktop_click": ("clica", "clicar", "clique"),
                    "lock_workstation": ("bloqueia", "tranca", "computador", "pc"),
                }
                extra_scope = decision_text not in {
                    "sim", "podes", "pode", "autoriza", "autorizo",
                    "sim podes", "sim pode", "sim autoriza", "sim autorizo",
                    "podes fazer", "pode fazer", "não", "nao", "agora não",
                    "agora nao", "não autorizo", "nao autorizo", "recuso", "nego",
                }
                expected = scoped_terms.get(pending_action.tool_name, ())
                if extra_scope and expected and not any(term in decision_text for term in expected):
                    print("JARVIS > A autorização não corresponde à ação local pendente; não executei nada.")
                    continue
                if local_denial:
                    security.clear_pending(pending_action.token)
                    print("JARVIS > A ação local pendente foi recusada e removida.")
                    continue
                result = tools.confirm(pending_action.token)
                planner = skill_context.services.get("task_planner")
                if planner is not None:
                    try:
                        planner.record_confirmation(pending_action.token, result)
                    except Exception:
                        pass
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            # Natural OWNER approval without a token is accepted only when
            # exactly one action is pending, so "Autorizo" cannot accidentally
            # widen or select the wrong scope.
            natural_approval = lower.strip(" .!?") in {
                "sim", "podes", "pode", "autoriza", "autorizo", "pesquisa",
                "sim podes", "sim pode", "sim autoriza", "sim autorizo",
                "podes fazer", "pode fazer", "tens a minha autorizacao",
                "tem a minha autorizacao", "sim podes fazer",
            }
            if natural_approval:
                pending_rows = autonomy.pending()
                if len(pending_rows) == 1:
                    execute_owner_authorization(str(pending_rows[0].get("token") or ""))
                    continue
                if len(pending_rows) > 1:
                    # A generic yes must never select between unrelated scopes.
                    learning_rows = [
                        row for row in pending_rows
                        if row.get("capability") == "external_learning"
                    ]
                    if lower.strip(" .!?") == "pesquisa" and len(learning_rows) == 1:
                        execute_owner_authorization(str(learning_rows[0].get("token") or ""))
                        continue
                    print("JARVIS > Tenho várias ações pendentes. Diga qual delas quer autorizar.")
                    continue

            natural_denial = lower.strip(" .!?") in {
                "nao", "não", "agora nao", "agora não", "nao autorizo",
                "não autorizo", "recuso", "nego",
            }
            if natural_denial:
                pending_rows = autonomy.pending()
                if len(pending_rows) == 1:
                    result = autonomy.deny(str(pending_rows[0].get("token") or ""))
                    print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                    continue

            # Natural typed equivalents remain token-bound.
            auth_match = re.fullmatch(
                r"(?:jarvis[ ,]+)?autorizo\s+([a-f0-9]{6})[.!]?",
                lower,
            )
            if auth_match:
                execute_owner_authorization(
                    auth_match.group(1)
                )
                continue

            deny_match = re.fullmatch(
                r"(?:jarvis[ ,]+)?(?:nego|recuso|nao autorizo|não autorizo)\s+([a-f0-9]{6})[.!]?",
                lower,
            )
            if deny_match:
                result = autonomy.deny(
                    deny_match.group(1)
                )
                print(
                    "JARVIS >",
                    json.dumps(
                        result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue

            if lower == "/pending":
                pending = security.pending()
                if not pending:
                    print("JARVIS > Não existem ações pendentes.")
                for p in pending:
                    print(f"{p.token} | {p.tool_name} | {p.arguments} | {p.created_at}")
                continue
            if lower.startswith("/confirm "):
                token = text.split(maxsplit=1)[1].strip()
                result = tools.confirm(token)
                planner = skill_context.services.get("task_planner")
                if planner is not None:
                    try:
                        planner.record_confirmation(token, result)
                    except Exception:
                        pass
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/cancel "):
                token = text.split(maxsplit=1)[1].strip()
                ok = security.clear_pending(token)
                print("JARVIS >", "Cancelado." if ok else "Token desconhecido.")
                continue

            with command_lock:
                request_generation = silence_latch.generation()
                result = process_request(text)
                answer = result.answer
                route = result.route
                command_ms = result.elapsed_ms
                hybrid = result.hybrid
                if not silence_latch.output_allowed(request_generation):
                    silence_latch.mark_suppressed_response("response")
                    continue
                print(f"\nJARVIS > {answer}\n")
                cloud_cost = (
                    f" cloud~${hybrid.cloud_estimated_usd:.6f}"
                    if hybrid and hybrid.route.startswith("CLOUD")
                    else ""
                )
                if debug_terminal["enabled"]:
                    print(
                        f"  [PERF  ] command={command_ms}ms "
                        f"route={route}{cloud_cost}"
                    )
                events.emit("LLM_RESPONSE_READY", chars=len(answer), route=route, source="terminal")
    finally:
        application.stop_activity_trace()

        if settings.skills_enabled:
            skills.stop_all()

        application.release_models_on_shutdown()

        reminder_service.stop()
        security_watch_service.stop()
        proactive_service.stop()
        companion_service.stop()
        book_library_service.stop()
        cyber_knowledge_service.stop()

        application.stop_runtime_services()


if __name__ == "__main__":
    main()
