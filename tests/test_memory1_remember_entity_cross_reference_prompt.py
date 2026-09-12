from __future__ import annotations

import unittest

from jarvis_core.memory.model_adapter import (
    trusted_memory_remember_extractor_system_prompt,
)


class RememberEntityCrossReferencePromptTests(
    unittest.TestCase
):
    def test_prompt_defines_entity_cross_reference_fields(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertIn(
            "Every entities[].local_ref must be referenced by at least ",
            prompt,
        )

        self.assertIn(
            "facts[].subject_ref",
            prompt,
        )

        self.assertIn(
            "facts[].value_entity_ref",
            prompt,
        )

        self.assertIn(
            "relations[].source_ref",
            prompt,
        )

        self.assertIn(
            "relations[].target_ref",
            prompt,
        )

    def test_prompt_requires_empty_entities_when_no_new_entity_is_needed(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertIn(
            (
                "If no genuinely new independently referable "
                "entity is required, return entities as an empty array."
            ),
            prompt,
        )

        self.assertIn(
            (
                "Known references supplied by trusted context "
                "must be reused without redeclaring them as new entities."
            ),
            prompt,
        )

    def test_prompt_contract_is_not_case_specific(
        self,
    ) -> None:
        prompt = (
            trusted_memory_remember_extractor_system_prompt()
        )

        self.assertNotIn(
            "pt-PT",
            prompt,
        )

        self.assertNotIn(
            "language_preference",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
