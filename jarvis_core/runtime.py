from __future__ import annotations

from dataclasses import dataclass

from time import monotonic

from jarvis_core.services.learning_followup import (
    get_learning_followup_context,
)
from jarvis_core.services.request_intent import (
    sanitize_assistant_text,
)
from jarvis_core.services.semantic_intent import (
    resolve_semantic_request,
)
from jarvis_core.memory.enums import (
    MemoryAuthority,
    SourceType,
)
from jarvis_core.memory.errors import (
    MemoryAvailabilityError,
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
from jarvis_core.memory.resolution_plan import (
    build_memory_resolution_plan,
    remember_plan_has_ambiguous_identity,
)
from jarvis_core.memory.write_executor import (
    TrustedWriteExecutionContext,
    execute_memory_resolution_plan,
)

@dataclass(frozen=True, slots=True)
class ProcessRequestResult:
    """Stable transport-neutral result of one JARVIS turn."""

    answer: str
    route: str
    elapsed_ms: int
    hybrid: object | None


_MODEL_OWNED_SEMANTIC_INTENTS = frozenset({
    "GENERAL_CONVERSATION",
    "SOCIAL_INTERACTION",
    "SELF_STATE",
    "IDENTITY_DIALOGUE",
    "CONVERSATION_RECALL",
    "KNOWLEDGE_CAPABILITY",
})


def route_runtime_request(
    user_text: str,
    *,
    source: str,
    semantic_context_inputs,
    events,
    fast_router,
    hybrid_brain,
    memory_grounding_context: str = "",
    requires_memory_aware_response: bool = False,
    before_hybrid=None,
):
    """
    Execute the transport-neutral semantic routing core.

    This function deliberately owns only routing:
    semantic context -> StructuredRequest -> deterministic FastRouter
    or model-owned HybridBrain.

    Persistence, cognition, performance accounting, runtime lifecycle,
    and other runtime side effects remain owned by JarvisRuntime.process_request().
    """
    semantic_inputs = tuple(
        semantic_context_inputs()
    )

    if len(
        semantic_inputs
    ) == 2:
        (
            semantic_recent_turns,
            semantic_app_aliases,
        ) = semantic_inputs

        semantic_learning_followup = None

    elif len(
        semantic_inputs
    ) == 3:
        (
            semantic_recent_turns,
            semantic_app_aliases,
            semantic_learning_followup,
        ) = semantic_inputs

    else:
        raise ValueError(
            "semantic_context_inputs must return "
            "2 or 3 values"
        )

    structured_request = resolve_semantic_request(
        user_text,
        recent_turns=semantic_recent_turns,
        app_aliases=semantic_app_aliases,
        learning_followup=(
            semantic_learning_followup
        ),
    )

    events.emit(
        "SEMANTIC_REQUEST_RESOLVED",
        intent=structured_request.intent,
        domain=structured_request.domain,
        subject=structured_request.subject,
        action=structured_request.action,
        requires_tool=structured_request.requires_tool,
        preferred_tool=structured_request.preferred_tool,
        epistemic_learning_eligible=(
            structured_request.epistemic_learning_eligible
        ),
        confidence=structured_request.confidence,
    )

    model_owned = (
        structured_request.intent
        in _MODEL_OWNED_SEMANTIC_INTENTS
    )

    fast = None

    memory_aware_response_required = (
        bool(memory_grounding_context)
        or bool(
            requires_memory_aware_response
        )
    )

    if (
        model_owned
        or memory_aware_response_required
    ):
        events.emit(
            "FAST_ROUTER_BYPASSED",
            intent=structured_request.intent,
            domain=structured_request.domain,
            subject=structured_request.subject,
            reason=(
                "memory_aware_response_required"
                if memory_aware_response_required
                else "model_owned_semantic_intent"
            ),
        )
    else:
        fast = fast_router.dispatch(
            user_text,
            request=structured_request,
        )

    if fast is not None and fast.handled:
        fast.response = sanitize_assistant_text(
            fast.response,
            user_text=user_text,
        )

        return (
            fast.response,
            f"FAST/{fast.route}",
            None,
        )

    if before_hybrid is not None:
        before_hybrid()

    if memory_grounding_context:
        hybrid = hybrid_brain.ask(
            user_text,
            request=structured_request,
            memory_grounding_context=(
                memory_grounding_context
            ),
        )
    else:
        hybrid = hybrid_brain.ask(
            user_text,
            request=structured_request,
        )

    return (
        hybrid.text,
        hybrid.route,
        hybrid,
    )


class JarvisRuntime:
    """
    Shared transport-neutral JARVIS conversational runtime.

    Terminal and Web transports must enter the same process_request()
    pipeline so Memory 1.0, semantic routing, Qwen reasoning, cognition,
    persistence and observable runtime effects remain canonical.
    """

    def __init__(
        self,
        *,
        settings,
        events,
        performance,
        apps,
        persistent_context,
        cognition,
        relational_presence_store,
        self_engine,
        memory1_store,
        memory1_owner_bindings,
        memory1_owner_id,
        memory1_matcher,
        memory1_adapter,
        hybrid_brain,
        fast_router,
    ):
        self.settings = settings
        self.events = events
        self.performance = performance
        self.apps = apps
        self.persistent_context = persistent_context
        self.cognition = cognition
        self.relational_presence_store = relational_presence_store
        self.self_engine = self_engine
        self.memory1_store = memory1_store
        self.memory1_owner_bindings = memory1_owner_bindings
        self.memory1_owner_id = memory1_owner_id
        self.memory1_matcher = memory1_matcher
        self.memory1_adapter = memory1_adapter
        self.hybrid_brain = hybrid_brain
        self.fast_router = fast_router

    def semantic_context_inputs(self):
        """
        Return read-only semantic context inputs.

        Failure to read either source must fail closed:
        no persisted context and/or no application catalogue
        means the semantic resolver receives empty data.
        """
        settings = self.settings
        persistent_context = self.persistent_context
        apps = self.apps
        events = self.events
        recent_turns = []

        if settings.persistent_context_enabled:
            try:
                recent_turns = persistent_context.recent(4)
            except Exception as exc:
                recent_turns = []
                events.emit(
                    "SEMANTIC_CONTEXT_READ_ERROR",
                    error=f"{type(exc).__name__}: {exc}",
                )

        app_aliases = {}

        try:
            app_rows = apps.list_apps()

            for item in app_rows:
                if not isinstance(item, dict):
                    continue

                if item.get("enabled") is False:
                    continue

                canonical = str(
                    item.get("id")
                    or ""
                ).strip()

                if not canonical:
                    continue

                values = [
                    canonical,
                    item.get("name"),
                    *list(
                        item.get("aliases")
                        or []
                    ),
                ]

                for value in values:
                    alias = str(
                        value
                        or ""
                    ).strip()

                    if alias:
                        app_aliases[alias] = canonical

        except Exception as exc:
            app_aliases = {}
            events.emit(
                "SEMANTIC_APP_CATALOG_READ_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )

        learning_followup = None

        try:
            learning_followup = (
                get_learning_followup_context(
                    max_age_seconds=300.0
                )
            )
        except Exception as exc:
            learning_followup = None
            events.emit(
                "SEMANTIC_LEARNING_FOLLOWUP_READ_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )

        return (
            recent_turns,
            app_aliases,
            learning_followup,
        )

    def process_request(self, user_text: str, *, source: str = "terminal") -> ProcessRequestResult:
        """Fast Path -> local reasoning or direct-web/local-synthesis research."""
        settings = self.settings
        events = self.events
        performance = self.performance
        persistent_context = self.persistent_context
        cognition = self.cognition
        relational_presence_store = self.relational_presence_store
        self_engine = self.self_engine
        memory1_store = self.memory1_store
        memory1_owner_bindings = self.memory1_owner_bindings
        memory1_owner_id = self.memory1_owner_id
        memory1_matcher = self.memory1_matcher
        memory1_adapter = self.memory1_adapter
        hybrid_brain = self.hybrid_brain
        fast_router = self.fast_router
        semantic_context_inputs = self.semantic_context_inputs
        memory1_occurred_at = utc_now()
        command_started = monotonic()
        try:
            self_engine.observe_owner_input(user_text, source=source)
        except Exception as exc:
            events.emit(
                "SYNTHETIC_SELF_INPUT_OBSERVE_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            relational_presence_store.observe_owner_input(
                user_text
            )
        except Exception as exc:
            events.emit(
                "RELATIONAL_PRESENCE_INPUT_OBSERVE_ERROR",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )


        # MEMORY1_RUNTIME_PRE_ROUTE_V1
        from jarvis_core.memory.recall_executor import (
            execute_memory_recall_plan,
        )
        from jarvis_core.memory.recall_grounding import (
            build_memory1_recall_fail_closed_grounding,
            build_memory1_recall_fail_closed_status,
            build_memory1_recall_grounding,
            build_memory1_recall_status,
        )
        from jarvis_core.memory.runtime_result import (
            MemoryInterpretationStatus,
            MemoryTurnResult,
            RememberTurnOutcome,
            RememberTurnResult,
            build_memory1_interpretation_fail_closed_context,
            build_deterministic_remember_receipt_response,
            build_memory1_remember_response_context,
            build_memory1_turn_status_context,
            build_remember_turn_result,
        )

        memory1_interpretation = None
        memory1_plan = None
        memory1_turn_result = None
        memory1_grounding_context = ""
        memory1_deterministic_remember_response = None

        # Fail closed for routing until the Memory1 interpreter
        # successfully proves what operation this turn contains.
        # RECALL and REMEMBER both require the model-owned Memory1
        # response path; neither may be consumed by FastRouter.
        memory1_requires_memory_aware_response = True

        try:
            memory1_context = InterpreterContext(
                locale="pt-PT",
                default_subject_ref="owner",
                current_time=memory1_occurred_at,
                known_entity_refs=(
                    memory1_owner_bindings
                    .local_refs()
                ),
            )

            memory1_envelope = (
                memory1_adapter.interpret(
                    user_text,
                    context=memory1_context,
                )
            )

            memory1_interpretation = (
                memory1_envelope
                .interpretation
            )

            memory1_interpretation_status = (
                MemoryInterpretationStatus.NEEDS_CONFIRMATION
                if (
                    memory1_interpretation.needs_confirmation
                    or memory1_interpretation.ambiguities
                )
                else MemoryInterpretationStatus.VALID
            )

            memory1_turn_result = MemoryTurnResult(
                operation=memory1_interpretation.operation,
                interpretation_status=(
                    memory1_interpretation_status
                ),
            )

            memory1_requires_memory_aware_response = (
                memory1_interpretation.operation
                in {
                    MemoryOperation.RECALL,
                    MemoryOperation.REMEMBER,
                }
            )

            if (
                memory1_interpretation.operation
                is MemoryOperation.RECALL
            ):
                memory1_plan = (
                    build_memory_resolution_plan(
                        memory1_interpretation,
                        matcher=memory1_matcher,
                        entity_registry=memory1_store,
                        property_registry=memory1_store,
                        trusted_entity_bindings=(
                            memory1_owner_bindings
                        ),
                    )
                )

                memory1_read_result = (
                    execute_memory_recall_plan(
                        memory1_plan,
                        store=memory1_store,
                    )
                )

                memory1_grounding = (
                    build_memory1_recall_grounding(
                        memory1_read_result
                    )
                )

                memory1_recall_status = (
                    build_memory1_recall_status(
                        memory1_read_result
                    )
                )

                memory1_turn_result = MemoryTurnResult(
                    operation=MemoryOperation.RECALL,
                    interpretation_status=(
                        memory1_interpretation_status
                    ),
                    recall=memory1_recall_status,
                )

                memory1_grounding_context = (
                    memory1_grounding.context
                    + "\n\n"
                    + build_memory1_turn_status_context(
                        memory1_turn_result
                    )
                )

                events.emit(
                    "MEMORY1_RUNTIME_RECALL_GROUNDED",
                    source=source,
                    evidence_status=(
                        memory1_grounding
                        .evidence_status
                    ),
                    evidence_count=(
                        memory1_grounding
                        .evidence_count
                    ),
                    recall_aggregate=(
                        memory1_recall_status
                        .aggregate
                        .value
                    ),
                    recall_item_count=(
                        memory1_recall_status
                        .item_count
                    ),
                    interpretation_status=(
                        memory1_turn_result
                        .interpretation_status
                        .value
                    ),
                )

            elif (
                memory1_interpretation.operation
                is MemoryOperation.REMEMBER
            ):
                if (
                    memory1_interpretation_status
                    is MemoryInterpretationStatus.NEEDS_CONFIRMATION
                ):
                    memory1_grounding_context = (
                        build_memory1_remember_response_context(
                            memory1_turn_result
                        )
                    )

                    events.emit(
                        "MEMORY1_RUNTIME_REMEMBER_NEEDS_CONFIRMATION",
                        source=source,
                    )

                else:
                    memory1_plan = (
                        build_memory_resolution_plan(
                            memory1_interpretation,
                            matcher=memory1_matcher,
                            entity_registry=memory1_store,
                            property_registry=memory1_store,
                            trusted_entity_bindings=(
                                memory1_owner_bindings
                            ),
                        )
                    )

                    if remember_plan_has_ambiguous_identity(
                        memory1_plan
                    ):
                        memory1_remember_result = (
                            RememberTurnResult(
                                outcome=(
                                    RememberTurnOutcome.AMBIGUOUS
                                )
                            )
                        )

                    else:
                        memory1_authority = (
                            MemoryAuthority.OWNER_EXPLICIT
                            if (
                                memory1_interpretation
                                .explicit_memory_request
                            )
                            else (
                                MemoryAuthority
                                .CONVERSATION_DERIVED
                            )
                        )

                        memory1_recorded_at = utc_now()

                        memory1_write_context = (
                            TrustedWriteExecutionContext(
                                raw_text=user_text,
                                source_type=SourceType.OWNER_TURN,
                                authority=memory1_authority,
                                occurred_at=memory1_occurred_at,
                                recorded_at=memory1_recorded_at,
                                actor_entity_id=memory1_owner_id,
                                speaker_entity_id=memory1_owner_id,
                                conversation_id=None,
                                sequence=None,
                            )
                        )

                        memory1_receipt = (
                            execute_memory_resolution_plan(
                                memory1_plan,
                                store=memory1_store,
                                context=memory1_write_context,
                            )
                        )

                        memory1_remember_result = (
                            build_remember_turn_result(
                                memory1_receipt
                            )
                        )

                    memory1_turn_result = MemoryTurnResult(
                        operation=MemoryOperation.REMEMBER,
                        interpretation_status=(
                            memory1_interpretation_status
                        ),
                        remember=memory1_remember_result,
                    )

                    if (
                        memory1_remember_result.receipt
                        is not None
                    ):
                        memory1_deterministic_remember_response = (
                            build_deterministic_remember_receipt_response(
                                memory1_remember_result
                            )
                        )

                    memory1_grounding_context = (
                        build_memory1_remember_response_context(
                            memory1_turn_result
                        )
                    )

                    if (
                        memory1_remember_result.outcome
                        is RememberTurnOutcome.COMMITTED
                    ):
                        events.emit(
                            "MEMORY1_RUNTIME_WRITE_COMMITTED",
                            transaction_id=(
                                memory1_remember_result
                                .receipt
                                .transaction_id
                            ),
                            canonical_revision=(
                                memory1_remember_result
                                .receipt
                                .canonical_revision
                            ),
                            episode_count=len(
                                memory1_remember_result
                                .receipt
                                .episode_ids
                            ),
                            fact_count=len(
                                memory1_remember_result
                                .receipt
                                .fact_ids
                            ),
                            relation_count=len(
                                memory1_remember_result
                                .receipt
                                .relation_ids
                            ),
                        )

                    elif (
                        memory1_remember_result.outcome
                        is RememberTurnOutcome.NO_CHANGE_IDEMPOTENT
                    ):
                        events.emit(
                            "MEMORY1_RUNTIME_WRITE_IDEMPOTENT",
                            message_code=(
                                memory1_remember_result
                                .receipt
                                .message_code
                            ),
                        )

                    elif (
                        memory1_remember_result.outcome
                        is RememberTurnOutcome.AMBIGUOUS
                    ):
                        events.emit(
                            "MEMORY1_RUNTIME_REMEMBER_AMBIGUOUS",
                            source=source,
                        )

                    else:
                        events.emit(
                            "MEMORY1_RUNTIME_WRITE_NOT_COMMITTED",
                            status=(
                                memory1_remember_result
                                .outcome
                                .value
                            ),
                            message_code=(
                                memory1_remember_result
                                .receipt
                                .message_code
                            ),
                        )

        except MemoryAvailabilityError as exc:
            if (
                memory1_interpretation is not None
                and memory1_interpretation.operation is MemoryOperation.RECALL
            ):
                memory1_fail_closed = build_memory1_recall_fail_closed_grounding()
                memory1_recall_status = build_memory1_recall_fail_closed_status()
                memory1_turn_result = MemoryTurnResult(
                    operation=MemoryOperation.RECALL,
                    interpretation_status=MemoryInterpretationStatus.VALID,
                    recall=memory1_recall_status,
                )
                memory1_grounding_context = (
                    memory1_fail_closed.context
                    + "\n\n"
                    + build_memory1_turn_status_context(memory1_turn_result)
                )
                events.emit(
                    "MEMORY1_RUNTIME_RECALL_FAIL_CLOSED",
                    source=source,
                    error_type=type(exc).__name__,
                )
            elif (
                memory1_interpretation is not None
                and memory1_interpretation.operation is MemoryOperation.REMEMBER
            ):
                events.emit(
                    "MEMORY1_RUNTIME_REMEMBER_UNAVAILABLE",
                    source=source,
                    error_type=type(exc).__name__,
                )
                raise
            else:
                selected_operation = getattr(exc, "selected_operation", None)
                memory1_turn_result = MemoryTurnResult(
                    operation=None,
                    interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE,
                )
                memory1_grounding_context = (
                    build_memory1_interpretation_fail_closed_context(memory1_turn_result)
                )
                if selected_operation is MemoryOperation.RECALL:
                    answer = (
                        "Não consegui consultar a memória neste momento. "
                        "Tenta novamente daqui a pouco."
                    )
                    route = "MEMORY1_RECALL_MODEL_FAILURE_FAIL_CLOSED"
                elif selected_operation is MemoryOperation.REMEMBER:
                    answer = (
                        "Não consegui processar este pedido de memória neste momento. "
                        "Tenta novamente daqui a pouco."
                    )
                    route = "MEMORY1_REMEMBER_MODEL_FAILURE_FAIL_CLOSED"
                else:
                    answer = "Não percebi bem o pedido. Podes reformular?"
                    route = "MEMORY1_INTERPRETATION_FAIL_CLOSED"
                events.emit(
                    "MEMORY1_RUNTIME_INTERPRETATION_MODEL_FAILURE",
                    source=source,
                    error_type=type(exc).__name__,
                )
                events.emit(
                    "MEMORY1_RUNTIME_INTERPRETATION_FAIL_CLOSED_RESPONSE",
                    source=source,
                    interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE.value,
                    selected_operation=(
                        selected_operation.value if selected_operation is not None else None
                    ),
                    route=route,
                )
                elapsed = round((monotonic() - command_started) * 1000)
                performance.record_request(elapsed_ms=elapsed, route=route)
                return ProcessRequestResult(
                    answer=answer,
                    route=route,
                    elapsed_ms=elapsed,
                    hybrid=None,
                )

        except MemoryModelContractError as exc:
            memory1_turn_result = MemoryTurnResult(
                operation=None,
                interpretation_status=MemoryInterpretationStatus.SCHEMA_INVALID,
            )
            memory1_grounding_context = (
                build_memory1_interpretation_fail_closed_context(memory1_turn_result)
            )
            events.emit(
                "MEMORY1_RUNTIME_INTERPRETATION_SCHEMA_INVALID",
                source=source,
                error_type=type(exc).__name__,
            )
            # selected_operation is request-local control metadata only.
            if exc.selected_operation is MemoryOperation.REMEMBER:
                # Preserve the already-frozen REMEMBER response verbatim.
                answer = (
                    "Não consegui validar este pedido de memória, "
                    "por isso não guardei nada. Reformula e tento "
                    "novamente."
                )
                route = "MEMORY1_REMEMBER_SCHEMA_INVALID_FAIL_CLOSED"
                events.emit(
                    "MEMORY1_RUNTIME_REMEMBER_SCHEMA_INVALID_FAIL_CLOSED",
                    source=source,
                    error_type=type(exc).__name__,
                )
            elif exc.selected_operation is MemoryOperation.RECALL:
                answer = (
                    "Não consegui validar este pedido de memória com segurança, "
                    "por isso não posso confirmar nem negar o que está guardado. "
                    "Reformula e tento novamente."
                )
                route = "MEMORY1_RECALL_SCHEMA_INVALID_FAIL_CLOSED"
            else:
                answer = "Não percebi bem o pedido. Podes reformular?"
                route = "MEMORY1_INTERPRETATION_FAIL_CLOSED"
            events.emit(
                "MEMORY1_RUNTIME_INTERPRETATION_FAIL_CLOSED_RESPONSE",
                source=source,
                interpretation_status=MemoryInterpretationStatus.SCHEMA_INVALID.value,
                selected_operation=(
                    exc.selected_operation.value
                    if exc.selected_operation is not None else None
                ),
                route=route,
            )
            elapsed = round((monotonic() - command_started) * 1000)
            performance.record_request(elapsed_ms=elapsed, route=route)
            return ProcessRequestResult(
                answer=answer,
                route=route,
                elapsed_ms=elapsed,
                hybrid=None,
            )

        except Exception as exc:
            if isinstance(exc, MemoryModelInvocationError):
                memory1_turn_result = MemoryTurnResult(
                    operation=None,
                    interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE,
                )
                memory1_grounding_context = (
                    build_memory1_interpretation_fail_closed_context(memory1_turn_result)
                )
                if exc.selected_operation is MemoryOperation.RECALL:
                    answer = (
                        "Não consegui consultar a memória neste momento. "
                        "Tenta novamente daqui a pouco."
                    )
                    route = "MEMORY1_RECALL_MODEL_FAILURE_FAIL_CLOSED"
                elif exc.selected_operation is MemoryOperation.REMEMBER:
                    answer = (
                        "Não consegui processar este pedido de memória neste momento. "
                        "Tenta novamente daqui a pouco."
                    )
                    route = "MEMORY1_REMEMBER_MODEL_FAILURE_FAIL_CLOSED"
                else:
                    answer = "Não percebi bem o pedido. Podes reformular?"
                    route = "MEMORY1_INTERPRETATION_FAIL_CLOSED"
                events.emit(
                    "MEMORY1_RUNTIME_INTERPRETATION_MODEL_FAILURE",
                    source=source,
                    error_type=type(exc).__name__,
                )
                events.emit(
                    "MEMORY1_RUNTIME_INTERPRETATION_FAIL_CLOSED_RESPONSE",
                    source=source,
                    interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE.value,
                    selected_operation=(
                        exc.selected_operation.value
                        if exc.selected_operation is not None else None
                    ),
                    route=route,
                )
                elapsed = round((monotonic() - command_started) * 1000)
                performance.record_request(elapsed_ms=elapsed, route=route)
                return ProcessRequestResult(
                    answer=answer,
                    route=route,
                    elapsed_ms=elapsed,
                    hybrid=None,
                )
            events.emit(
                "MEMORY1_RUNTIME_ERROR",
                source=source,
                error=(f"{type(exc).__name__}: {exc}"),
            )
            raise

        if memory1_deterministic_remember_response is not None:
            answer = memory1_deterministic_remember_response
            route = "MEMORY1/REMEMBER"
            hybrid = None

            events.emit(
                "MEMORY1_RUNTIME_RECEIPT_RESPONSE",
                outcome=(
                    memory1_turn_result.remember.outcome.value
                ),
            )

        else:
            answer, route, hybrid = route_runtime_request(
                user_text,
                source=source,
                semantic_context_inputs=(
                    semantic_context_inputs
                ),
                events=events,
                fast_router=fast_router,
                hybrid_brain=hybrid_brain,
                memory_grounding_context=(
                    memory1_grounding_context
                ),
                requires_memory_aware_response=(
                    memory1_requires_memory_aware_response
                ),
            )

        elapsed = round(
            (monotonic() - command_started)
            * 1000
        )



        if hybrid is None:
            if settings.persistent_context_enabled:
                persistent_context.record(
                    user_text,
                    answer,
                    route,
                )

            _memory_observation_result = cognition.observe_interaction(
                user_text,
                answer,
                route,
            )

            # MEMORY_RUNTIME_COGNITION_REFRESH_V1
            try:
                from jarvis_core.services.memory_maintenance import refresh_after_personal_cognition
                refresh_after_personal_cognition(_memory_observation_result)
            except Exception:
                pass

            try:
                relational_presence_store.observe_exchange(
                    user_text,
                    answer,
                )
            except Exception as exc:
                events.emit(
                    "RELATIONAL_PRESENCE_EXCHANGE_OBSERVE_ERROR",
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    route=route,
                )

            try:
                self_engine.observe_outcome(
                    owner_text=user_text,
                    assistant_text=answer,
                    route=route,
                    success=True,
                )
            except Exception as exc:
                events.emit(
                    "SYNTHETIC_SELF_OUTCOME_OBSERVE_ERROR",
                    error=(
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                )

            performance.record_request(
                elapsed_ms=elapsed,
                route=route,
            )

            return ProcessRequestResult(
                answer=answer,
                route=route,
                elapsed_ms=elapsed,
                hybrid=None,
            )

        if settings.persistent_context_enabled:
            persistent_context.record(
                user_text,
                hybrid.text,
                hybrid.route,
            )

        _memory_observation_result = cognition.observe_interaction(
            user_text,
            hybrid.text,
            hybrid.route,
        )

        # MEMORY_RUNTIME_COGNITION_REFRESH_V1
        try:
            from jarvis_core.services.memory_maintenance import refresh_after_personal_cognition
            refresh_after_personal_cognition(_memory_observation_result)
        except Exception:
            pass

        try:
            relational_presence_store.observe_exchange(
                user_text,
                hybrid.text,
            )
        except Exception as exc:
            events.emit(
                "RELATIONAL_PRESENCE_EXCHANGE_OBSERVE_ERROR",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                route=hybrid.route,
            )

        try:
            self_engine.observe_outcome(
                owner_text=user_text,
                assistant_text=hybrid.text,
                route=hybrid.route,
                success=bool(
                    str(
                        hybrid.text
                        or ""
                    ).strip()
                ),
            )
        except Exception as exc:
            events.emit(
                "SYNTHETIC_SELF_OUTCOME_OBSERVE_ERROR",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

        if hybrid.route.startswith("RESEARCH"):
            performance.record_request(
                elapsed_ms=elapsed,
                route=hybrid.route,
            )

        return ProcessRequestResult(
            answer=hybrid.text,
            route=hybrid.route,
            elapsed_ms=elapsed,
            hybrid=hybrid,
        )
