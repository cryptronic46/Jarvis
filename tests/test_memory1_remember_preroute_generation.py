from __future__ import annotations

import inspect
import unittest

import jarvis_core.cli as cli_module
from jarvis_core.core import brain as brain_module
from jarvis_core.core import hybrid_brain as hybrid_module
from jarvis_core.memory.enums import CommitStatus
from jarvis_core.memory.interpreter import EntityProposal, MemoryInterpretation, MemoryOperation
from jarvis_core.memory.models import MemoryCommitReceipt, utc_now
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    CanonicalIdentityResolution,
    IdentityResolutionAction,
)
from jarvis_core.memory.resolution_plan import (
    MemoryResolutionPlan,
    RememberEntityReferenceResolution,
    remember_plan_has_ambiguous_identity,
)
from jarvis_core.memory.runtime_result import (
    MEMORY1_RUNTIME_REMEMBER_SCOPE,
    MemoryInterpretationStatus,
    MemoryTurnResult,
    RememberTurnOutcome,
    RememberTurnResult,
    build_memory1_remember_response_context,
    build_remember_turn_result,
)


def _receipt(*, status, message_code, fact_ids=("fact-1",)):
    return MemoryCommitReceipt(
        transaction_id="tx-secret",
        status=status,
        episode_ids=(),
        fact_ids=fact_ids,
        relation_ids=(),
        superseded_fact_ids=(),
        superseded_relation_ids=(),
        conflicts_created=(),
        recorded_at=utc_now(),
        canonical_revision=2,
        projection_revision=None,
        message_code=message_code,
    )


class Memory1RememberPreRouteGenerationTests(unittest.TestCase):
    def test_receipt_mapping_distinguishes_committed_and_idempotent(self):
        committed = build_remember_turn_result(
            _receipt(
                status=CommitStatus.COMMITTED,
                message_code="MEMORY_COMMITTED",
            )
        )
        self.assertIs(committed.outcome, RememberTurnOutcome.COMMITTED)

        idempotent = build_remember_turn_result(
            _receipt(
                status=CommitStatus.NO_CHANGE,
                message_code="MEMORY_NO_CHANGE_IDEMPOTENT",
            )
        )
        self.assertIs(
            idempotent.outcome,
            RememberTurnOutcome.NO_CHANGE_IDEMPOTENT,
        )

    def test_remember_response_context_is_hard_empty_and_id_safe(self):
        remember = build_remember_turn_result(
            _receipt(
                status=CommitStatus.COMMITTED,
                message_code="MEMORY_COMMITTED",
                fact_ids=("fact-secret",),
            )
        )
        result = MemoryTurnResult(
            operation=MemoryOperation.REMEMBER,
            interpretation_status=MemoryInterpretationStatus.VALID,
            remember=remember,
        )
        context = build_memory1_remember_response_context(result)
        self.assertIn("JARVIS_MEMORY_GROUNDING_EVIDENCE", context)
        self.assertIn("memory_scope=" + MEMORY1_RUNTIME_REMEMBER_SCOPE, context)
        self.assertIn("evidence_status=empty", context)
        self.assertIn("outcome=COMMITTED", context)
        self.assertNotIn("tx-secret", context)
        self.assertNotIn("fact-secret", context)

    def test_remember_needs_confirmation_context_has_no_success_claim(self):
        result = MemoryTurnResult(
            operation=MemoryOperation.REMEMBER,
            interpretation_status=MemoryInterpretationStatus.NEEDS_CONFIRMATION,
        )
        context = build_memory1_remember_response_context(result)
        self.assertIn("requires clarification", context)
        self.assertNotIn("outcome=COMMITTED", context)

    def test_ambiguous_identity_is_structural_not_message_parsing(self):
        interpretation = MemoryInterpretation(
            operation=MemoryOperation.REMEMBER,
            confidence=1.0,
            explicit_memory_request=True,
            entities=(
                EntityProposal(
                    local_ref="x",
                    canonical_name="example",
                    entity_type="thing",
                ),
            ),
        )
        plan = MemoryResolutionPlan(
            interpretation=interpretation,
            remember_entities=(
                RememberEntityReferenceResolution(
                    local_ref="x",
                    proposal=None,
                    resolution=CanonicalIdentityResolution(
                        domain=CanonicalIdentityDomain.ENTITY,
                        action=IdentityResolutionAction.AMBIGUOUS,
                        confidence=0.5,
                        canonical_id=None,
                    ),
                    trusted_binding=False,
                ),
            ),
        )
        self.assertTrue(remember_plan_has_ambiguous_identity(plan))

    def test_runtime_writes_remember_before_route_and_removes_old_block(self):
        source = inspect.getsource(cli_module.main)
        process = source[source.index("def process_request"):]
        write = process.index("execute_memory_resolution_plan(")
        route = process.index(
            "answer, route, hybrid = route_runtime_request("
        )
        self.assertLess(write, route)
        self.assertNotIn("# MEMORY1_RUNTIME_REMEMBER_WRITE_V1", process)

    def test_runtime_blocks_fast_router_for_recall_and_remember(self):
        source = inspect.getsource(cli_module.main)
        process = source[source.index("def process_request"):]
        start = process.index("memory1_requires_memory_aware_response = (")
        route = process.index("answer, route, hybrid = route_runtime_request(")
        block = process[start:route]
        self.assertIn("MemoryOperation.RECALL", block)
        self.assertIn("MemoryOperation.REMEMBER", block)

    def test_receipt_backed_remember_bypasses_free_generation_before_route(self):
        source = inspect.getsource(cli_module.main)
        process = source[source.index("def process_request"):]

        receipt_response = process.index(
            "build_deterministic_remember_receipt_response("
        )

        bypass = process.index(
            "if memory1_deterministic_remember_response is not None:"
        )

        route = process.index(
            "answer, route, hybrid = route_runtime_request("
        )

        self.assertLess(
            receipt_response,
            bypass,
        )

        self.assertLess(
            bypass,
            route,
        )

        self.assertIn(
            'route = "MEMORY1/REMEMBER"',
            process,
        )

        self.assertIn(
            "hybrid = None",
            process,
        )

        self.assertIn(
            '"MEMORY1_RUNTIME_RECEIPT_RESPONSE"',
            process,
        )

        self.assertNotIn(
            "MEMORY1_RUNTIME_NARRATION_FALLBACK",
            process,
        )

    def test_receipt_templates_are_not_owned_by_route_runtime_request(self):
        source = inspect.getsource(
            cli_module.route_runtime_request
        )

        self.assertNotIn(
            "Guardei isso.",
            source,
        )

        self.assertNotIn(
            "Já tinha isso guardado.",
            source,
        )

        self.assertNotIn(
            "RememberTurnOutcome",
            source,
        )

        self.assertNotIn(
            "MemoryCommitReceipt",
            source,
        )

    def test_route_owner_remains_memory_receipt_agnostic(self):
        source = inspect.getsource(cli_module.route_runtime_request)
        self.assertNotIn("RememberTurnOutcome", source)
        self.assertNotIn("MemoryCommitReceipt", source)
        self.assertNotIn("memory1_turn_result", source)
        self.assertNotIn("receipt", source.lower())

    def test_brain_no_longer_returns_text_for_outer_model_errors(self):
        source = inspect.getsource(brain_module.JarvisBrain._ask_locked)
        tail = source[source.rindex("except LocalLLMError"):]
        self.assertNotIn("Erro do cérebro local JARVIS", tail)
        self.assertNotIn("Falha no cérebro local", tail)
        self.assertGreaterEqual(tail.count("raise"), 2)

    def test_hybrid_answer_is_generation_status_boundary(self):
        source = inspect.getsource(hybrid_module.HybridBrain.ask)
        self.assertIn("GenerationStatus.MODEL_FAILURE", source)
        self.assertIn("generation_status=local_generation_status", source)
        self.assertIn("except LocalLLMError", source)
        self.assertIn("except Exception", source)
        self.assertIn("raise", source)


if __name__ == "__main__":
    unittest.main()
