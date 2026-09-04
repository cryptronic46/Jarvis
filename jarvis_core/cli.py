from __future__ import annotations

import json
import re
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
from jarvis_core.core.cloud_brain import CloudBrain
from jarvis_core.security.policy import SecurityPolicy
from jarvis_core.skills import SkillContext, SkillManager
from jarvis_core.services.telemetry import TelemetryService
from jarvis_core.services.desktop_integration import DesktopIntegrationService
from jarvis_core.services.speech import SpeechService, SpeechConfig
from jarvis_core.services.listening import MicrophoneService, ListeningConfig
from jarvis_core.services.av_devices import webcam_audio_score
from jarvis_core.services.speaker_verification import SpeakerVerifier, SpeakerConfig
from jarvis_core.services.wakeword import WakeWordService, WakeWordConfig
from jarvis_core.services.voice_engine_v2 import VoiceEngineV2
from jarvis_core.services.voice_pipeline import listening_config_from_settings, voice_v2_config_from_settings, speaker_config_from_settings
from jarvis_core.services.listening_watchdog import ListeningWatchdogService
from jarvis_core.services.silence_latch import SilenceLatchService
from jarvis_core.services.activity_trace import ActivityTraceService
from jarvis_core.services.idle_mind import IdleMindService
from jarvis_core.services.user_memory import store as user_memory_store
from jarvis_core.services.startup_briefing import build_startup_briefing
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
from jarvis_core.services.privacy import privacy_state
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
    parse_direct_external_learning_order,
    parse_learning_goal,
)
from jarvis_core.tools.security_audit import (
    format_security_overview,
    format_security_full,
    format_network_overview,
    format_network_devices,
)
from jarvis_core.tools.windows_actions import AppRegistry


BANNER_TEMPLATE = """
========================================
              J A R V I S
             CORE {version}
        SKILLS | EYES | HANDS
========================================
"""


def local_pdf_library_learning_requested(text: str) -> bool:
    value = str(text or "").casefold()
    asks_to_learn = bool(re.search(r"\b(?:aprende|aprender|estuda|estudar|indexa|indexar)\b", value))
    targets_pdfs = bool(re.search(r"\bpdfs?\b", value))
    targets_collection = bool(re.search(r"\b(?:todos|todas|documentos|livros|biblioteca)\b", value))
    external_source = bool(re.search(r"https?://|\b(?:web|internet|online)\b", value))
    return asks_to_learn and targets_pdfs and targets_collection and not external_source


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
    "SPEECH_STARTED":"VOICE",
    "SPEECH_FINISHED":"VOICE",
    "SPEECH_BACKEND_FAILED":"VOICE",
    "LISTENING_STARTED":"MIC",
    "MIC_CALIBRATED":"MIC",
    "SPEECH_DETECTED":"MIC",
    "AUDIO_CAPTURED":"MIC",
    "LISTENING_TIMEOUT":"MIC",
    "TRANSCRIPTION_STARTED":"STT",
    "TRANSCRIPTION_FINISHED":"STT",
    "STT_MODEL_LOADING":"STT",
    "STT_MODEL_READY":"STT",
    "STT_BACKEND_FAILED":"STT",
    "STT_RUNTIME_FALLBACK":"STT",
    "MIC_ERROR":"MIC",
    "MIC_CALIBRATION_CACHED":"MIC",
    "FAST_PATH_HIT":"FAST",
    "STT_PRELOADED":"WARM",
    "STT_PRELOAD_FAILED":"WARM",
    "LLM_PRELOADED":"WARM",
    "LLM_PRELOAD_FAILED":"WARM",
    "TTS_CACHE_HIT":"VOICE",
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
    "WAKE_SERVICE_STARTED":"WAKE",
    "WAKE_SERVICE_STOPPED":"WAKE",
    "WAKE_LISTENING":"WAKE",
    "WAKE_WORD_DETECTED":"WAKE",
    "WAKE_PROFILE_ENROLLED":"WAKE",
    "WAKE_PROFILE_DELETED":"WAKE",
    "WAKE_COMMAND_TRANSCRIBED":"WAKE",
    "WAKE_COMMAND_TRANSCRIPTION_FAILED":"WAKE",
    "WAKE_COMMAND_TIMEOUT":"WAKE",
    "VOICE_INTERRUPT_CANDIDATE":"VOICE",
    "VOICE_INTERRUPT_DETECTED":"VOICE",
    "VOICE_INTERRUPT_TRANSCRIBED":"VOICE",
    "VOICE_INTERRUPT_REJECTED_SELF_AUDIO":"VOICE",
    "VOICE_INTERRUPT_TRANSCRIPTION_FAILED":"VOICE",
    "VOICE_INTERRUPT_APPLIED":"VOICE",
    "WAKE_CANDIDATE":"WAKE",
    "WAKE_CANDIDATE_CONFIRMED":"WAKE",
    "WAKE_CANDIDATE_REJECTED":"WAKE",
    "VOICE_HEARD":"HEARD",
    "SILENCE_LATCHED":"SILENCE",
    "SILENCE_RELEASED":"SILENCE",
    "SILENCE_OUTPUT_SUPPRESSED":"SILENCE",
    "WAKE_AUDIO_OVERFLOW":"WAKE",
    "WAKE_STREAM_STATUS":"WAKE",
    "WAKE_STREAM_REUSED":"WAKE",
    "WAKE_STREAM_CLOSED":"WAKE",
    "WAKE_STREAM_OPENED":"WAKE",
    "WAKE_TTS_SUPPRESSED":"WAKE",
    "WAKE_TTS_RESUMED":"WAKE",
    "WAKE_CALIBRATED":"WAKE",
    "WAKE_LOW_SIGNAL":"WAKE",
    "WAKE_ERROR":"WAKE",
    "WAKE_CALLBACK_ERROR":"WAKE",
    "SPEAKER_OBSERVE":"VOICEID",
    "MIC_STREAM_NO_SIGNAL":"MIC",
    "MIC_STREAM_RECOVERY":"MIC",
    "MIC_DEVICE_RECOVERY":"MIC",
    "MIC_DEVICE_CANDIDATE_FAILED":"MIC",
    "MIC_DEVICE_SELECTED":"MIC",
    "SPEAKER_MODEL_LOADING":"VOICEID",
    "SPEAKER_MODEL_READY":"VOICEID",
    "SPEAKER_MODEL_FAILED":"VOICEID",
    "SPEAKER_ENROLLMENT_STARTED":"VOICEID",
    "SPEAKER_ENROLLMENT_FINISHED":"VOICEID",
    "SPEAKER_VERIFICATION_STARTED":"VOICEID",
    "SPEAKER_VERIFICATION_FINISHED":"VOICEID",
    "SPEAKER_LOCK_CHANGED":"VOICEID",
    "PROACTIVE_MESSAGE":"MIND",
    "DESKTOP_INTEGRATION_READY":"DESKTOP",
    "DESKTOP_BRIDGE_STARTED":"DESKTOP",
    "WALLPAPER_ENGINE_STARTED":"DESKTOP",
    "DESKTOP_BRIDGE_UNAVAILABLE":"DESKTOP",
    "WALLPAPER_ENGINE_UNAVAILABLE":"DESKTOP",
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
    "LIVE_WALLPAPER_STATE_STARTED":"HUD",
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
    elif event.name == "LISTENING_STARTED":
        detail = f" device={event.data.get('device')} {event.data.get('device_name')}"
    elif event.name == "MIC_CALIBRATED":
        detail = (
            f" noise={event.data.get('noise_rms')} "
            f"raw={event.data.get('raw_noise_mean')} "
            f"threshold={event.data.get('threshold')}"
        )
    elif event.name == "MIC_CALIBRATION_CACHED":
        detail = (
            f" threshold={event.data.get('threshold')} "
            f"age={event.data.get('age_seconds')}s"
        )
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
    elif event.name == "WAKE_LISTENING":
        detail = (
            f" backend={event.data.get('backend')} "
            f"device={event.data.get('device')} "
            f"{event.data.get('device_name')}"
        )
    elif event.name == "WAKE_WORD_DETECTED":
        detail = (
            f" keyword={event.data.get('keyword')} "
            f"score={event.data.get('score')} "
            f"threshold={event.data.get('threshold')} "
            f"whisper={event.data.get('whisper_used')}"
        )
    elif event.name == "WAKE_PROFILE_ENROLLED":
        detail = (
            f" samples={event.data.get('samples')} "
            f"threshold={event.data.get('threshold')} "
            f"mean={event.data.get('mean_similarity')}"
        )
    elif event.name == "WAKE_COMMAND_TRANSCRIBED":
        detail = (
            f" text={event.data.get('text')!r} "
            f"profile={event.data.get('profile')} "
            f"beam={event.data.get('beam')} "
            f"{event.data.get('elapsed_ms')}ms"
        )
    elif event.name == "WAKE_CALIBRATED":
        detail = (
            f" noise={event.data.get('noise_rms')} "
            f"threshold={event.data.get('threshold')}"
        )
    elif event.name == "WAKE_SPEECH_DETECTED":
        detail = (
            f" rms={event.data.get('rms')} "
            f"threshold={event.data.get('threshold')} "
            f"blocks={event.data.get('blocks')}"
        )
    elif event.name == "WAKE_CANDIDATE_TRANSCRIBED":
        detail = (
            f" text={event.data.get('transcript')!r} "
            f"accepted={event.data.get('accepted')} "
            f"score={event.data.get('score')} "
            f"{event.data.get('elapsed_ms')}ms"
        )
    elif event.name == "WAKE_CANDIDATE_REJECTED":
        detail = (
            f" reason={event.data.get('reason')} "
            f"duration={event.data.get('duration_seconds')}s "
            f"peak={event.data.get('peak_rms')} "
            f"ratio={event.data.get('peak_ratio')}"
        )
    elif event.name == "WAKE_ERROR":
        detail = f" error={event.data.get('error')}"
    elif event.name == "WAKE_LOW_SIGNAL":
        detail = (
            f" max_rms={event.data.get('max_rms')} "
            f"device={event.data.get('device')}"
        )
    elif event.name == "WAKE_STREAM_STATUS":
        detail = f" status={event.data.get('status')}"
    elif event.name == "WAKE_STREAM_OPENED":
        detail = (
            f" open_count={event.data.get('open_count')} "
            f"device={event.data.get('device')} "
            f"rate={event.data.get('sample_rate')}"
        )
    elif event.name == "WAKE_STREAM_REUSED":
        detail = (
            f" open_count={event.data.get('open_count')} "
            f"dropped={event.data.get('dropped_stale_blocks')}"
        )
    elif event.name == "WAKE_STREAM_CLOSED":
        detail = f" reason={event.data.get('reason')}"
    elif event.name == "WAKE_PHRASE_CAPTURED":
        detail = (
            f" duration={event.data.get('duration_seconds')}s "
            f"single_stream={event.data.get('single_stream')}"
        )
    elif event.name == "SPEAKER_OBSERVE":
        detail = (
            f" accepted={event.data.get('accepted')} "
            f"score={event.data.get('score')}"
        )
    elif event.name in {"STT_PRELOADED","LLM_PRELOADED"}:
        detail = f" {event.data.get('elapsed_ms')}ms"
    elif event.name == "MIC_STREAM_NO_SIGNAL":
        detail = (
            f" device={event.data.get('device')} "
            f"max_rms={event.data.get('max_rms')}"
        )
    elif event.name == "MIC_STREAM_RECOVERY":
        detail = (
            f" retry={event.data.get('next_attempt')} "
            f"after={event.data.get('wait_seconds')}s"
        )
    elif event.name == "MIC_DEVICE_RECOVERY":
        detail = (
            f" stale={event.data.get('stale_device')} "
            f"preferred={event.data.get('preferred_device')} "
            f"{event.data.get('preferred_name')}"
        )
    elif event.name == "MIC_DEVICE_CANDIDATE_FAILED":
        detail = (
            f" device={event.data.get('device')} "
            f"{event.data.get('device_name')} "
            f"hostapi={event.data.get('hostapi')} "
            f"error={event.data.get('error')}"
        )
    elif event.name == "MIC_DEVICE_SELECTED":
        detail = (
            f" device={event.data.get('device')} "
            f"{event.data.get('device_name')} "
            f"hostapi={event.data.get('hostapi')} "
            f"fallback={event.data.get('fallback_position')}"
        )
    elif event.name == "STT_MODEL_LOADING":
        detail = f" {event.data.get('model')} on {event.data.get('device')}"
    elif event.name == "STT_MODEL_READY":
        detail = f" backend={event.data.get('backend')}"
    elif event.name == "STT_RUNTIME_FALLBACK":
        detail = (
            f" {event.data.get('from_backend')} -> "
            f"{event.data.get('to_backend')}"
        )
    elif event.name == "TRANSCRIPTION_FINISHED":
        detail = (
            f" chars={event.data.get('chars')} "
            f"backend={event.data.get('backend')} "
            f"profile={event.data.get('profile')} "
            f"beam={event.data.get('beam_size')}"
        )
    elif event.name == "SPEAKER_VERIFICATION_FINISHED":
        detail = (
            f" accepted={event.data.get('accepted')} "
            f"score={event.data.get('score')} "
            f"threshold={event.data.get('threshold')}"
        )
    print(f"  [{label:<6}] {event.name}{detail}")


def help_text() -> str:
    return """
Comandos:
  /help             ajuda
  /health           testar cérebro local JARVIS/modelo
  /version          mostrar versão do Core
  /tools            ferramentas e risco
  /apps             aplicações autorizadas
  /appcheck APP     diagnosticar localização de uma aplicação
  /voice status     voz + motor de entrada + STT
  /voice doctor     diagnóstico completo do Voice Engine
  /voice benchmark  medir custo do wake v2 em tempo real
  /voice backend auto|v2|legacy  escolher motor de entrada (reinício)
  /voice release    libertar modelo Faster Whisper da RAM/VRAM
  /voice test       testar a voz
  /voice on         ativar respostas faladas
  /voice off        desativar respostas faladas
  /voice stop       interromper a fala atual
  /voice feminine   aplicar voz feminina Raquel (perfil Velvet)
  /companion status estado da presença social adaptativa
  /companion on|off ativar/desativar iniciativa social
  /companion flirt on|off permitir/bloquear flirt contextual
  /companion intensity 0..1 intensidade máxima do flirt
  /mic list         listar microfones disponíveis
  /mic status       mostrar microfone/STT atual
  /mic doctor       listar candidatos JBL pela ordem de tentativa
  /mic use N        escolher microfone pelo índice
  /mic default      voltar ao microfone predefinido
  /av status        estado conjunto webcam + microfone
  /av auto          detetar e priorizar webcam/microfone integrado
  /av microphones   listar entradas e pontuação provável de webcam
  /av probe         testar quais entradas entregam sinal real
  /av cameras       listar câmaras locais disponíveis
  /av mic N         fixar o microfone da webcam pelo índice
  /av camera N      fixar a câmara pelo índice
  /av webcam on|off ativar/desativar prioridade automática da webcam
  /listen           ouvir uma frase e enviá-la ao JARVIS
  /listening status estado combinado do microfone/wake/watchdog
  /listening recover recuperar o stream de escuta sem reiniciar o Core
  /stt status       perfil e parâmetros de precisão do reconhecimento
  /stt test         capturar uma frase e mostrar diagnóstico STT sem executar
  /silence status   estado do silêncio conversacional latched
  /silence on|off   silenciar até novo wake / libertar silêncio
  /activity on|off  mostrar/ocultar trace seguro em tempo real
  /activity status  estado + atividade recente (sem chain-of-thought)
  /activity last    últimas decisões/ações observáveis
  /wake status      estado do Always Listening
  /wake doctor      testar wake acústico + JBL
  /wake test        captar 'Jarvis' e medir score/threshold
  /wake enroll      registar a tua pronúncia de 'Jarvis'
  /wake delete      apagar o perfil acústico de 'Jarvis'
  /wake on          iniciar Always Listening
  /interrupt enroll registar a frase 'Cala-te'
  /interrupt status estado da interrupção por voz
  /interrupt delete apagar perfil 'Cala-te'
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
  /privacy status   estado do modo privado
  /privacy on|off   bloquear/permitir pesquisa externa
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
  /mind speech on|off fala espontânea
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
  /wake off         parar Always Listening
  /voiceid status   estado do Voice Lock
  /voiceid doctor   testar backend/modelo antes do registo
  /voiceid enroll   registar a tua voz (5 amostras)
  /voiceid on       aceitar apenas a voz registada
  /voiceid off      desativar filtro de voz
  /voiceid threshold X  ajustar limiar de semelhança
  /voiceid delete   apagar perfil de voz local
  /desktop status   estado da integração Core + Wallpaper Engine
  /desktop ensure   garantir bridge e Wallpaper Engine ativos
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
  /warmup           pré-carregar STT, Voice Lock e LLM
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
    # every startup so release migrations (including the 0.21 voice profile)
    # apply without overwriting custom OWNER choices.
    Settings.ensure_file_schema()
    settings = Settings.load()
    events = EventBus(settings.log_dir, max_bytes=settings.log_max_bytes, backup_count=settings.log_backup_count)
    desktop = DesktopIntegrationService(
        events,
        enabled=settings.desktop_integration_enabled,
        core_root=Path(__file__).resolve().parents[1],
        wallpaper_root=settings.desktop_wallpaper_root,
        bridge_port=settings.desktop_bridge_port,
        bridge_auto_start=settings.desktop_bridge_auto_start,
        wallpaper_engine_auto_start=settings.desktop_wallpaper_engine_auto_start,
        wallpaper_engine_path=settings.desktop_wallpaper_engine_path,
    )
    desktop_state = desktop.start()

    # Quiet terminal is the product default. EventBus continues to persist
    # all diagnostics to logs/events.jsonl; /debug on only changes display.
    debug_terminal = {"enabled": False}
    memory = user_memory_store()
    profiles = profile_manager()
    persistent_context = context_store()
    agenda = agenda_store()
    routines = routine_manager()
    inventory = network_inventory()
    local_files = configure_file_index(extra_roots=[settings.book_library_root])
    integrations = integration_registry()
    privacy = privacy_state()
    cyber_knowledge = cyber_vault()
    book_library = configure_book_library(
        settings.book_library_root,
        settings.book_library_db_path,
        chunk_chars=settings.book_library_chunk_chars,
        chunk_overlap=settings.book_library_chunk_overlap,
    )
    cognition = personal_cognition()
    self_engine = synthetic_self()

    user_profile = memory.profile()
    active_profile = profiles.active()
    user_address = active_profile.get("address_as") or user_profile.get("address_as") or "Senhor"
    security = SecurityPolicy()
    telemetry = TelemetryService(
        events,
        interval_seconds=settings.telemetry_interval_seconds,
        history_seconds=settings.telemetry_history_seconds,
        gpu_interval_seconds=(
            settings.performance_gpu_sample_interval_seconds
        ),
    )
    performance = PerformanceGovernor(
        settings,
        events,
        telemetry,
    )
    speech = SpeechService(
        events,
        SpeechConfig(
            enabled=settings.speech_enabled,
            backend=settings.speech_backend,
            edge_voice=settings.speech_voice,
            rate=settings.speech_rate,
            pitch=settings.speech_pitch,
            persona_profile=settings.speech_persona_profile,
            sapi_prefer_gender=settings.speech_sapi_prefer_gender,
            volume=settings.speech_volume,
            max_chars=settings.speech_max_chars,
            fallback_sapi=settings.speech_fallback_sapi,
            cache_enabled=settings.speech_cache_enabled,
            cache_dir=settings.speech_cache_dir,
            cache_max_bytes=settings.speech_cache_max_bytes,
            cache_max_files=settings.speech_cache_max_files,
        ),
    )
    def build_microphone(*, model: str, stt_device: str) -> MicrophoneService:
        return MicrophoneService(
            events,
            ListeningConfig(
                device=settings.mic_device,
                language=settings.stt_language,
                model=model,
                stt_device=stt_device,
                download_root=settings.stt_download_root,
                calibration_seconds=settings.mic_calibration_seconds,
                start_timeout_seconds=settings.mic_start_timeout_seconds,
                max_phrase_seconds=settings.mic_max_phrase_seconds,
                silence_seconds=settings.mic_silence_seconds,
                threshold_multiplier=settings.mic_threshold_multiplier,
                threshold_floor=settings.mic_threshold_floor,
                beam_size=settings.stt_beam_size,
                wake_candidate_beam_size=settings.wake_candidate_beam_size,
                command_beam_size=settings.wake_stt_beam_size,
                command_retry_beam_size=settings.wake_stt_retry_beam_size,
                command_low_confidence_avg_logprob=settings.wake_stt_low_confidence_avg_logprob,
                command_low_confidence_no_speech=settings.wake_stt_low_confidence_no_speech,
                command_reject_avg_logprob=settings.wake_stt_reject_avg_logprob,
                command_reject_no_speech=settings.wake_stt_reject_no_speech,
                wake_reject_avg_logprob=settings.wake_candidate_reject_avg_logprob,
                wake_reject_no_speech=settings.wake_candidate_reject_no_speech,
                normalize_command_audio=settings.stt_normalize_command_audio,
                command_target_rms=settings.stt_command_target_rms,
                command_max_gain=settings.stt_command_max_gain,
                command_trim_silence=settings.stt_command_trim_silence,
                command_trim_padding_ms=settings.stt_command_trim_padding_ms,
                command_trim_floor_rms=settings.stt_command_trim_floor_rms,
                command_initial_prompt=settings.wake_stt_initial_prompt,
                command_hotwords=settings.wake_stt_hotwords,
                stream_retries=settings.mic_stream_retries,
                stream_recovery_seconds=settings.mic_stream_recovery_seconds,
                no_signal_rms=settings.mic_no_signal_rms,
                cpu_threads=settings.stt_cpu_threads,
                calibration_cache_seconds=settings.mic_calibration_cache_seconds,
                cached_calibration_blocks=settings.mic_cached_calibration_blocks,
                preferred_device_index=settings.mic_device,
                preferred_device_name=settings.mic_preferred_device_name,
                preferred_handsfree=settings.mic_preferred_handsfree,
                preferred_samplerate=settings.mic_preferred_samplerate,
                prefer_webcam_audio=settings.av_webcam_primary_enabled,
                webcam_name_hint=settings.av_webcam_name_hint,
                probe_min_signal_rms=settings.av_probe_min_signal_rms,
                verified_signal_ttl_seconds=settings.av_verified_signal_ttl_seconds,
            ),
        )

    legacy_microphone = build_microphone(
        model=settings.stt_model,
        stt_device=settings.stt_device,
    )
    # 0.27.6: Voice v2 and full_system_validation share this exact config factory.
    v2_microphone = MicrophoneService(
        events,
        listening_config_from_settings(settings, voice_v2=True),
    )
    # Closures below resolve this binding at call time; it is switched to the
    # v2 transcriber after the voice backend has passed its startup doctor.
    microphone = legacy_microphone
    speaker = SpeakerVerifier(events, speaker_config_from_settings(settings))
    # Health baseline: an enabled lock must be usable. If Torch or the
    # configured model is unavailable, disable only the effective runtime lock
    # instead of breaking every voice command or pretending protection is active.
    speaker_lock_health = {"ok": True, "disabled": False}
    if speaker.config.enabled:
        speaker_lock_health = speaker.ensure_ready()
        if not speaker_lock_health.get("ok"):
            speaker.set_enabled(False)
            speaker_lock_health["disabled"] = True
            events.emit(
                "SPEAKER_LOCK_AUTO_DISABLED",
                error=speaker_lock_health.get("error"),
                message=str(speaker_lock_health.get("message") or "")[:240],
            )
    apps = AppRegistry("apps.json")
    cyber_range = CyberRangeManager(
        settings.cyber_range_state_path,
        enabled=settings.cyber_range_enabled,
        probe_timeout_seconds=settings.cyber_range_probe_timeout_seconds,
    )
    set_cyber_range_manager(cyber_range)
    kali_bridge = KaliBridgeManager(
        settings.kali_bridge_state_path,
        enabled=settings.kali_bridge_enabled,
        ssh_executable=settings.kali_bridge_ssh_executable,
        connect_timeout_seconds=settings.kali_bridge_connect_timeout_seconds,
        command_timeout_seconds=settings.kali_bridge_command_timeout_seconds,
        output_max_chars=settings.kali_bridge_output_max_chars,
        known_hosts_path=settings.kali_bridge_known_hosts_path,
        vm_provider=settings.kali_vm_provider,
        vm_identifier=settings.kali_vm_identifier,
        vm_visible=settings.kali_vm_visible,
        activity_log_path=settings.kali_activity_log_path,
    )
    set_kali_bridge_manager(kali_bridge)
    tools = ToolRegistry(events, security, telemetry, apps)
    autonomy = AutonomyGuardian(
        settings,
        events,
    )
    set_autonomy_guardian(
        autonomy
    )

    brain = JarvisBrain(
        settings,
        events,
        tools,
        performance=performance,
    )
    # External AI is structurally blocked. CloudBrain remains a compatibility
    # object only; HybridBrain must never route execution to it.
    cloud_brain = CloudBrain(settings, events, tools)
    research_engine = LocalResearchEngine(settings, events, brain)

    skill_context = SkillContext(
        settings=settings,
        events=events,
        registry=tools,
        brain=brain,
        desktop=desktop,
        apps=apps,
        memory=memory,
        cyber_range=cyber_range,
        kali_bridge=kali_bridge,
    )
    skills = SkillManager(
        skill_context,
        external_root=settings.skills_external_root,
        trust_path=settings.skills_trust_path,
        external_enabled=(
            settings.skills_enabled
            and settings.skills_external_enabled
        ),
    )
    if settings.skills_enabled:
        skills.load_all()

    hybrid_brain = HybridBrain(
        settings,
        events,
        local_brain=brain,
        cloud_brain=cloud_brain,
        performance=performance,
        autonomy=autonomy,
        research_engine=research_engine,
    )
    fast_router = FastCommandRouter(events, tools, apps)
    command_lock = RLock()
    silence_latch = SilenceLatchService(
        events,
        enabled=settings.silence_latch_enabled,
    )
    activity_trace = ActivityTraceService(
        events,
        path=settings.activity_trace_path,
        enabled=settings.activity_trace_enabled,
        live=settings.activity_trace_live,
    )
    activity_trace.start()

    def current_address() -> str:
        return profiles.active().get("address_as") or user_address

    def is_silence_command(value: str) -> bool:
        normalized = str(value or "").lower().replace("-", " ")
        normalized = " ".join(normalized.split())
        compact = normalized.replace(" ", "")
        return (
            "calate" in compact
            or "para de falar" in normalized
            or normalized in {"silencio", "silêncio", "fica calada", "fica em silencio", "fica em silêncio"}
        )

    wake_holder = {"service": None}
    wake_followup_state = {"pending": False}
    learning_followup_state = {"topic": "", "created_at": 0.0}

    def read_tool(name: str, arguments: dict | None = None):
        raw = tools.execute(name, arguments or {})
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "error": "INVALID_TOOL_RESULT", "raw": raw}

    def process_request(user_text: str, *, source: str = "terminal"):
        """Fast Path -> local reasoning or direct-web/local-synthesis research."""
        command_started = monotonic()
        try:
            self_engine.observe_owner_input(user_text, source=source)
        except Exception as exc:
            events.emit(
                "SYNTHETIC_SELF_INPUT_OBSERVE_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )
        voice_origin = str(source).lower() in {"wake", "voice", "manual_voice", "manual"}
        fast = fast_router.dispatch(user_text, voice_origin=voice_origin)
        if fast.handled:
            # Fast-path text bypasses JarvisBrain, so apply the same final output
            # policy here (pt-PT localization, emoji policy, duplicate cleanup).
            fast.response = sanitize_assistant_text(fast.response, user_text=user_text)
            route = f"FAST/{fast.route}"
            elapsed = round((monotonic() - command_started) * 1000)
            if settings.persistent_context_enabled:
                persistent_context.record(user_text, fast.response, route)
            cognition.observe_interaction(user_text, fast.response, route)
            try:
                self_engine.observe_outcome(
                    owner_text=user_text,
                    assistant_text=fast.response,
                    route=route,
                    success=True,
                )
            except Exception as exc:
                events.emit(
                    "SYNTHETIC_SELF_OUTCOME_OBSERVE_ERROR",
                    error=f"{type(exc).__name__}: {exc}",
                )
            performance.record_request(
                elapsed_ms=elapsed,
                route=route,
            )
            return fast.response, route, elapsed, None

        if (
            voice_engine_state.get("effective") == "v2"
            and bool(getattr(settings, "voice_v2_vram_handoff_enabled", True))
        ):
            try:
                stt_state = microphone.stt_residency_status()
                if str(stt_state.get("backend") or "").lower().startswith("cuda/"):
                    released = microphone.release_stt()
                    events.emit("VOICE_V2_VRAM_TO_REASONING", result=released)
            except Exception as exc:
                events.emit(
                    "VOICE_V2_VRAM_TO_REASONING_FAILED",
                    error=f"{type(exc).__name__}: {exc}",
                )

        hybrid = hybrid_brain.ask(user_text)
        elapsed = round((monotonic() - command_started) * 1000)
        if settings.persistent_context_enabled:
            persistent_context.record(user_text, hybrid.text, hybrid.route)
        cognition.observe_interaction(user_text, hybrid.text, hybrid.route)
        try:
            self_engine.observe_outcome(
                owner_text=user_text,
                assistant_text=hybrid.text,
                route=hybrid.route,
                success=bool(str(hybrid.text or "").strip()),
            )
        except Exception as exc:
            events.emit(
                "SYNTHETIC_SELF_OUTCOME_OBSERVE_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )
        if hybrid.route.startswith("RESEARCH"):
            performance.record_request(
                elapsed_ms=elapsed,
                route=hybrid.route,
            )
        return (hybrid.text, hybrid.route, elapsed, hybrid)

    def handle_voice_command(source: str = "manual"):
        with command_lock:
            wake = wake_holder["service"]
            if source != "wake" and wake is not None:
                wake.suspend()
            if source != "wake" and silence_latch.active():
                silence_latch.release(source="explicit_listen")

            try:
                speech.stop(clear_queue=True)
                print("\nJARVIS > A ouvir... fala normalmente.")

                capture = microphone.capture_phrase()
                if not capture.get("ok"):
                    print("JARVIS >", json.dumps(capture, ensure_ascii=False, indent=2))
                    return

                wav_path = capture.get("wav_path")
                try:
                    voiceid_ms = 0
                    verification = None
                    if speaker.config.enabled and speaker.enrolled():
                        voiceid_started = monotonic()
                        try:
                            verification = speaker.verify(
                                wav_path,
                                duration_seconds=capture.get("duration_seconds"),
                            )
                        except Exception as exc:
                            verification = {
                                "ok": False,
                                "accepted": False,
                                "error": type(exc).__name__,
                                "message": str(exc),
                            }
                        voiceid_ms = round((monotonic() - voiceid_started) * 1000)
                        mode = str(settings.speaker_enforcement_mode).lower().strip()
                        if mode == "enforce":
                            if not verification.get("ok"):
                                print("JARVIS >", json.dumps(verification, ensure_ascii=False, indent=2))
                                return
                            if not verification.get("accepted"):
                                print(
                                    "JARVIS > Comando ignorado: voz não autorizada "
                                    f"(score={verification.get('score')}, "
                                    f"threshold={verification.get('threshold')})."
                                )
                                return
                        else:
                            events.emit(
                                "SPEAKER_OBSERVE",
                                accepted=verification.get("accepted"),
                                score=verification.get("score"),
                                threshold=verification.get("threshold"),
                            )

                    result = microphone.transcribe_command_file(wav_path)
                    if not result.get("ok"):
                        print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                        return

                    transcript = result["text"]
                    events.emit(
                        "VOICE_HEARD",
                        text=transcript,
                        raw_text=result.get("raw_text") or transcript,
                        source=source,
                        device=capture.get("device"),
                    )
                    if is_silence_command(transcript):
                        speech.stop(clear_queue=True)
                        silence_latch.latch(reason="owner_interrupt", source="voice_command")
                        return

                    print(f"\n{current_address()} > {transcript}")
                    if debug_terminal["enabled"]:
                        print(
                            f"  [STT   ] {result.get('backend')} | "
                            f"{capture.get('duration_seconds')}s | "
                            f"{result.get('elapsed_ms')}ms"
                        )

                    request_generation = silence_latch.generation()
                    answer, route, command_ms, hybrid = process_request(transcript, source="manual_voice")
                    if not silence_latch.output_allowed(request_generation):
                        silence_latch.mark_suppressed_response("response")
                        return
                    print(f"\nJARVIS > {answer}\n")
                    cloud_cost = (
                        f" cloud~${hybrid.cloud_estimated_usd:.6f}"
                        if hybrid and hybrid.route.startswith("CLOUD")
                        else ""
                    )
                    if debug_terminal["enabled"]:
                        print(
                            f"  [PERF  ] voiceid={voiceid_ms}ms "
                            f"stt={result.get('elapsed_ms')}ms "
                            f"command={command_ms}ms route={route}{cloud_cost}"
                        )
                    events.emit("LLM_RESPONSE_READY", chars=len(answer), route=route, source="manual_voice")
                    speech.say(answer)
                finally:
                    microphone.cleanup_capture(wav_path)
            finally:
                if source != "wake" and wake is not None:
                    wake.resume()

    def _listen_after_wake_only() -> None:
        """After a wake-only utterance, wait for the acknowledgement TTS and
        then capture the OWNER's next phrase as the command.

        This runs outside the Voice v2 stream thread so the callback can return,
        the single-stream wake engine can re-arm cleanly, and the ordinary
        microphone capture can suspend the wake stream before opening WASAPI.
        """
        try:
            deadline = monotonic() + 8.0
            while monotonic() < deadline:
                status = speech.status()
                if not bool(status.get("speaking")) and int(status.get("queued") or 0) == 0:
                    break
                sleep(0.05)
            # Let the configured TTS tail/speaker echo clear before opening the
            # command capture. This is short enough to still feel conversational.
            sleep(0.10)
            if not silence_latch.active():
                handle_voice_command(source="wake_followup")
        finally:
            wake_followup_state["pending"] = False

    def on_wake(inline_command: str | None = None):
        if debug_terminal["enabled"]:
            print("\n  [WAKE  ] JARVIS confirmado.")

        was_silent = silence_latch.active()
        if was_silent:
            silence_latch.release(source="verified_wake")

        if not inline_command:
            # A wake word by itself is a valid conversational turn. Acknowledge
            # it once, then automatically listen for the next phrase instead of
            # forcing the OWNER to repeat "Jarvis" with the command inline.
            if wake_followup_state["pending"]:
                events.emit("WAKE_ONLY_DUPLICATE_SUPPRESSED")
                return
            wake_followup_state["pending"] = True
            print("JARVIS > Sim, Senhor?")
            speech.say("Sim, Senhor?")
            events.emit("WAKE_ONLY_PHRASE", followup_listening=True)
            Thread(
                target=_listen_after_wake_only,
                name="jarvis-wake-followup",
                daemon=True,
            ).start()
            return

        with command_lock:
            transcript = inline_command.strip()
            events.emit("VOICE_HEARD", text=transcript, raw_text=transcript, source="wake")
            if is_silence_command(transcript):
                speech.stop(clear_queue=True)
                silence_latch.latch(reason="owner_interrupt", source="wake_command")
                return

            print(f"\n{current_address()} > {transcript}")
            request_generation = silence_latch.generation()
            answer, route, command_ms, hybrid = process_request(transcript, source="wake")
            if not silence_latch.output_allowed(request_generation):
                silence_latch.mark_suppressed_response("response")
                return
            print(f"\nJARVIS > {answer}\n")
            cloud_cost = (
                f" cloud~${hybrid.cloud_estimated_usd:.6f}"
                if hybrid and hybrid.route.startswith("CLOUD")
                else ""
            )
            if debug_terminal["enabled"]:
                print(
                    f"  [PERF  ] wake-command command={command_ms}ms "
                    f"route={route}{cloud_cost}"
                )
            events.emit("LLM_RESPONSE_READY", chars=len(answer), route=route, source="wake")
            speech.say(answer)

    def on_interrupt_probe_start() -> bool:
        return speech.pause_for_bargein()

    def on_interrupt_probe_end(
        confirmed: bool,
    ) -> None:
        if not confirmed:
            speech.resume_after_bargein()

    def on_interrupt() -> None:
        speech.stop(clear_queue=True)
        silence_latch.latch(reason="owner_interrupt", source="barge_in")
        events.emit("VOICE_INTERRUPT_APPLIED", phrase="Cala-te", silence_latched=True)

    legacy_wake = WakeWordService(
        events,
        WakeWordConfig(
            enabled=settings.wake_enabled,
            auto_start=settings.wake_auto_start,
            keyword=settings.wake_keyword,
            calibration_seconds=settings.wake_calibration_seconds,
            threshold_multiplier=settings.wake_threshold_multiplier,
            threshold_floor=settings.wake_threshold_floor,
            threshold_ceiling=settings.wake_threshold_ceiling,
            pre_roll_seconds=settings.wake_pre_roll_seconds,
            block_seconds=settings.wake_block_seconds,
            no_signal_rms=settings.wake_no_signal_rms,
            speech_confirm_blocks=settings.wake_speech_confirm_blocks,
            preferred_device_index=settings.mic_device,
            preferred_device_name=settings.mic_preferred_device_name,
            preferred_handsfree=settings.mic_preferred_handsfree,
            preferred_samplerate=settings.mic_preferred_samplerate,
            prefer_webcam_audio=settings.av_webcam_primary_enabled,
            webcam_name_hint=settings.av_webcam_name_hint,
            tts_tail_seconds=settings.wake_tts_tail_seconds,
            rearm_seconds=settings.wake_rearm_seconds,
            enrollment_samples=settings.wake_enrollment_samples,
            template_path=settings.wake_template_path,
            interrupt_template_path=settings.interrupt_template_path,
            interrupt_enrollment_samples=settings.interrupt_enrollment_samples,
            interrupt_match_floor=settings.interrupt_match_floor,
            feature_sample_rate=settings.wake_feature_sample_rate,
            feature_frame_ms=settings.wake_feature_frame_ms,
            feature_hop_ms=settings.wake_feature_hop_ms,
            feature_bands=settings.wake_feature_bands,
            probe_min_seconds=settings.wake_probe_min_seconds,
            probe_max_seconds=settings.wake_probe_max_seconds,
            wake_match_floor=settings.wake_match_floor,
            wake_match_margin=settings.wake_match_margin,
            wake_start_slack_seconds=settings.wake_start_slack_seconds,
            candidate_whisper_confirm=settings.wake_candidate_whisper_confirm,
            candidate_reject_cooldown_seconds=settings.wake_candidate_reject_cooldown_seconds,
            candidate_window_seconds=settings.wake_candidate_window_seconds,
            candidate_tail_seconds=settings.wake_candidate_tail_seconds,
            candidate_min_avg_logprob=settings.wake_candidate_min_avg_logprob,
            candidate_max_no_speech_prob=settings.wake_candidate_max_no_speech_prob,
            candidate_max_words=settings.wake_candidate_max_words,
            command_start_timeout_seconds=settings.wake_command_start_timeout_seconds,
            command_silence_seconds=settings.wake_command_silence_seconds,
            command_max_seconds=settings.wake_command_max_seconds,
            command_min_seconds=settings.wake_command_min_seconds,
            command_preroll_seconds=settings.wake_command_preroll_seconds,
            command_threshold_ratio=settings.wake_command_threshold_ratio,
        ),
        on_wake=on_wake,
        on_interrupt=on_interrupt,
        on_interrupt_probe_start=on_interrupt_probe_start,
        on_interrupt_probe_end=on_interrupt_probe_end,
        transcribe_callback=microphone.transcribe_command_file,
        wake_transcribe_callback=microphone.transcribe_wake_file,
        cleanup_callback=microphone.cleanup_capture,
    )
    # Voice v2 is independent of legacy device probing. Legacy objects remain
    # available only for an explicit compatibility selection (/backend legacy).
    def voice_v2_prepare_stt():
        if not bool(getattr(settings, "voice_v2_vram_handoff_enabled", True)):
            return {"ok": True, "enabled": False, "released_count": 0}

        # 0.26.7: do not evict Qwen for CPU Faster Whisper. The previous v2
        # handoff unloaded the 8B local model before every voice transcription,
        # even after CUDA had already fallen back to CPU. That forced a multi-
        # second Qwen reload on the very next conversational turn.
        stt_state = v2_microphone.stt_residency_status()
        preference = str(stt_state.get("device_preference") or "").lower().strip()
        backend = str(stt_state.get("backend") or "").lower().strip()
        if preference == "cpu" or backend.startswith("cpu/"):
            return {
                "ok": True,
                "enabled": True,
                "released_count": 0,
                "reason": "stt_cpu_keeps_qwen_resident",
            }

        residency = brain.residency_status()
        if not residency.get("running_configured"):
            return {"ok": True, "enabled": True, "released_count": 0}
        return brain.release_all_models(
            reason="voice_v2_stt_handoff",
            include_configured=True,
        )

    voice_v2 = VoiceEngineV2(
        events,
        voice_v2_config_from_settings(settings),
        on_wake=on_wake,
        on_interrupt=on_interrupt,
        transcribe_callback=v2_microphone.transcribe_command_file,
        wake_transcribe_callback=v2_microphone.transcribe_wake_file,
        cleanup_callback=v2_microphone.cleanup_capture,
        release_stt_callback=v2_microphone.release_stt,
        before_stt_callback=voice_v2_prepare_stt,
    )

    requested_voice_backend = str(settings.voice_input_backend or "v2").strip().lower()
    voice_engine_state = {
        "requested": requested_voice_backend,
        "effective": "v2",
        "fallback_reason": None,
    }
    wake = voice_v2
    microphone = v2_microphone
    if requested_voice_backend == "legacy":
        wake = legacy_wake
        microphone = legacy_microphone
        voice_engine_state["effective"] = "legacy"
        events.emit("VOICE_LEGACY_EXPLICIT_COMPATIBILITY_MODE")
    else:
        if requested_voice_backend not in {"v2", "auto"}:
            voice_engine_state["fallback_reason"] = "INVALID_BACKEND_SETTING_USING_V2"
        v2_doctor = voice_v2.doctor()
        if not v2_doctor.get("ok"):
            voice_engine_state["fallback_reason"] = (
                v2_doctor.get("error") or v2_doctor.get("message") or "VOICE_V2_NOT_READY"
            )
            # 0.27.6 deliberately does not silently fall back to the old wake/STT
            # pipeline. A broken v2 health check must remain visible and fail
            # acceptance rather than changing architecture behind the user's back.
            events.emit(
                "VOICE_V2_UNAVAILABLE_NO_LEGACY_FALLBACK",
                requested=requested_voice_backend,
                reason=voice_engine_state["fallback_reason"],
            )

    wake_holder["service"] = wake

    listening_watchdog = ListeningWatchdogService(
        events,
        wake,
        speech,
        enabled=settings.listening_watchdog_enabled,
        armed=(settings.wake_enabled and settings.wake_auto_start),
        interval_seconds=settings.listening_watchdog_interval_seconds,
        stream_grace_seconds=settings.listening_watchdog_stream_grace_seconds,
        recovery_cooldown_seconds=(
            settings.listening_watchdog_recovery_cooldown_seconds
        ),
    )

    def wake_tts_guard(event: Event) -> None:
        """
        Prevent self-trigger while keeping the selected capture engine alive.

        Voice v2 owns one WASAPI stream and keeps the local acoustic owner
        interrupt profile available on that same stream while normal wake is
        suppressed. Legacy mode keeps its historical behavior.
        """
        if event.name == "SPEECH_STARTED":
            wake.suppress_audio(True, reason="tts")
            events.emit("WAKE_TTS_SUPPRESSED", stream_kept_open=True)
        elif event.name == "SPEECH_FINISHED":
            wake.suppress_audio(
                False,
                reason="tts",
                tail_seconds=settings.wake_tts_tail_seconds,
            )
            events.emit("WAKE_TTS_RESUMED", stream_kept_open=True)

    # Functional wake/TTS guard is always active and never depends on logging.
    events.subscribe(wake_tts_guard)

    def terminal_event_printer(event: Event) -> None:
        if debug_terminal["enabled"]:
            event_printer(event)

    # Always subscribe the gate so /debug on/off works without restart.
    # EventBus itself keeps writing events to logs/events.jsonl while quiet.
    events.subscribe(terminal_event_printer)

    telemetry.start()

    def on_sustained_pressure(
        pressure: dict,
    ) -> None:
        if settings.performance_release_llm_on_pressure:
            result = brain.release_model(
                reason="sustained_resource_pressure"
            )
            events.emit(
                "PERFORMANCE_LLM_RELEASE_RESULT",
                pressure=pressure,
                result=result,
            )

    performance.start(
        on_sustained_pressure=on_sustained_pressure
    )
    speech.start()

    def warm_services():
        events.emit("WARMUP_STARTED")
        sleep(
            max(
                0.0,
                float(settings.performance_warmup_delay_seconds),
            )
        )

        if speaker.enrolled():
            speaker.ensure_ready()

        # Voice v2 deliberately keeps the heavier STT model cold by default.
        # openWakeWord+Silero remain resident on CPU; Faster Whisper is loaded
        # only after a verified wake and released again after idle.
        if voice_engine_state.get("effective") != "v2" or settings.voice_v2_preload_stt:
            microphone.preload_stt()
        else:
            events.emit("STT_WARMUP_DEFERRED_FOR_VOICE_V2")

        if performance.should_warm_llm():
            brain.warmup()
        else:
            events.emit(
                "LLM_WARMUP_DEFERRED",
                pressure=performance.pressure(),
            )

        events.emit("WARMUP_FINISHED")

    if settings.background_warmup:
        Thread(
            target=warm_services,
            name="jarvis-warmup",
            daemon=True,
        ).start()

    if (
        settings.wake_enabled
        and settings.wake_auto_start
        and wake.configured()
        and wake.enrolled()
    ):
        wake.start()

    listening_watchdog.start()

    print(BANNER_TEMPLATE.format(version=__version__))
    print(f"Assistant : {settings.assistant_name}")
    print(f"Model     : {settings.model}")
    print(f"Tools     : {len(tools.names)}")
    print(f"Skills    : {len(skills.skills) if settings.skills_enabled else 0} loaded | modular runtime")
    print(f"Apps      : {len(apps.list_apps())} allowed")
    print(
        f"Telemetry : CPU/RAM {settings.telemetry_interval_seconds}s | "
        f"GPU {settings.performance_gpu_sample_interval_seconds}s"
    )
    print(
        "Desktop   : "
        + ("READY" if desktop_state.get("bridge_online") else "BRIDGE STARTING/OFFLINE")
        + " | Wallpaper Engine "
        + ("ONLINE" if desktop_state.get("wallpaper_engine_running") else "NOT DETECTED")
    )
    print(f"Voice     : {'ON' if settings.speech_enabled else 'OFF'} | {settings.speech_voice} | {settings.speech_persona_profile}")
    print(f"Persona   : FEMININE | adaptive companion={'ON' if settings.companion_enabled else 'OFF'} | flirt={'ON' if settings.companion_flirt_enabled else 'OFF'}")
    print(f"Language  : pt-PT refinement=ON | personal learning={'ON' if settings.personal_learning_enabled else 'OFF'}")
    selected_stt_model = (
        settings.voice_v2_stt_model
        if voice_engine_state.get("effective") == "v2"
        else settings.stt_model
    )
    selected_stt_device = (
        settings.voice_v2_stt_device
        if voice_engine_state.get("effective") == "v2"
        else settings.stt_device
    )
    print(
        f"Listening : {voice_engine_state.get('effective', 'legacy').upper()} | "
        f"Whisper {selected_stt_model} ({selected_stt_device})"
    )
    if voice_engine_state.get("fallback_reason"):
        print(f"Voice v2  : FALLBACK -> legacy | {voice_engine_state['fallback_reason']}")
    elif voice_engine_state.get("effective") == "v2":
        print("Voice v2  : WASAPI + openWakeWord + Silero VAD | READY")
    try:
        startup_mic = microphone.status().get("device") or {}
        print(
            "A/V       : webcam-primary="
            + ("ON" if settings.av_webcam_primary_enabled else "OFF")
            + f" | mic={startup_mic.get('name') or 'AUTO'}"
            + f" | camera={settings.vision_camera_index}"
        )
    except Exception:
        print(
            "A/V       : webcam-primary="
            + ("ON" if settings.av_webcam_primary_enabled else "OFF")
            + f" | camera={settings.vision_camera_index}"
        )
    print(
        "ListenGuard: "
        + ("ON" if settings.listening_watchdog_enabled else "OFF")
        + " | auto-recovery="
        + ("ON" if settings.listening_watchdog_enabled else "OFF")
    )
    print(
        f"Speed     : Governor={performance.mode.upper()} | "
        f"FAST PATH + selective tools | STT beam={settings.stt_beam_size}"
    )
    print(
        f"AI VRAM   : native={getattr(settings, 'local_llm_backend', 'native_llama')} | "
        f"vision={getattr(settings, 'vision_keep_alive', '2m')} | "
        f"shutdown-release={'ON' if getattr(settings, 'ollama_release_on_shutdown', True) else 'OFF'}"
    )
    print(f"Voice Lock: {'ON' if speaker.config.enabled else 'OFF'} | {'ENROLLED' if speaker.enrolled() else 'NOT ENROLLED'} | mode={settings.speaker_enforcement_mode}" + (" | AUTO-DISABLED" if speaker_lock_health.get('disabled') else ""))
    wake_label = (
        "OPENWAKEWORD/READY"
        if voice_engine_state.get("effective") == "v2" and wake.enrolled()
        else "ACOUSTIC/READY"
        if wake.enrolled()
        else "NOT READY"
    )
    print(f"Wake Word : {settings.wake_keyword.upper()} | {wake_label}")
    print("Interrupt : CALA-TE | " + ("READY" if wake.interrupt_enrolled() else "NEEDS /interrupt enroll"))
    print(f"Silence   : {'READY' if settings.silence_latch_enabled else 'OFF'} | wake-release=ON")
    print(f"Activity  : {'ON' if settings.activity_trace_enabled else 'OFF'} | live={'ON' if settings.activity_trace_live else 'OFF'} | /activity on")
    print(f"Brain     : LOCAL PRIMARY | {settings.model}")
    print("External AI: HARD BLOCKED | Web research -> local Qwen synthesis")
    print(f"Research  : DIRECT WEB -> LOCAL SYNTHESIS | {'READY' if research_engine.available() else 'PRIVACY/OFF'}")
    print("Authority : OWNER/STRICT | autonomous external actions require permission")
    kali_state = kali_bridge.status()
    print(f"Kali LAB  : {'READY' if kali_state.get('configured') and kali_state.get('ready_scope') else 'NOT CONFIGURED/NOT READY'} | fixed profiles only")
    ok, msg = brain.health_check()
    print(f"Native LLM: {'ONLINE' if ok else 'ATTENTION'}")
    print(f"            {msg}")
    briefing = build_startup_briefing()
    briefing_text = briefing.get("text")
    if briefing_text:
        print(f"\nJARVIS > {briefing_text}\n")
        speech.say(briefing_text)
    print("\nTerminal silencioso ativo. /debug on para diagnóstico. /help para ajuda.\n")

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
        if cognition.state().get("proactive_speech_enabled", True):
            speech.say(final_message)

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
        if settings.speech_enabled:
            speech.say(message)

    companion_service = CompanionPresenceService(
        brain.plan_companion_initiative,
        companion_output_callback,
        state_path=settings.companion_state_path,
        enabled=settings.companion_enabled,
        flirt_enabled=settings.companion_flirt_enabled,
        flirt_intensity=settings.companion_flirt_intensity,
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
        wake=wake,
        planner_provider=lambda: skill_context.services.get("task_planner"),
        reflection_provider=brain.plan_idle_reflection,
    )

    def reminder_callback(message: str) -> None:
        print(f"\nJARVIS > {message}\n")
        if silence_latch.active():
            silence_latch.mark_suppressed_response("proactive")
            return
        speech.say(message)

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


    def queue_external_learning_retry(
        *,
        payload: dict,
        topic: str,
        error: str | None,
    ) -> None:
        failure = str(error or "").strip() or "RESEARCH_FAILED"
        reason_map = {
            "RESEARCH_UNAVAILABLE": "direct_research_unavailable_before_learning",
            "SEARCH_FAILED": "web_search_failed_before_learning",
            "SEARCH_RESULTS_IRRELEVANT": "web_search_irrelevant_before_learning",
            "FETCH_FAILED": "web_fetch_failed_before_learning",
            "FETCHED_SOURCES_IRRELEVANT": "web_sources_irrelevant_before_learning",
            "LOCAL_SYNTHESIS_FAILED": "local_synthesis_failed_before_learning",
            "LOCAL_SYNTHESIS_RELEVANCE_REJECTED": "local_synthesis_relevance_rejected_before_learning",
            "LEARNING_TOPIC_MISMATCH": "learning_store_topic_mismatch",
            "DIRECT_URL_FETCH_FAILED": "direct_url_fetch_failed_before_learning",
            "DIRECT_URL_TOPIC_MISMATCH": "direct_url_topic_mismatch_before_learning",
            "DIRECT_URL_BLOCKED": "direct_url_blocked_before_learning",
        }
        reason = reason_map.get(failure, "external_research_failed_before_learning")

        retry = autonomy.request(
            capability="external_learning",
            payload=payload,
            reason=reason,
            description=(
                "repetir a mesma sessão de aprendizagem externa sobre "
                f"{topic[:220]} depois de resolver a falha de pesquisa local/web"
            ),
            action=(
                "external_learning_resume_query"
                if str(payload.get("original_query") or "").strip()
                else "external_learning"
            ),
            source="local_research_retry",
        )
        if retry.get("pending"):
            if failure in {"SEARCH_RESULTS_IRRELEVANT", "FETCHED_SOURCES_IRRELEVANT"}:
                guidance = "Depois de existirem fontes públicas relevantes para o tópico"
            elif failure in {"LOCAL_SYNTHESIS_RELEVANCE_REJECTED", "LEARNING_TOPIC_MISMATCH"}:
                guidance = "Depois de obter uma síntese local que corresponda ao tópico autorizado"
            elif failure in {"RESEARCH_UNAVAILABLE", "SEARCH_FAILED", "FETCH_FAILED", "DIRECT_URL_FETCH_FAILED"}:
                guidance = "Depois de a pesquisa direta/local voltar a estar disponível"
            elif failure in {"DIRECT_URL_TOPIC_MISMATCH", "DIRECT_URL_BLOCKED"}:
                guidance = "Depois de o URL autorizado passar a validação segura e corresponder ao tópico"
            else:
                guidance = "Depois de resolver a falha de síntese local"
            print(
                "JARVIS > A aprendizagem não foi concluída. "
                f"{guidance}, esta ação exata ficou novamente pendente: "
                f"/authorize {retry.get('token')}."
            )

    def execute_direct_external_learning(
        intent: dict,
        *,
        source_text: str,
    ) -> None:
        topic = str(
            intent.get("topic")
            or ""
        ).strip()
        query = str(
            intent.get("query")
            or ""
        ).strip()
        source_url = str(
            intent.get("source_url")
            or ""
        ).strip()

        if not topic or not query:
            print(
                "JARVIS > Não consegui determinar o âmbito exato "
                "da aprendizagem autorizada. Não vou pesquisar."
            )
            return

        if not research_engine.available():
            print(
                "JARVIS > Recebi a sua autorização, mas a pesquisa direta na Internet "
                "está indisponível ou bloqueada pelo modo de privacidade. Não executei a pesquisa."
            )
            return

        payload = {
            "topic": topic,
            "query": query,
            "deep": bool(
                intent.get("deep", True)
            ),
            "scope": "single_research_session",
            "source_url": source_url or None,
        }
        using_standing = bool(intent.get("standing_public_web_read_only")) or autonomy.has_standing_public_web_learning()
        if using_standing:
            if not autonomy.has_standing_public_web_learning():
                print(
                    "JARVIS > A permissão persistente de pesquisa pública não está ativa. "
                    "Não iniciei a pesquisa externa."
                )
                return
            authorization = {"ok": True, "authorized": True, "standing": True}
        else:
            authorization = autonomy.record_direct_authorization(
                capability="external_learning",
                payload=payload,
                description=(
                    "pesquisar e aprender externamente sobre "
                    f"{topic[:220]}"
                ),
                source_text=source_text,
            )
            if not authorization.get("ok"):
                print(
                    "JARVIS > Não consegui registar a autorização. "
                    "A pesquisa não foi executada."
                )
                return

            if bool(intent.get("standing_public_web_read_only_grant")):
                standing_result = autonomy.grant_standing_public_web_learning(source_text)
                if standing_result.get("ok"):
                    events.emit(
                        "OWNER_STANDING_PUBLIC_WEB_LEARNING_GRANTED",
                        scope="public_web_read_only_learning",
                    )

        if source_url:
            print(
                ("JARVIS > Permissão persistente de pesquisa pública ativa. " if using_standing else "JARVIS > Autorização direta reconhecida. ")
                + f"Vou estudar o URL indicado sobre {topic} numa sessão limitada e segura. "
                + (
                    "A permissão persistente mantém-se ativa; esta execução limita-se ao conteúdo público do pedido atual. "
                    if using_standing
                    else "Esta autorização direta vale apenas para esta execução. "
                )
                + "Não executo downloads arbitrários, comandos, ações autenticadas ou acesso a alvos locais/privados."
            )
            result = research_engine.research_url(
                source_url,
                query=query,
                topic=topic,
                deep=bool(intent.get("deep", True)),
            )
        else:
            print(
                ("JARVIS > Permissão persistente de pesquisa pública ativa. " if using_standing else "JARVIS > Autorização direta reconhecida. ")
                + f"Vou fazer uma sessão de pesquisa sobre {topic}. "
                + (
                    "A permissão persistente mantém-se ativa; a execução atual é apenas leitura pública."
                    if using_standing
                    else "Esta autorização direta vale apenas para esta execução de leitura pública."
                )
            )
            result = research_engine.research(
                query,
                topic=topic,
                deep=bool(intent.get("deep", True)),
                search_query=topic,
            )
        if not result.ok:
            print(
                f"JARVIS > {result.text}"
            )
            if using_standing:
                reason_code = str(result.error or "UNKNOWN")
                print(
                    "JARVIS > A permissão persistente continua válida. "
                    f"Esta execução terminou sem aprendizagem (motivo: {reason_code}) e não criou uma nova autorização pendente."
                )
            else:
                queue_external_learning_retry(
                    payload=payload,
                    topic=topic,
                    error=result.error,
                )
            return

        stored = authorized_learning().add(
            topic=topic,
            query=query,
            summary=result.text,
            model=result.model,
            authorization_token=("STANDING" if using_standing else "DIRECT"),
            sources=result.sources or [],
            source_type="authorized_direct_web_local_model_summary_v2",
        )
        if not stored.get("ok") or not stored.get("stored"):
            print(
                "JARVIS > A síntese obtida não passou a validação final do tópico. "
                "Não guardei esta aprendizagem."
            )
            if using_standing:
                print(
                    "JARVIS > A permissão persistente continua válida; esta falha de validação "
                    "não cria uma nova autorização pendente."
                )
            else:
                queue_external_learning_retry(
                    payload=payload,
                    topic=topic,
                    error=str(stored.get("error") or "LEARNING_STORE_REJECTED"),
                )
            return
        events.emit(
            "DIRECT_AUTHORIZED_EXTERNAL_LEARNING_STORED",
            topic=topic,
            stored=stored,
        )

        learning_note = (
            f"Aprendizagem sobre {topic} guardada localmente. "
            + (
                "A permissão persistente de pesquisa pública continua ativa."
                if using_standing
                else "A autorização desta sessão foi consumida."
            )
        )
        final_answer = str(result.text or "").strip()
        if final_answer:
            print(f"\nJARVIS > {final_answer}\n")
            print(f"JARVIS > {learning_note}")
            speech.say(final_answer)
        else:
            print(f"\nJARVIS > {learning_note}\n")
            speech.say(learning_note)

    def request_external_learning_for_goal(
        intent: dict,
        *,
        source_text: str,
    ) -> None:
        """Register a local learning objective; never infer Web authority.

        A sentence such as "quero que aprendas comportamento humano" says
        what JARVIS should learn.  It is not a Web instruction, and an old
        standing Web permission must not turn it into one.
        """
        topic = str(intent.get("topic") or "").strip()
        if not topic:
            return

        recorded = cognition.record_jarvis_learning_goal(
            topic,
            source_text=source_text,
        )
        if not recorded.get("ok"):
            message = (
                "Senhor, percebi que isso é um objetivo de aprendizagem meu, "
                "mas não consegui registá-lo localmente. Não usei a Internet."
            )
        else:
            learning_followup_state["topic"] = topic
            learning_followup_state["created_at"] = monotonic()
            message = (
                f"Senhor, registei {topic} como um objetivo de aprendizagem meu. "
                "Não usei a Internet e uma permissão Web anterior não autoriza "
                "pesquisa automática neste pedido. Posso usar o conhecimento local "
                "que já tenho; só farei pesquisa pública quando me pedir explicitamente "
                "para pesquisar, estudar na Web/Internet ou indicar um URL."
            )
        events.emit(
            "LOCAL_LEARNING_GOAL_RECORDED",
            topic=topic[:220],
            stored=bool(recorded.get("stored")),
            web_used=False,
        )
        print(f"JARVIS > {message}")
        speech.say(message)

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
                answer, route, command_ms, hybrid = process_request(
                    query
                )
                print(
                    f"\nJARVIS > {answer}\n"
                )
                speech.say(answer)
            return

        if action in {"external_learning", "external_learning_resume_query"}:
            # Consume the exact one-shot grant before making the external call.
            gate = autonomy.request(
                capability="external_learning",
                payload=payload,
                reason="owner_authorized_learning",
                description=(
                    "executar a pesquisa externa previamente autorizada"
                ),
                action="external_learning",
                source="authorization_executor",
            )
            if not gate.get("allowed"):
                print(
                    "JARVIS > Não consegui consumir a autorização exata. "
                    "A pesquisa não será feita."
                )
                return

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
                return

            if source_url:
                result = research_engine.research_url(
                    source_url,
                    query=query,
                    topic=topic,
                    deep=bool(payload.get("deep")),
                )
            else:
                result = research_engine.research(
                    query,
                    topic=topic,
                    deep=bool(payload.get("deep")),
                    search_query=topic,
                )
            if not result.ok:
                print(
                    f"JARVIS > {result.text}"
                )
                queue_external_learning_retry(
                    payload=payload,
                    topic=topic,
                    error=result.error,
                )
                return

            stored = authorized_learning().add(
                topic=topic,
                query=query,
                summary=result.text,
                model=result.model,
                authorization_token=str(
                    grant.get("token")
                    or token
                ),
                sources=result.sources or [],
                source_type="authorized_direct_web_local_model_summary_v2",
            )
            if not stored.get("ok") or not stored.get("stored"):
                print(
                    "JARVIS > A síntese obtida não passou a validação final do tópico. "
                    "Não guardei esta aprendizagem."
                )
                queue_external_learning_retry(
                    payload=payload,
                    topic=topic,
                    error=str(stored.get("error") or "LEARNING_STORE_REJECTED"),
                )
                return
            message = (
                "Aprendizagem externa autorizada concluída e guardada "
                f"localmente sobre: {topic}. "
                "O registo é identificado como síntese produzida pelo Qwen local a partir de fontes web públicas, "
                "não como prova primária."
            )
            print(
                f"\nJARVIS > {message}\n"
            )
            speech.say(message)
            events.emit(
                "AUTHORIZED_EXTERNAL_LEARNING_STORED",
                topic=topic,
                stored=stored,
            )

            if action == "external_learning_resume_query":
                original_query = str(payload.get("original_query") or "").strip()
                if original_query:
                    print(
                        "JARVIS > Estudo local atualizado. Vou tentar novamente o pedido original "
                        "usando o conhecimento que acabei de validar."
                    )
                    with command_lock:
                        answer, route, command_ms, hybrid = process_request(original_query)
                        print(f"\nJARVIS > {answer}\n")
                        speech.say(answer)
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

            # Accept both "/wake on" and "\\wake on".
            if text.startswith("\\"):
                text = "/" + text[1:]

            lower = text.lower()

            # Resolve explicit OWNER terminal wake before specialized intent
            # parsers.  In 0.26.2 this happened only near the generic model
            # route, so a valid authorization such as
            # "Jarvis, tens a minha autorização ..." could be parsed against
            # the unstripped wake prefix or bypass the local authority path.
            # Slash commands remain usable while silent without implicitly
            # releasing the latch.
            if (
                silence_latch.active()
                and not is_silence_command(text)
                and not lower.startswith("/")
            ):
                wake_match = re.match(
                    r"^\s*jarvis(?=$|[\s,;:!?.-])[\s,;:!?.-]*(.*)$",
                    text,
                    flags=re.IGNORECASE,
                )
                if wake_match is not None:
                    silence_latch.release(source="explicit_terminal_wake")
                    text = str(wake_match.group(1) or "").strip()
                    if not text:
                        print("JARVIS > Diga, Senhor.")
                        continue
                    lower = text.lower()
                else:
                    silence_latch.release(source="explicit_terminal_input")

            if local_pdf_library_learning_requested(text):
                result = read_tool("sync_book_library", {"force": False})
                message = format_book_library_sync(result)
                print(f"JARVIS >\n{message}")
                speech.say(message)
                continue

            direct_learning = parse_direct_external_learning_order(
                text
            )
            if (
                direct_learning is None
                and learning_followup_state.get("topic")
                and monotonic() - float(learning_followup_state.get("created_at") or 0.0) <= 300.0
            ):
                url_match = re.search(r"(?i)https?://[^\s<>\"']+", text)
                url_only = bool(url_match) and not re.search(r"(?i)\b(?:aprende|estuda|pesquisa|consulta|visita|investiga)\b", text)
                if url_only:
                    source_url = url_match.group(0).rstrip(").,;!?]}")
                    topic = str(learning_followup_state.get("topic") or "").strip()
                    direct_learning = {
                        "kind": "direct_external_learning",
                        "topic": topic,
                        "query": f"Estuda a fonte indicada para o objetivo de aprendizagem sobre {topic}.",
                        "deep": True,
                        "scope": "single_research_session",
                        "direct_user_authority": True,
                        "source_url": source_url,
                        "followup_bound": True,
                    }
            if direct_learning is not None:
                execute_direct_external_learning(
                    direct_learning,
                    source_text=text,
                )
                if direct_learning.get("followup_bound"):
                    learning_followup_state["topic"] = ""
                    learning_followup_state["created_at"] = 0.0
                continue

            learning_goal = parse_learning_goal(
                text
            )
            if learning_goal is not None:
                request_external_learning_for_goal(
                    learning_goal,
                    source_text=text,
                )
                continue

            if is_silence_command(text):
                speech.stop(clear_queue=True)
                silence_latch.latch(reason="owner_interrupt", source="terminal")
                continue

            if lower == "/silence status":
                print("JARVIS >", json.dumps(silence_latch.status(), ensure_ascii=False, indent=2))
                continue
            if lower in {"/silence off", "/silence release"}:
                print("JARVIS >", json.dumps(silence_latch.release(source="owner_cli"), ensure_ascii=False, indent=2))
                continue
            if lower == "/silence on":
                speech.stop(clear_queue=True)
                print("JARVIS >", json.dumps(silence_latch.latch(reason="owner_cli", source="terminal"), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity on":
                settings.activity_trace_live = True
                Settings.update_file_values({"activity_trace_live": True})
                print("JARVIS >", json.dumps(activity_trace.set_live(True), ensure_ascii=False, indent=2))
                continue
            if lower == "/activity off":
                settings.activity_trace_live = False
                Settings.update_file_values({"activity_trace_live": False})
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
                print(help_text()); continue
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
            if lower == "/voice status":
                print(
                    "JARVIS >",
                    json.dumps(
                        {
                            "speech": speech.status(),
                            "input_engine": dict(voice_engine_state),
                            "listening": wake.status(),
                            "microphone": microphone.status(),
                            "stt_residency": microphone.stt_residency_status(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower == "/voice doctor":
                selected_doctor = wake.doctor()
                print(
                    "JARVIS >",
                    json.dumps(
                        {
                            "engine": dict(voice_engine_state),
                            "doctor": selected_doctor,
                            "stt": microphone.status(),
                            "setup_v2": ".\\setup_voice_v2.ps1",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                continue
            if lower in {"/voice benchmark", "/voice latency"}:
                benchmark = (
                    wake.benchmark()
                    if hasattr(wake, "benchmark")
                    else {
                        "ok": False,
                        "error": "BENCHMARK_NOT_SUPPORTED_BY_LEGACY_ENGINE",
                        "message": "Instala/ativa o Voice Engine v2 para benchmark do wake.",
                    }
                )
                if lower == "/voice latency":
                    benchmark = {
                        "wake": benchmark,
                        "stt": microphone.stt_residency_status(),
                        "vram_handoff_enabled": bool(getattr(settings, "voice_v2_vram_handoff_enabled", True)),
                    }
                print("JARVIS >", json.dumps(benchmark, ensure_ascii=False, indent=2))
                continue
            if lower == "/voice release":
                result = microphone.release_stt()
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/voice backend "):
                wanted = lower.split(maxsplit=2)[2].strip()
                if wanted not in {"auto", "v2", "legacy"}:
                    print("JARVIS > Backend inválido. Usa: auto, v2 ou legacy.")
                    continue
                settings.voice_input_backend = wanted
                Settings.update_file_values({"voice_input_backend": wanted})
                print(
                    "JARVIS > Backend de entrada guardado como "
                    f"{wanted}. Reinicia o JARVIS para aplicar. "
                    "Para v2 executa primeiro .\\setup_voice_v2.ps1."
                )
                continue
            if lower == "/voice test":
                speech.test_phrase()
                print("JARVIS > Teste de voz enviado para os altifalantes.")
                continue
            if lower == "/voice on":
                speech.set_enabled(True)
                print("JARVIS > Voz ativada.")
                speech.say("Voz ativada. Estou online.")
                continue
            if lower == "/voice off":
                speech.set_enabled(False)
                print("JARVIS > Voz desativada.")
                continue
            if lower == "/voice stop":
                speech.stop(clear_queue=True)
                print("JARVIS > Fala interrompida.")
                continue
            if lower == "/voice feminine":
                speech.config.edge_voice = "pt-PT-RaquelNeural"
                speech.config.rate = "-9%"
                speech.config.pitch = "-8Hz"
                speech.config.persona_profile = "velvet_feminine"
                speech.config.sapi_prefer_gender = "Female"
                settings.speech_voice = speech.config.edge_voice
                settings.speech_rate = speech.config.rate
                settings.speech_pitch = speech.config.pitch
                settings.speech_persona_profile = speech.config.persona_profile
                settings.speech_sapi_prefer_gender = speech.config.sapi_prefer_gender
                Settings.update_file_values({
                    "speech_voice": settings.speech_voice,
                    "speech_rate": settings.speech_rate,
                    "speech_pitch": settings.speech_pitch,
                    "speech_persona_profile": settings.speech_persona_profile,
                    "speech_sapi_prefer_gender": settings.speech_sapi_prefer_gender,
                })
                print("JARVIS > Perfil de voz feminina Velvet aplicado: RaquelNeural.")
                speech.say("Perfil feminino aplicado, Senhor. Assim está melhor.")
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
            if lower == "/companion flirt on":
                settings.companion_flirt_enabled = True
                companion_service.set_flirt_enabled(True)
                Settings.update_file_values({"companion_flirt_enabled": True})
                print("JARVIS > Flirt contextual ativado.")
                continue
            if lower == "/companion flirt off":
                settings.companion_flirt_enabled = False
                companion_service.set_flirt_enabled(False)
                Settings.update_file_values({"companion_flirt_enabled": False})
                print("JARVIS > Flirt contextual desativado.")
                continue
            if lower.startswith("/companion intensity "):
                raw_value = text[len("/companion intensity "):].strip().replace(",", ".")
                try:
                    value = float(raw_value)
                except ValueError:
                    print("JARVIS > Usa um valor entre 0 e 1, por exemplo: /companion intensity 0.65")
                    continue
                result = companion_service.set_intensity(value)
                if result.get("ok"):
                    settings.companion_flirt_intensity = float(result.get("flirt_intensity", value))
                    Settings.update_file_values({
                        "companion_flirt_intensity": settings.companion_flirt_intensity
                    })
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower == "/stt status":
                payload = {
                    "ok": True,
                    "language": microphone.config.language,
                    "model": microphone.config.model,
                    "device": microphone.config.stt_device,
                    "backend": microphone.status().get("model_backend"),
                    "command_beam": microphone.config.command_beam_size,
                    "retry_beam": microphone.config.command_retry_beam_size,
                    "normalize_audio": microphone.config.normalize_command_audio,
                    "target_rms": microphone.config.command_target_rms,
                    "max_gain": microphone.config.command_max_gain,
                    "wake_command_silence_seconds": wake.config.command_silence_seconds,
                    "wake_command_preroll_seconds": wake.config.command_preroll_seconds,
                    "wake_command_threshold_ratio": wake.config.command_threshold_ratio,
                }
                print("JARVIS >", json.dumps(payload, ensure_ascii=False, indent=2))
                continue
            if lower == "/stt test":
                speech.stop(clear_queue=True)
                was_running = bool(wake.status().get("running"))
                if was_running:
                    wake.suspend()
                print("JARVIS > Teste STT preparado.")
                wav_path = None
                try:
                    # 0.26.2: the previous text told the OWNER to wait for
                    # "A ouvir" but never actually printed it.  That could
                    # leave the capture listening only to room noise.
                    print("JARVIS > A ouvir... fala agora.")
                    capture = microphone.capture_phrase()
                    if not capture.get("ok"):
                        print("JARVIS >", json.dumps(capture, ensure_ascii=False, indent=2))
                    else:
                        wav_path = capture.get("wav_path")
                        result = microphone.transcribe_command_file(wav_path)
                        result["capture"] = {k: v for k, v in capture.items() if k != "wav_path"}
                        if not result.get("ok") and wav_path:
                            # Keep failed diagnostic audio instead of deleting
                            # the only evidence needed to understand the mic.
                            try:
                                diagnostic_dir = Path(settings.log_dir) / "audio_diagnostics"
                                diagnostic_dir.mkdir(parents=True, exist_ok=True)
                                source_path = Path(wav_path)
                                diagnostic_path = diagnostic_dir / source_path.name
                                diagnostic_path.write_bytes(source_path.read_bytes())
                                result["diagnostic_wav"] = str(diagnostic_path)
                                events.emit(
                                    "STT_DIAGNOSTIC_AUDIO_SAVED",
                                    path=str(diagnostic_path),
                                    reason=result.get("error") or "transcription_failed",
                                )
                            except Exception as exc:
                                result["diagnostic_save_error"] = f"{type(exc).__name__}: {exc}"
                        print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                finally:
                    microphone.cleanup_capture(wav_path)
                    if was_running:
                        wake.resume()
                continue
            if lower == "/listening status":
                combined = listening_watchdog.status()
                try:
                    combined["microphone"] = microphone.status()
                except Exception as exc:
                    combined["microphone"] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                print(
                    "JARVIS >",
                    json.dumps(combined, ensure_ascii=False, indent=2),
                )
                continue
            if lower == "/listening recover":
                result = listening_watchdog.recover(reason="owner_manual")
                print(
                    "JARVIS >",
                    json.dumps(result, ensure_ascii=False, indent=2),
                )
                continue

            if lower == "/av status":
                vision_service = skill_context.services.get("vision")
                payload = {
                    "ok": True,
                    "webcam_primary": bool(settings.av_webcam_primary_enabled),
                    "webcam_name_hint": settings.av_webcam_name_hint,
                    "microphone": microphone.status(),
                    "wake": wake.status(),
                    "vision": (
                        vision_service.status()
                        if vision_service is not None
                        else {"ok": False, "error": "VISION_SERVICE_UNAVAILABLE"}
                    ),
                }
                print("JARVIS >", json.dumps(payload, ensure_ascii=False, indent=2))
                continue
            if lower == "/av microphones":
                try:
                    rows = []
                    for dev in microphone.list_devices():
                        score = webcam_audio_score(dev.get("name", ""), settings.av_webcam_name_hint)
                        rows.append({
                            **dev,
                            "webcam_score": score,
                            "probable_webcam_mic": score >= 1200,
                        })
                    print("JARVIS >", json.dumps(rows, ensure_ascii=False, indent=2))
                except Exception as exc:
                    print(f"JARVIS > Erro ao listar entradas A/V: {type(exc).__name__}: {exc}")
                continue
            if lower == "/av probe":
                was_running = bool(wake.status().get("running"))
                if was_running:
                    wake.suspend()
                try:
                    print("JARVIS > A testar entradas de áudio. Fala normalmente durante alguns segundos.")
                    rows = microphone.probe_devices(limit=12)
                    live = [row for row in rows if row.get("ok")]
                    selected_probe = microphone.select_best_probe(rows)
                    payload = {
                        "ok": bool(live),
                        "live_inputs": len(live),
                        "selected_candidate": selected_probe,
                        "devices": rows,
                    }
                    print("JARVIS >", json.dumps(payload, ensure_ascii=False, indent=2))
                except Exception as exc:
                    print("JARVIS >", json.dumps({
                        "ok": False,
                        "error": type(exc).__name__,
                        "message": str(exc),
                    }, ensure_ascii=False, indent=2))
                finally:
                    if was_running:
                        wake.resume()
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
            if lower == "/av auto":
                result = {"ok": True, "microphone": None, "camera": None}
                try:
                    candidates = microphone._input_device_candidates()
                    was_running = bool(wake.status().get("running"))
                    if was_running:
                        wake.suspend()
                    try:
                        probes = microphone.probe_devices(limit=12)
                    finally:
                        if was_running:
                            wake.resume()
                    probe_by_index = {
                        int(row["index"]): row
                        for row in probes
                        if row.get("index") is not None
                    }
                    selected_probe = microphone.select_best_probe(probes)
                    webcam = None
                    if selected_probe is not None:
                        selected_idx = int(selected_probe["index"])
                        chosen = next(((idx, dev) for idx, dev in candidates if int(idx) == selected_idx), None)
                        if chosen is not None:
                            webcam = (chosen[0], chosen[1], selected_probe)
                    if webcam is not None:
                        idx, dev, probe = webcam
                        name = str(dev.get("name", ""))
                        microphone.config.device = int(idx)
                        microphone.config.preferred_device_index = int(idx)
                        microphone.config.prefer_webcam_audio = True
                        wake.config.preferred_device_index = int(idx)
                        if hasattr(wake.config, "preferred_device_name"):
                            wake.config.preferred_device_name = name
                        microphone.config.webcam_name_hint = name
                        wake.config.prefer_webcam_audio = True
                        wake.config.webcam_name_hint = name
                        settings.mic_device = int(idx)
                        settings.av_webcam_primary_enabled = True
                        settings.av_webcam_name_hint = name
                        settings.voice_v2_device_name = name
                        result["microphone"] = {
                            "index": int(idx),
                            "name": name,
                            "signal_probe": probe,
                        }
                    else:
                        result["microphone"] = {
                            "ok": False,
                            "error": "NO_LIVE_MIC_INPUT",
                            "probes": probes,
                        }
                except Exception as exc:
                    result["microphone"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

                vision_service = skill_context.services.get("vision")
                if vision_service is not None:
                    cameras = vision_service.list_cameras()
                    rows = cameras.get("cameras") or []
                    if rows:
                        selected = next((row for row in rows if row.get("configured")), rows[0])
                        cam_idx = int(selected["index"])
                        vision_service.set_camera_index(cam_idx)
                        settings.vision_camera_index = cam_idx
                        result["camera"] = selected
                    else:
                        result["camera"] = cameras
                Settings.update_file_values({
                    "mic_device": settings.mic_device,
                    "av_webcam_primary_enabled": settings.av_webcam_primary_enabled,
                    "av_webcam_name_hint": settings.av_webcam_name_hint,
                    "voice_v2_device_name": settings.voice_v2_device_name,
                    "vision_camera_index": settings.vision_camera_index,
                })
                if isinstance(result.get("microphone"), dict) and result["microphone"].get("index") is not None:
                    result["listening_recovery"] = listening_watchdog.recover(reason="owner_av_auto")
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower == "/av webcam on":
                settings.av_webcam_primary_enabled = True
                microphone.config.prefer_webcam_audio = True
                wake.config.prefer_webcam_audio = True
                Settings.update_file_values({"av_webcam_primary_enabled": True})
                recovered = listening_watchdog.recover(reason="owner_av_webcam_on")
                print("JARVIS >", json.dumps({"ok": True, "webcam_primary": True, "listening_recovery": recovered}, ensure_ascii=False, indent=2))
                continue
            if lower == "/av webcam off":
                settings.av_webcam_primary_enabled = False
                microphone.config.prefer_webcam_audio = False
                wake.config.prefer_webcam_audio = False
                Settings.update_file_values({"av_webcam_primary_enabled": False})
                recovered = listening_watchdog.recover(reason="owner_av_webcam_off")
                print("JARVIS >", json.dumps({"ok": True, "webcam_primary": False, "listening_recovery": recovered}, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/av mic "):
                raw_index = text[len("/av mic "):].strip()
                try:
                    index = int(raw_index)
                    devices = microphone.list_devices()
                    selected = next((row for row in devices if int(row["index"]) == index), None)
                    if selected is None:
                        raise ValueError("INVALID_MIC_DEVICE")
                    name = str(selected["name"])
                    microphone.config.device = index
                    microphone.config.preferred_device_index = index
                    microphone.config.prefer_webcam_audio = True
                    wake.config.preferred_device_index = index
                    if hasattr(wake.config, "preferred_device_name"):
                        wake.config.preferred_device_name = name
                    microphone.config.webcam_name_hint = name
                    wake.config.prefer_webcam_audio = True
                    wake.config.webcam_name_hint = name
                    settings.mic_device = index
                    settings.av_webcam_primary_enabled = True
                    settings.av_webcam_name_hint = name
                    settings.voice_v2_device_name = name
                    Settings.update_file_values({
                        "mic_device": index,
                        "av_webcam_primary_enabled": True,
                        "av_webcam_name_hint": name,
                        "voice_v2_device_name": name,
                    })
                    recovered = listening_watchdog.recover(reason="owner_av_mic_bind")
                    result = {"ok": True, "microphone": selected, "listening_recovery": recovered}
                except Exception as exc:
                    result = {"ok": False, "error": type(exc).__name__, "message": str(exc)}
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

            if lower == "/mic list":
                try:
                    devices = microphone.list_devices()
                    if not devices:
                        print("JARVIS > Não encontrei microfones de entrada.")
                    for d in devices:
                        marker = "*" if d.get("is_selected") else ("D" if d["is_default"] else " ")
                        print(
                            f"{marker} [{d['index']}] {d['name']} | "
                            f"{d['input_channels']} canal(is) | {d['default_samplerate']} Hz"
                        )
                    print("JARVIS > * = microfone selecionado pelo JARVIS | D = predefinido do Windows")
                except Exception as exc:
                    print(f"JARVIS > Erro ao listar microfones: {type(exc).__name__}: {exc}")
                continue
            if lower == "/mic status":
                print("JARVIS >", json.dumps(microphone.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/mic doctor":
                try:
                    candidates = microphone._input_device_candidates()
                    rows = []
                    for position, (idx, dev) in enumerate(candidates, start=1):
                        rows.append({
                            "position": position,
                            "index": int(idx),
                            "name": str(dev.get("name", "")),
                            "hostapi": str(dev.get("_hostapi_name", "")),
                            "channels": int(dev.get("max_input_channels", 0)),
                            "samplerate": int(
                                float(
                                    dev.get("default_samplerate", 0)
                                    or 0
                                )
                            ),
                        })
                    print(
                        "JARVIS >",
                        json.dumps(
                            rows,
                            ensure_ascii=False,
                            indent=2,
                        ),
                    )
                except Exception as exc:
                    print(
                        f"JARVIS > Erro no diagnóstico do microfone: "
                        f"{type(exc).__name__}: {exc}"
                    )
                continue

            if lower == "/mic default":
                result = microphone.set_device(None)
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower.startswith("/mic use "):
                raw_index = text.split(maxsplit=2)[2].strip()
                try:
                    index = int(raw_index)
                    result = microphone.set_device(index)
                    if result.get("ok"):
                        selected = dict(result.get("device") or {})
                        name = str(selected.get("name") or "").strip()
                        rate = int(selected.get("default_samplerate") or 0)
                        channels = int(selected.get("input_channels") or 0)
                        microphone.config.preferred_device_name = name or microphone.config.preferred_device_name
                        if rate > 0:
                            microphone.config.preferred_samplerate = rate
                        wake.config.preferred_device_index = index
                        if hasattr(wake.config, "preferred_device_name") and name:
                            wake.config.preferred_device_name = name
                        if hasattr(wake.config, "preferred_samplerate") and rate > 0:
                            wake.config.preferred_samplerate = rate
                        settings.mic_device = index
                        if name:
                            settings.mic_preferred_device_name = name
                            settings.voice_v2_device_name = name
                            settings.av_webcam_name_hint = name
                        if rate > 0:
                            settings.mic_preferred_samplerate = rate
                        settings.mic_preferred_handsfree = "hands-free" in name.lower() or "hands free" in name.lower()
                        Settings.update_file_values({
                            "mic_device": settings.mic_device,
                            "mic_preferred_device_name": settings.mic_preferred_device_name,
                            "mic_preferred_handsfree": settings.mic_preferred_handsfree,
                            "mic_preferred_samplerate": settings.mic_preferred_samplerate,
                            "voice_v2_device_name": settings.voice_v2_device_name,
                            "av_webcam_name_hint": settings.av_webcam_name_hint,
                        })
                        recovery = listening_watchdog.recover(reason="owner_mic_use")
                        result["persisted"] = True
                        result["channels"] = channels
                        result["listening_recovery"] = recovery
                except ValueError:
                    result = {"ok": False, "error": "INVALID_INDEX", "value": raw_index}
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower == "/voiceid status":
                print("JARVIS >", json.dumps(speaker.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/voiceid doctor":
                result = speaker.ensure_ready()
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower == "/voiceid on":
                speaker.set_enabled(True)
                print("JARVIS > Voice Lock ativado.")
                continue
            if lower == "/voiceid off":
                speaker.set_enabled(False)
                print("JARVIS > Voice Lock desativado.")
                continue
            if lower.startswith("/voiceid threshold "):
                raw = text.split(maxsplit=2)[2].strip()
                try:
                    value = speaker.set_threshold(float(raw))
                    print(f"JARVIS > Limiar Voice Lock definido para {value:.2f}.")
                except ValueError:
                    print("JARVIS > Valor inválido.")
                continue
            if lower == "/voiceid delete":
                removed = speaker.delete_profile()
                print("JARVIS >", "Perfil apagado." if removed else "Não existe perfil para apagar.")
                continue
            if lower == "/voiceid enroll":
                speech.stop(clear_queue=True)

                readiness = speaker.ensure_ready()
                if not readiness.get("ok"):
                    print("JARVIS >", json.dumps(readiness, ensure_ascii=False, indent=2))
                    continue

                total = max(3, int(settings.speaker_enrollment_samples))
                captures = []
                phrases = [
                    "Jarvis, confirma a minha identidade e fica pronto.",
                    "Jarvis, abre o Brave e verifica o estado do computador.",
                    "Jarvis, coloca o volume a trinta por cento.",
                    "Jarvis, mostra a temperatura atual da gráfica.",
                    "Jarvis, estou pronto para continuar.",
                ]
                print(
                    f"JARVIS > Vou registar {total} amostras da tua voz. "
                    "Fala normalmente e mantém o JBL na posição habitual."
                )

                failed = False
                try:
                    for i in range(total):
                        phrase = phrases[i % len(phrases)]
                        print(f"\nAmostra {i+1}/{total}. Diz: {phrase}")
                        capture = microphone.capture_phrase()
                        if not capture.get("ok"):
                            print("JARVIS >", json.dumps(capture, ensure_ascii=False, indent=2))
                            failed = True
                            break
                        captures.append(capture["wav_path"])

                        # Give Bluetooth/Windows time to release the capture
                        # endpoint before the next enrollment sample.
                        if i < total - 1:
                            sleep(max(0.5, float(settings.mic_stream_recovery_seconds)))

                    if not failed:
                        try:
                            result = speaker.enroll(captures)
                        except ModuleNotFoundError:
                            result = {
                                "ok": False,
                                "error": "VOICEID_DEPENDENCIES_MISSING",
                                "message": "Executa .\\setup_voiceid.ps1 e tenta novamente.",
                            }
                        except Exception as exc:
                            result = {
                                "ok": False,
                                "error": type(exc).__name__,
                                "message": str(exc),
                            }
                        print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                finally:
                    for wav in captures:
                        microphone.cleanup_capture(wav)
                continue
            if lower in {"/listen", "/ptt"}:
                handle_voice_command(source="manual")
                continue
            if lower == "/wake enroll":
                speech.stop(clear_queue=True)
                was_running = bool(wake.status().get("running"))
                if was_running:
                    wake.suspend()

                total = max(3, int(settings.wake_enrollment_samples))
                captures = []
                print(
                    f"JARVIS > Vou registar {total} amostras. "
                    "Em cada uma, diz apenas: Jarvis."
                )
                failed = False
                try:
                    for i in range(total):
                        print(f"\nWake {i+1}/{total}: diz apenas 'Jarvis'.")
                        capture = microphone.capture_phrase()
                        if not capture.get("ok"):
                            print(
                                "JARVIS >",
                                json.dumps(
                                    capture,
                                    ensure_ascii=False,
                                    indent=2,
                                ),
                            )
                            failed = True
                            break
                        captures.append(capture["wav_path"])
                        if i < total - 1:
                            sleep(
                                max(
                                    0.4,
                                    float(
                                        settings.mic_stream_recovery_seconds
                                    ),
                                )
                            )

                    if not failed:
                        result = wake.enroll(captures)
                        print(
                            "JARVIS >",
                            json.dumps(
                                result,
                                ensure_ascii=False,
                                indent=2,
                            ),
                        )
                finally:
                    for wav in captures:
                        microphone.cleanup_capture(wav)
                    if was_running:
                        wake.resume()
                continue

            if lower == "/wake test":
                speech.stop(clear_queue=True)
                was_running = bool(wake.status().get("running"))
                if was_running:
                    wake.suspend()
                wav_path = None
                try:
                    print("JARVIS > Teste de wake preparado. Quando aparecer 'A ouvir...', diz apenas: Jarvis.")
                    print("JARVIS > A ouvir... diz agora: Jarvis.")
                    capture = microphone.capture_phrase()
                    if not capture.get("ok"):
                        print("JARVIS >", json.dumps(capture, ensure_ascii=False, indent=2))
                        continue
                    wav_path = capture.get("wav_path")
                    if hasattr(wake, "test_wake_file"):
                        result = wake.test_wake_file(wav_path)
                    else:
                        result = {"ok": False, "error": "WAKE_TEST_UNAVAILABLE_ON_BACKEND"}
                    result["capture"] = {
                        "duration_seconds": capture.get("duration_seconds"),
                        "device": capture.get("device"),
                        "device_name": capture.get("device_name"),
                        "noise_rms": capture.get("noise_rms"),
                        "max_rms": capture.get("max_rms"),
                    }
                    print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                finally:
                    if wav_path:
                        microphone.cleanup_capture(wav_path)
                    if was_running:
                        wake.resume()
                continue

            if lower == "/wake delete":
                wake.stop()
                removed = wake.delete_profile()
                print(
                    "JARVIS > Perfil wake apagado."
                    if removed
                    else "JARVIS > Não existia perfil wake."
                )
                continue

            if lower == "/interrupt enroll":
                speech.stop(clear_queue=True)
                was_running = bool(wake.status().get("running"))
                if was_running:
                    wake.suspend()
                total = max(3, int(settings.interrupt_enrollment_samples))
                captures = []
                print(f"JARVIS > Vou registar {total} amostras. Em cada uma, diz apenas: Cala-te.")
                failed = False
                try:
                    for i in range(total):
                        print(f"\nInterrupção {i+1}/{total}: diz apenas 'Cala-te'.")
                        capture = microphone.capture_phrase()
                        if not capture.get("ok"):
                            print("JARVIS >", json.dumps(capture, ensure_ascii=False, indent=2))
                            failed = True
                            break
                        captures.append(capture["wav_path"])
                        if i < total - 1:
                            sleep(max(0.4, float(settings.mic_stream_recovery_seconds)))
                    if not failed:
                        result = wake.enroll_interrupt(captures)
                        print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                finally:
                    for wav in captures:
                        microphone.cleanup_capture(wav)
                    if was_running:
                        wake.resume()
                continue

            if lower == "/interrupt status":
                status = wake.status()
                print("JARVIS >", json.dumps({"enrolled": status.get("interrupt_enrolled"), "threshold": status.get("interrupt_threshold"), "phrase": "Cala-te"}, ensure_ascii=False, indent=2))
                continue

            if lower == "/interrupt delete":
                removed = wake.delete_interrupt_profile()
                print("JARVIS > Perfil 'Cala-te' apagado." if removed else "JARVIS > Não existia perfil 'Cala-te'.")
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

            if lower == "/privacy status":
                print("JARVIS >", json.dumps(privacy.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/privacy on":
                result = read_tool("set_privacy_mode", {"enabled": True})
                print("JARVIS > Modo privado ativado. Cloud bloqueada." if result.get("ok") else f"JARVIS > {result}")
                continue
            if lower == "/privacy off":
                result = read_tool("set_privacy_mode", {"enabled": False})
                print("JARVIS > Modo privado desativado." if result.get("ok") else f"JARVIS > {result}")
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
            if lower == "/mind speech on":
                print("JARVIS >", json.dumps(cognition.set_mode(proactive_speech_enabled=True), ensure_ascii=False, indent=2))
                continue
            if lower == "/mind speech off":
                print("JARVIS >", json.dumps(cognition.set_mode(proactive_speech_enabled=False), ensure_ascii=False, indent=2))
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
                raw = text[len("/cyber lab probe "):].strip()
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
                result = cyber_range.probe(target, ports)
                print(f"JARVIS >\n{format_lab_probe(result)}")
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
                result = kali_bridge.doctor()
                print("JARVIS >", json.dumps(result, ensure_ascii=False, indent=2))
                continue
            if lower == "/cyber kali inventory":
                result = kali_bridge.inventory()
                print(f"JARVIS >\n{format_kali_inventory(result)}")
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
                result = kali_bridge.nmap_service_scan(target, ports)
                print(f"JARVIS >\n{format_kali_scan(result)}")
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
                result = kali_bridge.whatweb_fingerprint(target, port, https)
                print(f"JARVIS >\n{format_kali_scan(result)}")
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
                result = kali_bridge.nikto_safe_web_scan(target, port, https)
                print(f"JARVIS >\n{format_kali_scan(result)}")
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
                result = cyber_knowledge.sync(full=False)
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
                result = cyber_knowledge.sync(full=True)
                print(
                    f"JARVIS >\n"
                    f"{format_cyber_knowledge_sync(result)}"
                )
                continue
            if lower.startswith("/cyber knowledge sync source "):
                source_id = text[
                    len("/cyber knowledge sync source "):
                ].strip()
                result = cyber_knowledge.sync(source_id=source_id)
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

            if lower == "/wake status":
                print(
                    "JARVIS >",
                    json.dumps(wake.status(), ensure_ascii=False, indent=2),
                )
                continue
            if lower == "/wake doctor":
                result = wake.doctor()
                print(
                    "JARVIS >",
                    json.dumps(result, ensure_ascii=False, indent=2),
                )
                continue
            if lower == "/wake on":
                result = wake.start()
                if result.get("ok"):
                    listening_watchdog.set_armed(True)
                print(
                    "JARVIS >",
                    json.dumps(result, ensure_ascii=False, indent=2),
                )
                continue
            if lower == "/wake off":
                listening_watchdog.set_armed(False)
                wake.stop()
                print("JARVIS > Always Listening parado. Auto-recuperação desarmada.")
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
            if lower == "/research test":
                result = research_engine.test()
                print(f"JARVIS > {result.text}")
                if debug_terminal["enabled"]:
                    print(
                        f"  [RESEARCH] model={result.model} "
                        f"{result.elapsed_ms}ms sources={len(result.sources or [])}"
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
                print("JARVIS > A pré-carregar os modelos.")
                result = {
                    "voiceid": (
                        speaker.ensure_ready()
                        if speaker.enrolled()
                        else {"ok": True, "skipped": "not_enrolled"}
                    ),
                    "stt": microphone.preload_stt(),
                    "llm": brain.warmup(),
                }
                print(json.dumps(result, ensure_ascii=False, indent=2))
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

            if lower == "/desktop status":
                print("JARVIS >", json.dumps(desktop.status(), ensure_ascii=False, indent=2))
                continue
            if lower == "/desktop ensure":
                print("JARVIS >", json.dumps(desktop.start(), ensure_ascii=False, indent=2))
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

            # Natural typed/voice equivalents remain token-bound.
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
                answer, route, command_ms, hybrid = process_request(text)
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
                speech.say(answer)
    finally:
        activity_trace.stop()
        listening_watchdog.stop()
        if settings.skills_enabled:
            skills.stop_all()
        if bool(getattr(settings, "ollama_release_on_shutdown", True)):
            brain.release_all_models(
                reason="jarvis_shutdown",
                include_configured=True,
            )
        reminder_service.stop()
        security_watch_service.stop()
        proactive_service.stop()
        companion_service.stop()
        book_library_service.stop()
        cyber_knowledge_service.stop()
        wake.stop()
        speech.shutdown()
        performance.stop()
        telemetry.stop()


if __name__ == "__main__":
    main()
