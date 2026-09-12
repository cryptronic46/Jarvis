from __future__ import annotations

from io import BytesIO
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib import error

from jarvis_core.core.local_llm import (
    LocalLLMAvailabilityError,
    LocalLLMError,
    NativeLlamaClient,
)
from jarvis_core.memory.availability import is_sqlite_availability_error
from jarvis_core.memory.entity_bindings import TrustedEntityBindings
from jarvis_core.memory.entity_resolution import (
    RecallEntityResolution,
    RecallEntityResolutionAction,
)
from jarvis_core.memory.enums import PropertyKind
from jarvis_core.memory.errors import MemoryAvailabilityError
from jarvis_core.memory.interpreter import (
    EntityQueryProposal,
    MemoryInterpretation,
    MemoryOperation,
    MemoryQueryProposal,
    PropertyQueryProposal,
)
from jarvis_core.memory.model_adapter import TrustedTwoStageSemanticMemoryAdapter
from jarvis_core.memory.property_resolution import (
    RecallPropertyResolution,
    RecallPropertyResolutionAction,
)
from jarvis_core.memory.qwen_identity_matcher import QwenSemanticIdentityMatcher
from jarvis_core.memory.qwen_model import (
    JarvisQwenMemoryModel,
    QwenMemoryModelAvailabilityError,
)
from jarvis_core.memory.recall_executor import (
    FactRecallKey,
    RecallAggregateOutcome,
    RecallItemOutcome,
    RelationRecallKey,
    execute_memory_recall_plan,
)
from jarvis_core.memory.recall_grounding import (
    build_memory1_recall_fail_closed_status,
    build_memory1_recall_status,
)
from jarvis_core.memory.resolution import CanonicalIdentityDomain, ModelCandidateView
from jarvis_core.memory.resolution_plan import (
    MemoryResolutionPlan,
    RecallEntityReferenceResolution,
    RecallEntityResolutionFailure,
    RecallEntityRole,
    RecallPropertyQueryResolution,
    RecallPropertyRef,
    RecallPropertyResolutionFailure,
)
import jarvis_core.memory.resolution_plan as resolution_plan_module


def prop(name: str) -> PropertyQueryProposal:
    return PropertyQueryProposal(
        semantic_labels=(name,),
        semantic_type="property",
    )


def owner_row():
    return RecallEntityReferenceResolution(
        local_ref="owner",
        query=None,
        resolution=RecallEntityResolution(
            action=RecallEntityResolutionAction.EXISTING,
            confidence=1.0,
            canonical_id="owner-id",
        ),
        trusted_binding=True,
    )


def property_row(query, *, action, canonical_id=None, kind=PropertyKind.FACT):
    return RecallPropertyQueryResolution(
        kind=kind,
        query=query,
        resolution=RecallPropertyResolution(
            kind=kind,
            action=action,
            confidence=1.0,
            canonical_id=canonical_id,
        ),
    )


class FakeStore:
    def __init__(self):
        self.calls = []
        self.fact_rows = {}
        self.relation_rows = {}
        self.fail_read_property = None
        self.fail_assert = False

    def assert_readable(self):
        if self.fail_assert:
            raise MemoryAvailabilityError("down")

    def query_current_facts(self, *, subject_entity_ids, property_ids=None):
        self.calls.append(("fact", subject_entity_ids, property_ids))
        pid = property_ids[0]
        if pid == self.fail_read_property:
            raise MemoryAvailabilityError("read down")
        return tuple(self.fact_rows.get(pid, ()))

    query_historical_facts = query_current_facts

    def query_facts_as_of_revision(self, *, revision, subject_entity_ids, property_ids=None):
        return self.query_current_facts(
            subject_entity_ids=subject_entity_ids,
            property_ids=property_ids,
        )

    def query_current_relations(self, *, source_entity_ids, property_ids=None):
        self.calls.append(("relation", source_entity_ids, property_ids))
        pid = property_ids[0]
        if pid == self.fail_read_property:
            raise MemoryAvailabilityError("read down")
        return tuple(self.relation_rows.get(pid, ()))

    query_historical_relations = query_current_relations

    def query_relations_as_of_revision(self, *, revision, source_entity_ids, property_ids=None):
        return self.query_current_relations(
            source_entity_ids=source_entity_ids,
            property_ids=property_ids,
        )


def fact_obj(pid: str, value: str):
    return SimpleNamespace(
        id="fact-" + pid,
        subject_entity_id="owner-id",
        property_id=pid,
        value=SimpleNamespace(
            value_type="STRING",
            value=value,
            unit=None,
            entity_id=None,
        ),
        memory_class="FACTUAL",
        authority="OWNER_EXPLICIT",
        confidence=1.0,
        valid_from=None,
        valid_until=None,
        recorded_at=None,
    )


class AvailabilityContractTests(unittest.TestCase):
    def test_sqlite_availability_uses_primary_code_not_class_alone(self):
        busy = sqlite3.OperationalError("busy")
        busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
        generic = sqlite3.OperationalError("syntax")
        generic.sqlite_errorcode = sqlite3.SQLITE_ERROR
        self.assertTrue(is_sqlite_availability_error(busy))
        self.assertFalse(is_sqlite_availability_error(generic))

    def test_native_http_503_is_availability(self):
        exc = error.HTTPError(
            "http://127.0.0.1", 503, "down", {}, BytesIO(b"down")
        )
        with patch("jarvis_core.core.local_llm.request.urlopen", side_effect=exc):
            with self.assertRaises(LocalLLMAvailabilityError):
                NativeLlamaClient._json("http://127.0.0.1", {})

    def test_native_http_400_is_not_availability(self):
        exc = error.HTTPError(
            "http://127.0.0.1", 400, "bad", {}, BytesIO(b"bad")
        )
        with patch("jarvis_core.core.local_llm.request.urlopen", side_effect=exc):
            with self.assertRaises(LocalLLMError) as ctx:
                NativeLlamaClient._json("http://127.0.0.1", {})
        self.assertNotIsInstance(ctx.exception, LocalLLMAvailabilityError)

    def test_native_urlerror_is_availability(self):
        with patch(
            "jarvis_core.core.local_llm.request.urlopen",
            side_effect=error.URLError(ConnectionRefusedError()),
        ):
            with self.assertRaises(LocalLLMAvailabilityError):
                NativeLlamaClient._json("http://127.0.0.1", {})

    def test_qwen_model_preserves_availability_category(self):
        class Client:
            def chat(self, **kwargs):
                raise LocalLLMAvailabilityError("down")

        model = JarvisQwenMemoryModel(Client(), model="qwen")
        with self.assertRaises(QwenMemoryModelAvailabilityError):
            model.generate_constrained_json(
                system_prompt="system",
                user_text="user",
                context_json="{}",
                schema={"type": "object"},
            )

    def test_matcher_translates_model_availability_to_memory_availability(self):
        class Model:
            def generate_constrained_json(self, **kwargs):
                raise QwenMemoryModelAvailabilityError("down")

        matcher = QwenSemanticIdentityMatcher(Model())
        with self.assertRaises(MemoryAvailabilityError):
            matcher.select_identity(
                domain=CanonicalIdentityDomain.PROPERTY,
                semantic_labels=("language",),
                semantic_type="property",
                candidates=(),
            )

    def test_adapter_translates_model_availability_to_memory_availability(self):
        class Model:
            def generate_constrained_json(self, **kwargs):
                raise QwenMemoryModelAvailabilityError("down")

        adapter = TrustedTwoStageSemanticMemoryAdapter(Model(), model_id="qwen")
        with self.assertRaises(MemoryAvailabilityError):
            adapter._invoke_stage(
                stage="stage1",
                system_prompt="system",
                schema={"type": "object"},
                text="text",
                context_json="{}",
                num_predict=32,
            )


class RecallTypedOutcomeTests(unittest.TestCase):
    def test_available_plus_miss_is_partial_without_broadening(self):
        p1, p2 = prop("language"), prop("color")
        query = MemoryQueryProposal(
            subject_refs=("owner",),
            fact_properties=(p1, p2),
        )
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(owner_row(),),
            recall_fact_properties=(
                property_row(
                    p1,
                    action=RecallPropertyResolutionAction.EXISTING,
                    canonical_id="pid-language",
                ),
                property_row(
                    p2,
                    action=RecallPropertyResolutionAction.MISS,
                ),
            ),
        )
        store = FakeStore()
        store.fact_rows["pid-language"] = (fact_obj("pid-language", "pt-PT"),)
        result = execute_memory_recall_plan(plan, store=store)
        self.assertEqual(result.aggregate, RecallAggregateOutcome.PARTIAL)
        self.assertEqual(
            tuple(item.outcome for item in result.items),
            (RecallItemOutcome.AVAILABLE, RecallItemOutcome.NOT_FOUND),
        )
        self.assertEqual(len(store.calls), 1)

    def test_available_plus_ambiguous_preserves_available_evidence(self):
        p1, p2 = prop("language"), prop("color")
        query = MemoryQueryProposal(
            subject_refs=("owner",),
            fact_properties=(p1, p2),
        )
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(owner_row(),),
            recall_fact_properties=(
                property_row(
                    p1,
                    action=RecallPropertyResolutionAction.EXISTING,
                    canonical_id="pid-language",
                ),
                property_row(
                    p2,
                    action=RecallPropertyResolutionAction.AMBIGUOUS,
                ),
            ),
        )
        store = FakeStore()
        store.fact_rows["pid-language"] = (fact_obj("pid-language", "pt-PT"),)
        result = execute_memory_recall_plan(plan, store=store)
        self.assertEqual(result.aggregate, RecallAggregateOutcome.PARTIAL)
        self.assertEqual(len(result.facts), 1)
        self.assertEqual(len(store.calls), 1)

    def test_relation_shape_gate_does_not_block_fact_branch(self):
        fp = prop("language")
        rp1 = PropertyQueryProposal(("owns",), "relation")
        rp2 = PropertyQueryProposal(("uses",), "relation")
        t1 = EntityQueryProposal("car", ("car",), "vehicle")
        t2 = EntityQueryProposal("laptop", ("laptop",), "device")
        query = MemoryQueryProposal(
            subject_refs=("owner",),
            entity_queries=(t1, t2),
            fact_properties=(fp,),
            relation_properties=(rp1, rp2),
            target_refs=("car", "laptop"),
        )
        def entity(local_ref, cid, q):
            return RecallEntityReferenceResolution(
                local_ref=local_ref,
                query=q,
                resolution=RecallEntityResolution(
                    action=RecallEntityResolutionAction.EXISTING,
                    confidence=1.0,
                    canonical_id=cid,
                ),
                trusted_binding=False,
            )
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(
                owner_row(),
                entity("car", "car-id", t1),
                entity("laptop", "laptop-id", t2),
            ),
            recall_fact_properties=(property_row(
                fp,
                action=RecallPropertyResolutionAction.EXISTING,
                canonical_id="pid-language",
            ),),
            recall_relation_properties=(
                property_row(rp1, kind=PropertyKind.RELATION, action=RecallPropertyResolutionAction.EXISTING, canonical_id="pid-owns"),
                property_row(rp2, kind=PropertyKind.RELATION, action=RecallPropertyResolutionAction.EXISTING, canonical_id="pid-uses"),
            ),
        )
        store = FakeStore()
        store.fact_rows["pid-language"] = (fact_obj("pid-language", "pt-PT"),)
        result = execute_memory_recall_plan(plan, store=store)
        self.assertTrue(result.relation_query_shape_ambiguous)
        self.assertEqual(result.aggregate, RecallAggregateOutcome.PARTIAL)
        self.assertEqual(tuple(call[0] for call in store.calls), ("fact",))

    def test_infrastructure_gate_marks_all_materializable_items_unavailable(self):
        p1, p2 = prop("language"), prop("color")
        query = MemoryQueryProposal(subject_refs=("owner",), fact_properties=(p1, p2))
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(owner_row(),),
            recall_fact_properties=(
                property_row(p1, action=RecallPropertyResolutionAction.MISS),
                property_row(p2, action=RecallPropertyResolutionAction.AMBIGUOUS),
            ),
        )
        store = FakeStore(); store.fail_assert = True
        result = execute_memory_recall_plan(plan, store=store)
        self.assertTrue(result.infrastructure_unavailable)
        self.assertEqual(
            tuple(item.outcome for item in result.items),
            (RecallItemOutcome.UNAVAILABLE, RecallItemOutcome.UNAVAILABLE),
        )
        self.assertEqual(store.calls, [])

    def test_read_failure_isolated_to_one_item(self):
        p1, p2 = prop("language"), prop("color")
        query = MemoryQueryProposal(subject_refs=("owner",), fact_properties=(p1, p2))
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL,
                confidence=1.0,
                explicit_memory_request=False,
                query=query,
            ),
            recall_entities=(owner_row(),),
            recall_fact_properties=(
                property_row(p1, action=RecallPropertyResolutionAction.EXISTING, canonical_id="pid-language"),
                property_row(p2, action=RecallPropertyResolutionAction.EXISTING, canonical_id="pid-color"),
            ),
        )
        store = FakeStore()
        store.fact_rows["pid-language"] = (fact_obj("pid-language", "pt-PT"),)
        store.fail_read_property = "pid-color"
        result = execute_memory_recall_plan(plan, store=store)
        self.assertEqual(
            tuple(item.outcome for item in result.items),
            (RecallItemOutcome.AVAILABLE, RecallItemOutcome.UNAVAILABLE),
        )
        self.assertEqual(result.aggregate, RecallAggregateOutcome.PARTIAL)

    def test_relation_key_preserves_target_dimension(self):
        rp = PropertyQueryProposal(("owns",), "relation")
        t1 = EntityQueryProposal("car", ("car",), "vehicle")
        t2 = EntityQueryProposal("house", ("house",), "place")
        query = MemoryQueryProposal(
            subject_refs=("owner",),
            entity_queries=(t1, t2),
            relation_properties=(rp,),
            target_refs=("car", "house"),
        )
        def er(ref, cid, q):
            return RecallEntityReferenceResolution(
                local_ref=ref, query=q,
                resolution=RecallEntityResolution(
                    action=RecallEntityResolutionAction.EXISTING,
                    confidence=1.0, canonical_id=cid,
                ), trusted_binding=False,
            )
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL, confidence=1.0,
                explicit_memory_request=False, query=query,
            ),
            recall_entities=(owner_row(), er("car", "car-id", t1), er("house", "house-id", t2)),
            recall_relation_properties=(property_row(
                rp, kind=PropertyKind.RELATION,
                action=RecallPropertyResolutionAction.EXISTING,
                canonical_id="pid-owns",
            ),),
        )
        store = FakeStore()
        store.relation_rows["pid-owns"] = (
            SimpleNamespace(id="r-car", source_entity_id="owner-id", property_id="pid-owns", target_entity_id="car-id"),
            SimpleNamespace(id="r-house", source_entity_id="owner-id", property_id="pid-owns", target_entity_id="house-id"),
        )
        result = execute_memory_recall_plan(plan, store=store)
        self.assertEqual(len(result.items), 2)
        self.assertTrue(all(isinstance(item.key, RelationRecallKey) for item in result.items))
        self.assertEqual({item.key.target_ref for item in result.items}, {"car", "house"})

    def test_status_metadata_never_exposes_canonical_ids(self):
        p = prop("language")
        query = MemoryQueryProposal(subject_refs=("owner",), fact_properties=(p,))
        plan = MemoryResolutionPlan(
            interpretation=MemoryInterpretation(
                operation=MemoryOperation.RECALL, confidence=1.0,
                explicit_memory_request=False, query=query,
            ),
            recall_entities=(owner_row(),),
            recall_fact_properties=(property_row(
                p, action=RecallPropertyResolutionAction.MISS,
            ),),
        )
        result = execute_memory_recall_plan(plan, store=FakeStore())
        status = build_memory1_recall_status(result)
        self.assertIn("NOT_FOUND", status.context)
        self.assertNotIn("owner-id", status.context)
        self.assertNotIn("pid-", status.context)


class ResolutionPlanAvailabilityTests(unittest.TestCase):
    def test_property_availability_failure_is_materialized_in_plan(self):
        p = prop("language")
        query = MemoryQueryProposal(subject_refs=("owner",), fact_properties=(p,))
        interpretation = MemoryInterpretation(
            operation=MemoryOperation.RECALL,
            confidence=1.0,
            explicit_memory_request=False,
            query=query,
        )

        class EntityReader:
            def __init__(self, registry): pass
            def validate_existing_recall_entity_contract(self, canonical_id):
                return SimpleNamespace(id=canonical_id)

        class PropertyReader:
            def __init__(self, registry): pass
            def resolve_recall_property_identity(self, *args, **kwargs):
                raise MemoryAvailabilityError("down")

        with (
            patch.object(resolution_plan_module, "CanonicalEntityCatalogReader", EntityReader),
            patch.object(resolution_plan_module, "CanonicalPropertyCatalogReader", PropertyReader),
        ):
            plan = resolution_plan_module.build_memory_resolution_plan(
                interpretation,
                matcher=SimpleNamespace(),
                entity_registry=object(),
                property_registry=object(),
                trusted_entity_bindings=TrustedEntityBindings({"owner": "owner-id"}),
            )

        self.assertEqual(plan.recall_fact_properties, ())
        self.assertEqual(len(plan.recall_property_resolution_failures), 1)
        self.assertEqual(
            plan.recall_property_resolution_failures[0].property_ref,
            RecallPropertyRef.from_query(p),
        )


    def test_fail_closed_status_is_unavailable_without_canonical_ids(self):
        status = build_memory1_recall_fail_closed_status()
        self.assertEqual(
            status.aggregate,
            RecallAggregateOutcome.NONE_AVAILABLE,
        )
        self.assertEqual(status.item_count, 0)
        self.assertIn("turn_outcome=UNAVAILABLE", status.context)
        self.assertNotIn("01a08", status.context)


if __name__ == "__main__":
    unittest.main()
