from __future__ import annotations

import ast
import inspect
import json
import unittest

import jarvis_core.cli as cli_module
import jarvis_core.memory.model_adapter as adapter_module
from jarvis_core.memory.errors import MemoryAvailabilityError, MemoryValidationError
from jarvis_core.memory.interpreter import (
    MemoryOperation,
    MemoryQueryProposal,
    RecallRetrievalScope,
)
from jarvis_core.memory.model_adapter import (
    MemoryModelAvailabilityError,
    MemoryModelContractError,
    MemoryModelInvocationError,
    _compose_recall_interpretation,
    _compose_validated_recall_interpretation,
    _recall_structural_retry_prompt,
    memory_recall_extraction_json_schema,
    trusted_memory_recall_extractor_system_prompt,
)
from jarvis_core.memory.qwen_model import memory_interpretation_json_schema


class Memory1E4SRecallScopeRetryAuthorityTests(unittest.TestCase):
    def test_retrieval_scope_enum_is_closed(self):
        self.assertEqual(
            {item.value for item in RecallRetrievalScope},
            {"SELECTOR_SCOPED", "FULL_SUBJECT_PROFILE"},
        )

    def test_selector_scoped_requires_a_selector(self):
        with self.assertRaisesRegex(MemoryValidationError, "requires at least one selector"):
            MemoryQueryProposal(
                subject_refs=("owner",),
                retrieval_scope=RecallRetrievalScope.SELECTOR_SCOPED,
            )

    def test_full_subject_profile_allows_empty_selectors(self):
        query = MemoryQueryProposal(
            subject_refs=("owner",),
            retrieval_scope=RecallRetrievalScope.FULL_SUBJECT_PROFILE,
        )
        self.assertIs(query.retrieval_scope, RecallRetrievalScope.FULL_SUBJECT_PROFILE)

    def test_two_stage_schema_requires_retrieval_scope(self):
        query = memory_recall_extraction_json_schema()["properties"]["query"]
        self.assertIn("retrieval_scope", query["properties"])
        self.assertIn("retrieval_scope", query["required"])
        self.assertEqual(
            set(query["properties"]["retrieval_scope"]["enum"]),
            {"SELECTOR_SCOPED", "FULL_SUBJECT_PROFILE"},
        )

    def test_monolithic_schema_keeps_recall_query_parity(self):
        two_stage = memory_recall_extraction_json_schema()["properties"]["query"]
        schema = memory_interpretation_json_schema()
        recall_branch = schema["oneOf"][2]
        monolithic = recall_branch["properties"]["query"]
        self.assertEqual(set(two_stage["properties"]), set(monolithic["properties"]))
        self.assertIn("retrieval_scope", monolithic.get("required", []))

    def test_recall_prompt_declares_scope_contract(self):
        prompt = trusted_memory_recall_extractor_system_prompt()
        self.assertIn("retrieval_scope=SELECTOR_SCOPED", prompt)
        self.assertIn("retrieval_scope=FULL_SUBJECT_PROFILE", prompt)
        self.assertIn("Never use FULL_SUBJECT_PROFILE merely", prompt)

    def test_stage2_boundary_rejects_missing_scope(self):
        raw = json.dumps({
            "query": {"subject_refs": ["owner"], "temporal_mode": "CURRENT"},
            "needs_confirmation": False,
            "ambiguities": [],
        })
        with self.assertRaises(MemoryModelContractError) as captured:
            _compose_recall_interpretation(raw, confidence=1.0)
        self.assertIsInstance(captured.exception.__cause__, MemoryValidationError)
        self.assertIn("requires retrieval_scope", str(captured.exception.__cause__))

    def test_validated_composer_binds_recall_on_failure(self):
        raw = json.dumps({
            "query": {
                "subject_refs": ["owner"],
                "retrieval_scope": "SELECTOR_SCOPED",
                "temporal_mode": "CURRENT",
            }
        })
        with self.assertRaises(MemoryModelContractError) as captured:
            _compose_validated_recall_interpretation(raw, confidence=1.0)
        self.assertIs(captured.exception.selected_operation, MemoryOperation.RECALL)

    def test_retry_prompt_is_complete_regeneration_only(self):
        prompt = _recall_structural_retry_prompt(
            "BASE", validation_reason="RECALL query requires retrieval_scope"
        )
        self.assertIn("Regenerate the complete Stage-2 payload", prompt)
        self.assertIn("do not reuse, prune, patch or locally repair", prompt)
        self.assertIn("Do not invent revision 0", prompt)

    def test_invocation_error_carries_request_local_operation(self):
        exc = MemoryModelInvocationError(
            "failure", selected_operation=MemoryOperation.RECALL
        )
        self.assertIs(exc.selected_operation, MemoryOperation.RECALL)

    def test_availability_error_keeps_category_and_operation(self):
        exc = MemoryModelAvailabilityError(
            "unavailable", selected_operation=MemoryOperation.RECALL
        )
        self.assertIsInstance(exc, MemoryAvailabilityError)
        self.assertIs(exc.selected_operation, MemoryOperation.RECALL)

    def test_recall_runtime_has_only_one_retry_call_site(self):
        source = inspect.getsource(adapter_module)
        self.assertEqual(source.count("_recall_structural_retry_prompt("), 2)
        self.assertEqual(source.count("_compose_validated_recall_interpretation("), 3)

    def test_cli_preserves_three_handlers_and_bypasses_free_router(self):
        source = inspect.getsource(cli_module.main)
        tree = ast.parse(source)
        candidates = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            names = [
                handler.type.id
                for handler in node.handlers
                if isinstance(handler.type, ast.Name)
            ]
            if "MemoryAvailabilityError" in names and "MemoryModelContractError" in names:
                candidates.append((node, names))
        self.assertEqual(len(candidates), 1)
        block, names = candidates[0]
        self.assertEqual(
            names,
            ["MemoryAvailabilityError", "MemoryModelContractError", "Exception"],
        )
        availability = ast.unparse(block.handlers[0])
        contract = ast.unparse(block.handlers[1])
        generic = ast.unparse(block.handlers[2])
        self.assertIn("MEMORY1_RECALL_MODEL_FAILURE_FAIL_CLOSED", availability)
        self.assertIn("MEMORY1_RECALL_SCHEMA_INVALID_FAIL_CLOSED", contract)
        self.assertIn("não guardei nada", contract)
        self.assertIn("MemoryModelInvocationError", generic)
        self.assertIn("MEMORY1_RUNTIME_ERROR", generic)
        self.assertTrue(any(isinstance(n, ast.Raise) for n in ast.walk(block.handlers[2])))
        self.assertNotIn("route_runtime_request(", availability)
        self.assertNotIn("route_runtime_request(", contract)


if __name__ == "__main__":
    unittest.main()
