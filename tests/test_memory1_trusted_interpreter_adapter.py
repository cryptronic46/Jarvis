from __future__ import annotations

from dataclasses import (
    FrozenInstanceError,
    fields,
)
from datetime import (
    datetime,
    timezone,
)
import hashlib
import json
from pathlib import Path
import ast
import unittest

from jarvis_core.memory.enums import (
    MEMORY_CONTRACT_VERSION,
)
from jarvis_core.memory.errors import (
    MemoryValidationError,
)
from jarvis_core.memory.interpreter import (
    InterpreterContext,
    MemoryOperation,
)
from jarvis_core.memory.model_adapter import (
    MEMORY_INTERPRETER_CONTRACT_VERSION,
    MEMORY_INTERPRETER_SCHEMA_VERSION,
    MemoryInterpretationAdapterError,
    MemoryInterpretationEnvelope,
    MemoryModelContractError,
    MemoryModelInvocationError,
    TrustedSemanticMemoryAdapter,
    trusted_memory_interpreter_system_prompt,
)



def valid_payload():
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
        output=None,
        error=None,
    ):
        self.output = (
            output
            if output is not None
            else json.dumps(
                valid_payload()
            )
        )

        self.error = error
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

        if self.error is not None:
            raise self.error

        return self.output


class Memory1TrustedInterpreterAdapterTests(
    unittest.TestCase
):

    def fixed_time(
        self,
    ):
        return datetime(
            2026,
            9,
            8,
            16,
            30,
            tzinfo=timezone.utc,
        )

    def test_versions_are_explicit_and_frozen(
        self,
    ):
        self.assertEqual(
            MEMORY_INTERPRETER_SCHEMA_VERSION,
            4,
        )

        self.assertEqual(
            MEMORY_INTERPRETER_CONTRACT_VERSION,
            "1.0",
        )

        self.assertEqual(
            MEMORY_CONTRACT_VERSION,
            "1.0",
        )

    def test_valid_model_output_returns_trusted_envelope(
        self,
    ):
        model = FakeModel()

        adapter = (
            TrustedSemanticMemoryAdapter(
                model,
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        envelope = adapter.interpret(
            "qualquer formula??o natural"
        )

        self.assertIsInstance(
            envelope,
            MemoryInterpretationEnvelope,
        )

        self.assertEqual(
            envelope
            .interpreter_schema_version,
            MEMORY_INTERPRETER_SCHEMA_VERSION,
        )

        self.assertEqual(
            envelope
            .interpreter_contract_version,
            "1.0",
        )

        self.assertEqual(
            envelope
            .memory_contract_version,
            "1.0",
        )

        self.assertEqual(
            envelope.model_id,
            "fake-model",
        )

        self.assertEqual(
            envelope.generated_at,
            self.fixed_time(),
        )

        self.assertEqual(
            envelope
            .interpretation
            .operation,
            MemoryOperation.REMEMBER,
        )

    def test_envelope_is_immutable(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(),
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        envelope = adapter.interpret(
            "texto"
        )

        with self.assertRaises(
            FrozenInstanceError
        ):
            envelope.model_id = (
                "spoofed"
            )

    def test_envelope_does_not_store_raw_user_or_model_text(
        self,
    ):
        names = {
            item.name
            for item
            in fields(
                MemoryInterpretationEnvelope
            )
        }

        self.assertNotIn(
            "user_text",
            names,
        )

        self.assertNotIn(
            "raw_output",
            names,
        )

        self.assertIn(
            "request_sha256",
            names,
        )

        self.assertIn(
            "raw_output_sha256",
            names,
        )

    def test_request_and_output_hashes_are_exact(
        self,
    ):
        text = (
            "informa??o sens?vel de teste"
        )

        raw_output = json.dumps(
            valid_payload(),
            ensure_ascii=False,
        )

        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output=raw_output
                ),
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        envelope = adapter.interpret(
            text
        )

        self.assertEqual(
            envelope.request_sha256,
            hashlib.sha256(
                text.encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

        self.assertEqual(
            envelope.raw_output_sha256,
            hashlib.sha256(
                raw_output.encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    def test_context_and_prompt_hashes_match_actual_model_call(
        self,
    ):
        model = FakeModel()

        adapter = (
            TrustedSemanticMemoryAdapter(
                model,
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        context = InterpreterContext(
            locale="pt-PT",
            default_subject_ref="owner",
            known_entity_refs=('owner',),
        )

        envelope = adapter.interpret(
            "texto",
            context=context,
        )

        call = model.calls[0]

        self.assertEqual(
            envelope.system_prompt_sha256,
            hashlib.sha256(
                call[
                    "system_prompt"
                ].encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

        self.assertEqual(
            envelope.context_sha256,
            hashlib.sha256(
                call[
                    "context_json"
                ].encode(
                    "utf-8"
                )
            ).hexdigest(),
        )

    def test_model_exception_fails_closed(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    error=RuntimeError(
                        "model unavailable"
                    )
                ),
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelInvocationError
        ):
            adapter.interpret(
                "texto"
            )

    def test_invalid_json_fails_closed(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output="{bad-json"
                ),
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ):
            adapter.interpret(
                "texto"
            )

    def test_non_text_model_output_fails_closed(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output={
                        "not": "text"
                    }
                ),
                model_id="fake-model",
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ):
            adapter.interpret(
                "texto"
            )

    def test_model_cannot_spoof_envelope_model_id(
        self,
    ):
        payload = valid_payload()

        payload[
            "model_id"
        ] = "evil-model"

        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output=json.dumps(
                        payload
                    )
                ),
                model_id=(
                    "trusted-model"
                ),
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ):
            adapter.interpret(
                "texto"
            )

    def test_model_cannot_spoof_schema_version(
        self,
    ):
        payload = valid_payload()

        payload[
            "interpreter_schema_version"
        ] = 999

        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output=json.dumps(
                        payload
                    )
                ),
                model_id="trusted-model",
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ):
            adapter.interpret(
                "texto"
            )

    def test_model_cannot_spoof_authority_inside_envelope_flow(
        self,
    ):
        payload = valid_payload()

        payload[
            "facts"
        ][0][
            "authority"
        ] = "OWNER_EXPLICIT"

        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(
                    output=json.dumps(
                        payload
                    )
                ),
                model_id="trusted-model",
                clock=self.fixed_time,
            )
        )

        with self.assertRaises(
            MemoryModelContractError
        ):
            adapter.interpret(
                "texto"
            )

    def test_naive_trusted_clock_fails_closed(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(),
                model_id="trusted-model",
                clock=lambda: datetime(
                    2026,
                    9,
                    8,
                    16,
                    30,
                ),
            )
        )

        with self.assertRaises(
            MemoryInterpretationAdapterError
        ):
            adapter.interpret(
                "texto"
            )

    def test_non_datetime_trusted_clock_fails_closed(
        self,
    ):
        adapter = (
            TrustedSemanticMemoryAdapter(
                FakeModel(),
                model_id="trusted-model",
                clock=lambda: "now",
            )
        )

        with self.assertRaises(
            MemoryInterpretationAdapterError
        ):
            adapter.interpret(
                "texto"
            )

    def test_empty_model_id_is_rejected_by_core(
        self,
    ):
        with self.assertRaises(
            MemoryValidationError
        ):
            TrustedSemanticMemoryAdapter(
                FakeModel(),
                model_id="",
            )

    def test_system_prompt_declares_version_boundary(
        self,
    ):
        prompt = (
            trusted_memory_interpreter_system_prompt()
        )

        self.assertIn(
            'interpreter_schema_version=4',
            prompt,
        )

        self.assertIn(
            "interpreter_contract_version=1.0",
            prompt,
        )

        self.assertIn(
            "memory_contract_version=1.0",
            prompt,
        )

        self.assertIn(
            "trusted Core",
            prompt,
        )

    def test_adapter_has_no_canonical_write_dependency(
        self,
    ):
        source = Path(
            "jarvis_core/memory/model_adapter.py"
        ).read_text(
            encoding="utf-8"
        )

        self.assertNotIn(
            "CanonicalMemoryStore",
            source,
        )

        self.assertNotIn(
            "CanonicalMemoryTransaction",
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

    def test_adapter_has_no_regex_language_parser(
        self,
    ):
        tree = ast.parse(
            Path(
                "jarvis_core/memory/model_adapter.py"
            ).read_text(
                encoding="utf-8"
            )
        )

        imports = set()

        for node in ast.walk(
            tree
        ):
            if isinstance(
                node,
                ast.Import,
            ):
                imports.update(
                    alias.name
                    for alias
                    in node.names
                )

            elif isinstance(
                node,
                ast.ImportFrom,
            ):
                if node.module:
                    imports.add(
                        node.module
                    )

        self.assertNotIn(
            "re",
            imports,
        )

        self.assertNotIn(
            "regex",
            imports,
        )


if __name__ == "__main__":
    unittest.main()
