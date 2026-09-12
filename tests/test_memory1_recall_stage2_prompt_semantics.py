from __future__ import annotations

import unittest

from jarvis_core.memory.errors import MemoryValidationError
from jarvis_core.memory.interpreter import (
    MemoryQueryProposal,
    QueryTemporalMode,
)
from jarvis_core.memory.model_adapter import (
    trusted_memory_recall_extractor_system_prompt,
)


class RecallStage2PromptSemanticsTests(unittest.TestCase):

    def setUp(self):
        self.prompt = (
            trusted_memory_recall_extractor_system_prompt()
        )

    def test_current_and_default_retrieval_omit_revision(self):
        self.assertIn(
            "For present or default retrieval, use "
            "temporal_mode=CURRENT and omit as_of_revision.",
            self.prompt,
        )

    def test_historical_and_as_of_modes_are_distinguished(self):
        self.assertIn(
            "For historical retrieval without an explicit canonical "
            "revision, use temporal_mode=HISTORICAL and omit "
            "as_of_revision.",
            self.prompt,
        )

        self.assertIn(
            "Use temporal_mode=AS_OF_REVISION only when the request "
            "explicitly specifies a canonical revision",
            self.prompt,
        )

        self.assertIn(
            "revision 0 is valid only when canonical revision 0 is "
            "explicitly requested.",
            self.prompt,
        )

    def test_subject_attributes_are_fact_property_semantics(self):
        self.assertIn(
            "Treat requested attributes, preferences, categories and "
            "literal-valued characteristics of a subject as "
            "fact-property semantics, not as target entities.",
            self.prompt,
        )

        self.assertIn(
            "emit one matching fact_properties object and do not copy "
            "the subject into target_refs.",
            self.prompt,
        )

    def test_target_refs_are_reserved_for_relations(self):
        self.assertIn(
            "Use target_refs only for entities that are semantic "
            "targets of requested relations.",
            self.prompt,
        )

    def test_prompt_contains_no_preferred_language_special_case(self):
        lowered = self.prompt.lower()

        self.assertNotIn(
            "preferred_language",
            lowered,
        )

        self.assertNotIn(
            "idioma preferido",
            lowered,
        )

        self.assertNotIn(
            "pt-pt",
            lowered,
        )

    def test_core_still_rejects_current_with_as_of_revision(self):
        with self.assertRaises(
            MemoryValidationError
        ):
            MemoryQueryProposal(
                subject_refs=("owner",),
                temporal_mode=(
                    QueryTemporalMode.CURRENT
                ),
                as_of_revision=0,
            )


if __name__ == "__main__":
    unittest.main()
