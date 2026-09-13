from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from jarvis_core.application import (
    JarvisApplication,
)
from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.config import Settings
from jarvis_core.core.events import EventBus
from jarvis_core.core.fast_router import (
    FastCommandRouter,
)
from jarvis_core.core.hybrid_brain import HybridBrain
from jarvis_core.core.tool_registry import ToolRegistry
from jarvis_core.memory.canonical_store import (
    CanonicalMemoryStore,
)
from jarvis_core.memory.model_adapter import (
    TrustedTwoStageSemanticMemoryAdapter,
)
from jarvis_core.memory.owner_bootstrap import (
    ensure_canonical_owner,
)
from jarvis_core.memory.qwen_identity_matcher import (
    QwenSemanticIdentityMatcher,
)
from jarvis_core.memory.qwen_model import (
    JarvisQwenMemoryModel,
)
from jarvis_core.runtime import JarvisRuntime
from jarvis_core.security.policy import SecurityPolicy
from jarvis_core.services.activity_trace import (
    ActivityTraceService,
)
from jarvis_core.services.agenda import agenda_store
from jarvis_core.services.autonomy import (
    AutonomyGuardian,
    set_autonomy_guardian,
)
from jarvis_core.services.book_library import (
    configure_book_library,
)
from jarvis_core.services.context_store import (
    context_store,
)
from jarvis_core.services.cyber_knowledge import (
    configure_cyber_knowledge_egress,
    cyber_vault,
)
from jarvis_core.services.cyber_range import (
    CyberRangeManager,
    set_cyber_range_manager,
)
from jarvis_core.services.external_learning import (
    configure_external_learning_runtime,
)
from jarvis_core.services.file_index import (
    configure_file_index,
)
from jarvis_core.services.integrations import (
    integration_registry,
)
from jarvis_core.services.kali_bridge import (
    KaliBridgeManager,
    set_kali_bridge_manager,
)
from jarvis_core.services.local_research import (
    LocalResearchEngine,
)
from jarvis_core.services.network_inventory import (
    network_inventory,
)
from jarvis_core.services.performance import (
    PerformanceGovernor,
)
from jarvis_core.services.personal_cognition import (
    personal_cognition,
)
from jarvis_core.services.profiles import (
    manager as profile_manager,
)
from jarvis_core.services.relational_presence import (
    relational_presence,
)
from jarvis_core.services.routines import (
    routine_manager,
)
from jarvis_core.services.silence_latch import (
    SilenceLatchService,
)
from jarvis_core.services.synthetic_self import (
    synthetic_self,
)
from jarvis_core.services.telemetry import (
    TelemetryService,
)
from jarvis_core.services.user_memory import (
    store as user_memory_store,
)
from jarvis_core.skills import SkillContext, SkillManager
from jarvis_core.tools.environment_tools import (
    configure_environment_egress,
)
from jarvis_core.tools.windows_actions import AppRegistry


@dataclass(
    frozen=True,
    slots=True,
)
class JarvisCoreContext:
    """
    Trusted internal Core context.

    This object is for local Core/admin transports such as the technical
    terminal. It is deliberately separate from JarvisApplication so Web
    transports do not receive direct access to internal stores, registries,
    locks, skills or security implementation objects.
    """

    memory: object
    profiles: object
    user_address: str
    agenda: object
    routines: object
    inventory: object
    integrations: object
    book_library: object
    cognition: object
    self_engine: object
    security: object
    apps: object
    cyber_range: object
    tools: object
    memory1_store: object
    research_engine: object
    skill_context: object
    skills: object
    hybrid_brain: object
    command_lock: object
    silence_latch: object


@dataclass(
    frozen=True,
    slots=True,
)
class ApplicationBootstrapResult:
    """
    Result of constructing one live JARVIS Core application.

    Public transports consume `application`. Trusted local/admin code may
    additionally consume `context`.
    """

    application: JarvisApplication
    context: JarvisCoreContext


_BOOTSTRAP_RESULT: ApplicationBootstrapResult | None = None
_BOOTSTRAP_LOCK = RLock()


def build_application() -> ApplicationBootstrapResult:
    """
    Build one process-wide live JARVIS Core.

    Repeated callers in the same process receive the exact same application,
    Brain, Memory 1.0 and JarvisRuntime graph.
    """

    global _BOOTSTRAP_RESULT

    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP_RESULT is not None:
            return _BOOTSTRAP_RESULT

        Settings.ensure_file_schema()
        settings = Settings.load()

        events = EventBus(
            settings.log_dir,
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )

        memory = user_memory_store()
        profiles = profile_manager()
        persistent_context = context_store()
        agenda = agenda_store()
        routines = routine_manager()
        inventory = network_inventory()

        configure_file_index(
            extra_roots=[
                settings.book_library_root
            ]
        )

        integrations = integration_registry()
        cyber_knowledge = cyber_vault()

        book_library = configure_book_library(
            settings.book_library_root,
            settings.book_library_db_path,
            chunk_chars=(
                settings.book_library_chunk_chars
            ),
            chunk_overlap=(
                settings.book_library_chunk_overlap
            ),
        )

        cognition = personal_cognition()

        try:
            from jarvis_core.services.memory_maintenance import (
                refresh_runtime_personal_memory,
            )

            refresh_runtime_personal_memory()

        except Exception:
            pass

        self_engine = synthetic_self()
        relational_presence_store = (
            relational_presence()
        )

        user_profile = memory.profile()
        active_profile = profiles.active()

        user_address = (
            active_profile.get("address_as")
            or user_profile.get("address_as")
            or "Senhor"
        )

        security = SecurityPolicy()

        telemetry = TelemetryService(
            events,
            interval_seconds=(
                settings.telemetry_interval_seconds
            ),
            history_seconds=(
                settings.telemetry_history_seconds
            ),
            gpu_interval_seconds=(
                settings
                .performance_gpu_sample_interval_seconds
            ),
        )

        performance = PerformanceGovernor(
            settings,
            events,
            telemetry,
        )

        apps = AppRegistry(
            "apps.json"
        )

        cyber_range = CyberRangeManager(
            settings.cyber_range_state_path,
            enabled=settings.cyber_range_enabled,
            probe_timeout_seconds=(
                settings
                .cyber_range_probe_timeout_seconds
            ),
        )

        set_cyber_range_manager(
            cyber_range
        )

        kali_bridge = KaliBridgeManager(
            settings.kali_bridge_state_path,
            enabled=settings.kali_bridge_enabled,
            ssh_executable=(
                settings.kali_bridge_ssh_executable
            ),
            connect_timeout_seconds=(
                settings
                .kali_bridge_connect_timeout_seconds
            ),
            command_timeout_seconds=(
                settings
                .kali_bridge_command_timeout_seconds
            ),
            output_max_chars=(
                settings.kali_bridge_output_max_chars
            ),
            known_hosts_path=(
                settings.kali_bridge_known_hosts_path
            ),
            vm_provider=settings.kali_vm_provider,
            vm_identifier=(
                settings.kali_vm_identifier
            ),
            vm_visible=settings.kali_vm_visible,
            activity_log_path=(
                settings.kali_activity_log_path
            ),
        )

        set_kali_bridge_manager(
            kali_bridge
        )

        tools = ToolRegistry(
            events,
            security,
            telemetry,
            apps,
        )

        autonomy = AutonomyGuardian(
            settings,
            events,
        )

        set_autonomy_guardian(
            autonomy
        )

        configure_cyber_knowledge_egress(
            autonomy
        )

        configure_environment_egress(
            autonomy
        )

        kali_bridge.set_authority_guardian(
            autonomy
        )

        cyber_range.set_authority_guardian(
            autonomy
        )

        brain = JarvisBrain(
            settings,
            events,
            tools,
            performance=performance,
        )

        memory1_store = (
            CanonicalMemoryStore()
        )

        memory1_owner_bindings = (
            ensure_canonical_owner(
                memory1_store
            )
        )

        memory1_owner_id = (
            memory1_owner_bindings
            .canonical_id_for(
                "owner"
            )
        )

        memory1_qwen_model = (
            JarvisQwenMemoryModel(
                brain.client,
                model=settings.model,
            )
        )

        memory1_matcher = (
            QwenSemanticIdentityMatcher(
                memory1_qwen_model
            )
        )

        memory1_adapter = (
            TrustedTwoStageSemanticMemoryAdapter(
                memory1_qwen_model,
                model_id=settings.model,
            )
        )

        research_engine = LocalResearchEngine(
            settings,
            events,
            brain,
            egress_guardian=autonomy,
        )

        configure_external_learning_runtime(
            research_engine,
            events,
        )

        skill_context = SkillContext(
            settings=settings,
            events=events,
            registry=tools,
            brain=brain,
            apps=apps,
            memory=memory,
            cyber_range=cyber_range,
            kali_bridge=kali_bridge,
        )

        skills = SkillManager(
            skill_context,
            external_root=(
                settings.skills_external_root
            ),
            trust_path=(
                settings.skills_trust_path
            ),
            external_enabled=(
                settings.skills_enabled
                and
                settings.skills_external_enabled
            ),
        )

        if settings.skills_enabled:
            skills.load_all()

        hybrid_brain = HybridBrain(
            settings,
            events,
            local_brain=brain,
            performance=performance,
            autonomy=autonomy,
            research_engine=research_engine,
        )

        fast_router = FastCommandRouter(
            events,
            tools,
            apps,
        )

        command_lock = RLock()

        silence_latch = SilenceLatchService(
            events,
            enabled=(
                settings.silence_latch_enabled
            ),
        )

        activity_trace = ActivityTraceService(
            events,
            path=settings.activity_trace_path,
            enabled=(
                settings.activity_trace_enabled
            ),
            live=False,
        )

        runtime = JarvisRuntime(
            settings=settings,
            events=events,
            performance=performance,
            apps=apps,
            persistent_context=persistent_context,
            cognition=cognition,
            relational_presence_store=(
                relational_presence_store
            ),
            self_engine=self_engine,
            memory1_store=memory1_store,
            memory1_owner_bindings=(
                memory1_owner_bindings
            ),
            memory1_owner_id=(
                memory1_owner_id
            ),
            memory1_matcher=memory1_matcher,
            memory1_adapter=memory1_adapter,
            hybrid_brain=hybrid_brain,
            fast_router=fast_router,
        )

        application = JarvisApplication(
            runtime=runtime,
            autonomy=autonomy,
            kali_bridge=kali_bridge,
            cyber_knowledge=cyber_knowledge,
            settings=settings,
            events=events,
            brain=brain,
            telemetry=telemetry,
            performance=performance,
            activity_trace=activity_trace,
        )

        context = JarvisCoreContext(
            memory=memory,
            profiles=profiles,
            user_address=user_address,
            agenda=agenda,
            routines=routines,
            inventory=inventory,
            integrations=integrations,
            book_library=book_library,
            cognition=cognition,
            self_engine=self_engine,
            security=security,
            apps=apps,
            cyber_range=cyber_range,
            tools=tools,
            memory1_store=memory1_store,
            research_engine=research_engine,
            skill_context=skill_context,
            skills=skills,
            hybrid_brain=hybrid_brain,
            command_lock=command_lock,
            silence_latch=silence_latch,
        )

        result = ApplicationBootstrapResult(
            application=application,
            context=context,
        )

        _BOOTSTRAP_RESULT = result

        return result
