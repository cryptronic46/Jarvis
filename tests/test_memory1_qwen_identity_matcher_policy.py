from __future__ import annotations

import unittest

import jarvis_core.memory.qwen_identity_matcher as matcher_module


class Memory1QwenIdentityMatcherPolicyTests(
    unittest.TestCase
):
    def setUp(self):
        self.prompt = matcher_module._SYSTEM_PROMPT

    def test_semantic_labels_are_primary_identity_signal(self):
        self.assertIn(
            "Treat semantic_labels as the primary identity signal.",
            self.prompt,
        )

    def test_semantic_type_is_secondary_corroborating_evidence(self):
        self.assertIn(
            "Treat semantic_type as secondary corroborating evidence",
            self.prompt,
        )

    def test_type_mismatch_alone_cannot_veto_strong_label_match(self):
        self.assertIn(
            "a semantic_type mismatch alone must not reject a "
            "candidate whose semantic_labels are a strong semantic match",
            self.prompt,
        )

    def test_existing_may_survive_semantic_type_wording_difference(self):
        self.assertIn(
            "Choose EXISTING when semantic_labels strongly identify exactly "
            "one existing candidate, even when semantic_type wording differs.",
            self.prompt,
        )

    def test_ambiguous_requires_multiple_plausible_candidates(self):
        self.assertIn(
            "Choose AMBIGUOUS only when two or more distinct candidates remain "
            "comparably plausible after considering semantic_labels",
            self.prompt,
        )

    def test_new_requires_no_plausible_label_match(self):
        self.assertIn(
            "Choose NEW when semantic_labels do not plausibly match any "
            "existing candidate.",
            self.prompt,
        )


if __name__ == "__main__":
    unittest.main()
