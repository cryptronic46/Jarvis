from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import ast
import json
from pathlib import Path
import unittest

from jarvis_core.memory.enums import (
    Cardinality,
    MemoryClass,
    MemoryNamespace,
    ValueType,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    EntityProposal,
    FactProposal,
    InterpreterContext,
    MemoryInterpretation,
    MemoryOperation,
    QueryTemporalMode,
    SemanticMemoryInterpreter,
    memory_interpreter_system_prompt,
    parse_memory_interpretation,
)



def remember_payload():
    return {
        "operation": "REMEMBER",
        "confidence": 0.99,
        "explicit_memory_request": True,
        "entities": [],
        "fact_properties": [
            {
                "local_ref": "age_property",
                "semantic_labels": ["age"],
                "semantic_type": "age",
                "cardinality": "TEMPORAL_SINGLE",
                "value_type": "INTEGER",
            }
        ],
        "relation_properties": [],
        "facts": [
            {
                "subject_ref": "owner",
                "property_ref": "age_property",
                "value": 38,
                "memory_class": "FACTUAL",
                "confidence": 0.99,
                "raw_representation": "38",
            }
        ],
        "relations": [],
        "query": None,
        "needs_confirmation": False,
        "ambiguities": [],
    }



class FakeModel:
    def __init__(
        self,
        payload,
    ):
        self.payload = payload
        self.calls = []

    def generate_memory_json(
        self,
        *,
        system_prompt,
        user_text,
        context_json,
    ):
        self.calls.append(
            {
                "system_prompt":
                    system_prompt,
                "user_text":
                    user_text,
                "context_json":
                    context_json,
            }
        )

        if isinstance(
            self.payload,
            str,
        ):
            return self.payload

        return json.dumps(
            self.payload,
            ensure_ascii=False,
        )


class Memory1SemanticInterpreterContractTests(
    unittest.TestCase
):


    def test_remember_fact_parses_to_immutable_structure(
        self,
    ):
        result = (
            parse_memory_interpretation(
                json.dumps(
                    remember_payload()
                )
            )
        )

        self.assertEqual(
            result.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            len(
                result.facts
            ),
            1,
        )

        self.assertEqual(
            len(
                result.fact_properties
            ),
            1,
        )

        fact = result.facts[0]

        property_proposal = (
            result.fact_properties[0]
        )

        self.assertEqual(
            fact.property_ref,
            "age_property",
        )

        self.assertEqual(
            property_proposal.local_ref,
            "age_property",
        )

        self.assertEqual(
            property_proposal.semantic_labels,
            (
                "age",
            ),
        )

        self.assertEqual(
            property_proposal.semantic_type,
            "age",
        )

        self.assertEqual(
            property_proposal.value_type,
            ValueType.INTEGER,
        )

        self.assertEqual(
            property_proposal.cardinality,
            Cardinality.TEMPORAL_SINGLE,
        )

        self.assertEqual(
            fact.value,
            38,
        )

        self.assertEqual(
            fact.memory_class,
            MemoryClass.FACTUAL,
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            fact.property_ref = "other"

        with self.assertRaises(
            FrozenInstanceError
        ):
            property_proposal.local_ref = "other"

    def test_entity_proposal_uses_temporary_reference_not_canonical_id(
        self,
    ):
        payload = remember_payload()

        payload[
            "entities"
        ] = [
            {
                "local_ref": "person_1",
                "canonical_name": "Ana",
                "entity_type": "person",
                "namespace_hint": "PERSON",
                "aliases": [],
            }
        ]

        result = (
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )
        )

        entity = (
            result.entities[0]
        )

        self.assertIsInstance(
            entity,
            EntityProposal,
        )

        self.assertEqual(
            entity.local_ref,
            "person_1",
        )

        self.assertEqual(
            entity.namespace_hint,
            MemoryNamespace.PERSON,
        )

    def test_recall_query_is_structured(
        self,
    ):
        payload = {
            "operation": "RECALL",
            "confidence": 0.98,
            "explicit_memory_request": False,
            "entities": [],
            "facts": [],
            "relations": [],
            "query": {'subject_refs': ['owner'], 'fact_properties': [{'semantic_labels': ['age'], 'semantic_type': 'property'}], 'relation_properties': [], 'target_refs': [], 'temporal_mode': 'CURRENT', 'as_of_revision': None},
            "needs_confirmation": False,
            "ambiguities": [],
        }

        result = (
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )
        )

        self.assertEqual(
            result.operation,
            MemoryOperation.RECALL,
        )

        self.assertEqual(
            tuple(label for item in result.query.fact_properties for label in item.semantic_labels),
            (
                "age",
            ),
        )

        self.assertEqual(
            result.query.temporal_mode,
            QueryTemporalMode.CURRENT,
        )

    def test_as_of_revision_contract_is_structural(
        self,
    ):
        payload = {
            "operation": "RECALL",
            "confidence": 1.0,
            "explicit_memory_request": False,
            "entities": [],
            "facts": [],
            "relations": [],
            "query": {'subject_refs': ['owner'], 'fact_properties': [{'semantic_labels': ['age'], 'semantic_type': 'property'}], 'relation_properties': [], 'target_refs': [], 'temporal_mode': 'AS_OF_REVISION', 'as_of_revision': 12},
            "needs_confirmation": False,
            "ambiguities": [],
        }

        result = (
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )
        )

        self.assertEqual(
            result.query.as_of_revision,
            12,
        )

    def test_model_cannot_assign_authority(
        self,
    ):
        payload = remember_payload()

        payload[
            "facts"
        ][0][
            "authority"
        ] = "OWNER_EXPLICIT"

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_model_cannot_assign_source_type(
        self,
    ):
        payload = remember_payload()

        payload[
            "source_type"
        ] = "OWNER_TURN"

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_model_cannot_assign_canonical_ids(
        self,
    ):
        payload = remember_payload()

        payload[
            "entities"
        ] = [
            {
                "local_ref": "person_1",
                "canonical_name": "Ana",
                "entity_type": "person",
                "namespace_hint": "PERSON",
                "aliases": [],
                "id": (
                    "00000000-0000-4000-"
                    "8000-000000000001"
                ),
            }
        ]

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_model_cannot_assign_supersession(
        self,
    ):
        payload = remember_payload()

        payload[
            "facts"
        ][0][
            "supersedes_fact_ids"
        ] = [
            "anything"
        ]

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_model_cannot_assign_permissions_even_nested(
        self,
    ):
        payload = remember_payload()

        payload[
            "facts"
        ][0][
            "value"
        ] = {
            "permissions": [
                "admin"
            ]
        }

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_unknown_root_key_fails_closed(
        self,
    ):
        payload = remember_payload()

        payload[
            "invented_field"
        ] = True

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_invalid_json_fails_closed(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                "{not-json"
            )

    def test_top_level_array_fails_closed(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                "[]"
            )

    def test_remember_without_structured_payload_fails_closed(
        self,
    ):
        payload = {
            "operation": "REMEMBER",
            "confidence": 1.0,
            "explicit_memory_request": True,
            "entities": [],
            "facts": [],
            "relations": [],
            "query": None,
            "needs_confirmation": False,
            "ambiguities": [],
        }

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_recall_without_query_fails_closed(
        self,
    ):
        payload = {
            "operation": "RECALL",
            "confidence": 1.0,
            "explicit_memory_request": False,
            "entities": [],
            "facts": [],
            "relations": [],
            "query": None,
            "needs_confirmation": False,
            "ambiguities": [],
        }

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_none_operation_cannot_smuggle_memory(
        self,
    ):
        payload = remember_payload()

        payload[
            "operation"
        ] = "NONE"

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_confidence_must_be_bounded(
        self,
    ):
        payload = remember_payload()

        payload[
            "confidence"
        ] = 1.5

        with self.assertRaises(
            MemoryValidationError
        ):
            parse_memory_interpretation(
                json.dumps(
                    payload
                )
            )

    def test_interpreter_context_is_frozen_and_requires_aware_time(
        self,
    ):
        context = InterpreterContext(
            current_time=datetime(
                2026,
                9,
                8,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            known_entity_refs=('owner',),
        )

        with self.assertRaises(
            TypeError
        ):
            context.known_entity_refs[
                "other"
            ] = "OTHER"

        with self.assertRaises(
            MemoryValidationError
        ):
            InterpreterContext(
                current_time=datetime(
                    2026,
                    9,
                    8,
                    12,
                    0,
                )
            )

    def test_model_adapter_receives_text_and_context_but_does_not_write(
        self,
    ):
        model = FakeModel(
            remember_payload()
        )

        interpreter = (
            SemanticMemoryInterpreter(
                model
            )
        )

        context = (
            InterpreterContext(
                locale="pt-PT",
                default_subject_ref="owner",
                known_entity_refs=('owner',),
            )
        )

        result = interpreter.interpret(
            "texto arbitr?rio",
            context=context,
        )

        self.assertEqual(
            result.operation,
            MemoryOperation.REMEMBER,
        )

        self.assertEqual(
            len(
                model.calls
            ),
            1,
        )

        call = model.calls[0]

        self.assertEqual(
            call[
                "user_text"
            ],
            "texto arbitr?rio",
        )

        decoded = json.loads(
            call[
                "context_json"
            ]
        )

        self.assertEqual(
            decoded[
                "default_subject_ref"
            ],
            "owner",
        )

    def test_prompt_explicitly_denies_model_authority_and_write_claims(
        self,
    ):
        prompt = (
            memory_interpreter_system_prompt()
            .lower()
        )

        self.assertIn(
            "do not execute actions",
            prompt,
        )

        self.assertIn(
            "do not claim that anything was stored",
            prompt,
        )

        self.assertIn(
            "do not assign authority",
            prompt,
        )

        self.assertIn(
            "trusted core",
            prompt,
        )

    def test_interpreter_module_contains_no_regex_language_parser(
        self,
    ):
        path = Path(
            "jarvis_core/memory/interpreter.py"
        )

        tree = ast.parse(
            path.read_text(
                encoding="utf-8"
            )
        )

        imported_modules = set()

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imported_modules.update(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                if node.module:
                    imported_modules.add(
                        node.module
                    )

        self.assertNotIn(
            "re",
            imported_modules,
        )

        self.assertNotIn(
            "regex",
            imported_modules,
        )

    def test_interpreter_has_no_canonical_store_write_dependency(
        self,
    ):
        source = Path(
            "jarvis_core/memory/interpreter.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "CanonicalMemoryStore",
            source,
        )

        self.assertNotIn(
            "begin_transaction",
            source,
        )

        self.assertNotIn(
            "MemoryCommitReceipt",
            source,
        )


if __name__ == "__main__":
    unittest.main()
