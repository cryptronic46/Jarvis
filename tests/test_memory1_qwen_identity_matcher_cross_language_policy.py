import json
import unittest

import jarvis_core.memory.qwen_identity_matcher as matcher_module
from jarvis_core.memory.qwen_identity_matcher import QwenSemanticIdentityMatcher
from jarvis_core.memory.resolution import (
    CanonicalIdentityDomain,
    ModelCandidateView,
)


class _SpyModel:
    def __init__(self):
        self.calls = []

    def generate_constrained_json(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps(
            {
                "action": "NEW",
                "confidence": 1.0,
                "selected_handle": None,
            }
        )


class Memory1QwenIdentityMatcherCrossLanguagePolicyTests(unittest.TestCase):
    def test_prompt_requires_meaning_not_lexical_overlap(self):
        prompt = matcher_module._SYSTEM_PROMPT
        self.assertIn("Judge semantic_labels by meaning", prompt)
        self.assertIn("Translation across languages", prompt)
        self.assertIn("snake_case", prompt)
        self.assertIn("Do not require shared tokens", prompt)
        self.assertIn(
            "Choose NEW only after genuinely evaluating every provided candidate",
            prompt,
        )

    def test_semantic_type_mismatch_cannot_veto_strong_label_match(self):
        prompt = matcher_module._SYSTEM_PROMPT
        self.assertIn("semantic_type mismatch alone must not reject", prompt)
        self.assertIn("strong semantic equivalent", prompt)
        self.assertIn("different languages", prompt)

    def test_all_candidates_reach_model_context_without_lexical_prefilter(self):
        spy = _SpyModel()
        matcher = QwenSemanticIdentityMatcher(spy)
        candidates = (
            ModelCandidateView(
                domain=CanonicalIdentityDomain.PROPERTY,
                handle="candidate_0000",
                semantic_labels=("preferred_language",),
                semantic_type="property",
            ),
            ModelCandidateView(
                domain=CanonicalIdentityDomain.PROPERTY,
                handle="candidate_0001",
                semantic_labels=("memory_test_code",),
                semantic_type="string",
            ),
        )

        matcher.select_identity(
            domain=CanonicalIdentityDomain.PROPERTY,
            semantic_labels=("código de teste da memória",),
            semantic_type="literal",
            candidates=candidates,
        )

        self.assertEqual(len(spy.calls), 1)
        context = json.loads(spy.calls[0]["context_json"])
        self.assertEqual(
            [row["handle"] for row in context["candidates"]],
            ["candidate_0000", "candidate_0001"],
        )
        self.assertEqual(
            context["candidates"][1]["semantic_labels"],
            ["memory_test_code"],
        )
        self.assertEqual(
            context["semantic_labels"],
            ["código de teste da memória"],
        )


if __name__ == "__main__":
    unittest.main()
