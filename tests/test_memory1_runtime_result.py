from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import unittest

from jarvis_core.memory.enums import CommitStatus
from jarvis_core.memory.errors import MemoryValidationError
from jarvis_core.memory.interpreter import MemoryOperation
from jarvis_core.memory.models import MemoryCommitReceipt, utc_now
from jarvis_core.memory.recall_executor import RecallAggregateOutcome
from jarvis_core.memory.recall_grounding import Memory1RecallStatus
from jarvis_core.memory.runtime_result import (
    MEMORY1_RUNTIME_FAIL_CLOSED_SCOPE,
    MemoryInterpretationStatus,
    MemoryTurnResult,
    RememberTurnOutcome,
    RememberTurnResult,
    build_deterministic_remember_receipt_response,
    build_memory1_interpretation_fail_closed_context,
    build_memory1_turn_status_context,
)


class Memory1RuntimeResultTests(unittest.TestCase):
    def test_interpretation_status_contract_is_closed(self):
        self.assertEqual(
            [item.value for item in MemoryInterpretationStatus],
            ["VALID", "NEEDS_CONFIRMATION", "SCHEMA_INVALID", "MODEL_FAILURE"],
        )

    def test_memory_turn_result_is_small_frozen_boundary(self):
        self.assertEqual(
            [field.name for field in fields(MemoryTurnResult)],
            ["operation", "interpretation_status", "recall", "remember"],
        )
        result = MemoryTurnResult(
            operation=MemoryOperation.NONE,
            interpretation_status=MemoryInterpretationStatus.VALID,
        )
        with self.assertRaises(FrozenInstanceError):
            result.operation = MemoryOperation.RECALL

    def test_failed_interpretation_cannot_claim_operation(self):
        with self.assertRaises(MemoryValidationError):
            MemoryTurnResult(
                operation=MemoryOperation.RECALL,
                interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE,
            )

    def test_recall_result_requires_recall_operation(self):
        recall = Memory1RecallStatus(
            context="request-local",
            aggregate=RecallAggregateOutcome.NONE_AVAILABLE,
            item_count=0,
            relation_query_shape_ambiguous=False,
            interpretation_uncertain=False,
        )
        with self.assertRaises(MemoryValidationError):
            MemoryTurnResult(
                operation=MemoryOperation.NONE,
                interpretation_status=MemoryInterpretationStatus.VALID,
                recall=recall,
            )

    def test_remember_outcomes_cover_commit_contract_plus_ambiguous(self):
        self.assertEqual(
            {item.value for item in RememberTurnOutcome},
            {
                CommitStatus.COMMITTED.value,
                CommitStatus.REJECTED.value,
                CommitStatus.CONFLICT_REQUIRES_CONFIRMATION.value,
                "NO_CHANGE_IDEMPOTENT",
                "NO_CHANGE_REJECTED",
                "AMBIGUOUS",
            },
        )
        ambiguous = RememberTurnResult(outcome=RememberTurnOutcome.AMBIGUOUS)
        self.assertIsNone(ambiguous.receipt)

    def test_model_failure_context_is_hard_empty_and_not_recall_claim(self):
        result = MemoryTurnResult(
            operation=None,
            interpretation_status=MemoryInterpretationStatus.MODEL_FAILURE,
        )
        context = build_memory1_interpretation_fail_closed_context(result)
        self.assertIn("JARVIS_MEMORY_GROUNDING_EVIDENCE", context)
        self.assertIn("memory_scope=" + MEMORY1_RUNTIME_FAIL_CLOSED_SCOPE, context)
        self.assertIn("evidence_status=unavailable", context)
        self.assertIn("operation=UNDETERMINED", context)
        self.assertIn("interpretation_status=MODEL_FAILURE", context)
        self.assertNotIn("operation=RECALL", context)

    def test_recall_status_is_separate_from_evidence(self):
        recall = Memory1RecallStatus(
            context=(
                "JARVIS_MEMORY_RECALL_STATUS "
                "(request-local metadata; not canonical evidence):\n"
                "aggregate=NONE_AVAILABLE"
            ),
            aggregate=RecallAggregateOutcome.NONE_AVAILABLE,
            item_count=0,
            relation_query_shape_ambiguous=False,
            interpretation_uncertain=False,
        )
        result = MemoryTurnResult(
            operation=MemoryOperation.RECALL,
            interpretation_status=MemoryInterpretationStatus.VALID,
            recall=recall,
        )
        context = build_memory1_turn_status_context(result)
        self.assertIn("JARVIS_MEMORY_TURN_STATUS", context)
        self.assertIn("JARVIS_MEMORY_RECALL_STATUS", context)
        self.assertNotIn("JARVIS_MEMORY_GROUNDING_EVIDENCE", context)


    def test_idempotent_no_change_is_typed_separately_from_rejected_no_change(self):
        receipt = MemoryCommitReceipt(
            transaction_id="request-1",
            status=CommitStatus.NO_CHANGE,
            episode_ids=(),
            fact_ids=("fact-existing",),
            relation_ids=(),
            superseded_fact_ids=(),
            superseded_relation_ids=(),
            conflicts_created=(),
            recorded_at=utc_now(),
            canonical_revision=2,
            projection_revision=None,
            message_code="MEMORY_NO_CHANGE_IDEMPOTENT",
        )
        result = RememberTurnResult(
            outcome=RememberTurnOutcome.NO_CHANGE_IDEMPOTENT,
            receipt=receipt,
        )
        self.assertIs(result.receipt, receipt)

        with self.assertRaises(MemoryValidationError):
            RememberTurnResult(
                outcome=RememberTurnOutcome.NO_CHANGE_REJECTED,
                receipt=receipt,
            )



    def test_deterministic_receipt_response_covers_every_receipt_backed_outcome(self):
        cases = (
            (
                CommitStatus.COMMITTED,
                "MEMORY_COMMITTED",
                RememberTurnOutcome.COMMITTED,
                "Guardei isso.",
            ),
            (
                CommitStatus.REJECTED,
                "MEMORY_REJECTED",
                RememberTurnOutcome.REJECTED,
                "Não guardei isso.",
            ),
            (
                CommitStatus.CONFLICT_REQUIRES_CONFIRMATION,
                "MEMORY_CONFLICT_REQUIRES_CONFIRMATION",
                RememberTurnOutcome.CONFLICT_REQUIRES_CONFIRMATION,
                "Preciso de confirmação antes de guardar isso.",
            ),
            (
                CommitStatus.NO_CHANGE,
                "MEMORY_NO_CHANGE_IDEMPOTENT",
                RememberTurnOutcome.NO_CHANGE_IDEMPOTENT,
                "Já tinha isso guardado.",
            ),
            (
                CommitStatus.NO_CHANGE,
                "MEMORY_NO_CHANGE_REJECTED",
                RememberTurnOutcome.NO_CHANGE_REJECTED,
                "Não alterei a memória.",
            ),
        )

        for (
            status,
            message_code,
            outcome,
            expected,
        ) in cases:
            with self.subTest(
                outcome=outcome.value
            ):
                receipt = MemoryCommitReceipt(
                    transaction_id="tx-response",
                    status=status,
                    episode_ids=(),
                    fact_ids=(),
                    relation_ids=(),
                    superseded_fact_ids=(),
                    superseded_relation_ids=(),
                    conflicts_created=(),
                    recorded_at=utc_now(),
                    canonical_revision=3,
                    projection_revision=None,
                    message_code=message_code,
                )

                result = RememberTurnResult(
                    outcome=outcome,
                    receipt=receipt,
                )

                self.assertEqual(
                    build_deterministic_remember_receipt_response(
                        result
                    ),
                    expected,
                )

    def test_deterministic_receipt_response_rejects_non_receipt_ambiguous_result(self):
        ambiguous = RememberTurnResult(
            outcome=RememberTurnOutcome.AMBIGUOUS
        )

        with self.assertRaises(
            MemoryValidationError
        ):
            build_deterministic_remember_receipt_response(
                ambiguous
            )



if __name__ == "__main__":
    unittest.main()
