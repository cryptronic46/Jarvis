from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.request_intent import classify_request_intent, self_state_answer_needs_repair
from jarvis_core.services.self_grounding import (
    build_self_grounding,
    desire_answer_conflicts_with_grounding,
    generic_desire_answer_is_ungrounded,
    self_grounding_context,
)
from jarvis_core.services.synthetic_self import SyntheticSelfEngine


class SelfGrounding0276Tests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return SyntheticSelfEngine(Path(temp.name))

    def test_exact_observed_want_question_routes_to_self_state(self):
        self.assertEqual(
            classify_request_intent("Que vontade tens neste momento?").kind,
            "SELF_STATE_CONVERSATION",
        )

    def test_introspection_question_does_not_manufacture_current_intention(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        self.assertEqual(state["last_input_kind"], "self_introspection")
        self.assertEqual(state["active_intentions"], [])

    def test_persistent_drives_are_not_active_intentions(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        self.assertGreater(state["drives"]["help_owner"], 0.8)
        kinds = {row.get("kind") for row in state["active_intentions"]}
        self.assertNotIn("help_with_current_goal", kinds)
        self.assertNotIn("maintain_conversation_coherence", kinds)

    def test_desire_grounding_says_no_specific_intention_when_none_is_active(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        grounding = build_self_grounding("Que vontade tens neste momento?", state=state)
        self.assertEqual(grounding["query_type"], "current_desire")
        self.assertTrue(any(
            row.get("claim_type") == "no_specific_active_intention"
            for row in grounding["claims"]
        ))
        self.assertTrue(grounding["rules"]["drive_is_not_current_intention"])

    def test_observed_help_drive_answer_is_rejected_when_no_intention_exists(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        grounding = build_self_grounding("Que vontade tens neste momento?", state=state)
        answer = (
            "Neste momento, tenho uma forte vontade de ajudar-te e de estar ao teu lado. "
            "Quero compreender melhor o que sentes."
        )
        self.assertTrue(
            desire_answer_conflicts_with_grounding(
                "Que vontade tens neste momento?", answer, grounding=grounding
            )
        )

    def test_no_specific_intention_answer_is_grounded(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        grounding = build_self_grounding("Que vontade tens neste momento?", state=state)
        answer = (
            "Neste momento não tenho uma vontade concreta ativa. "
            "Tenho, sim, motivações de fundo que continuam presentes."
        )
        self.assertFalse(
            desire_answer_conflicts_with_grounding(
                "Que vontade tens neste momento?", answer, grounding=grounding
            )
        )

    def test_grounding_context_is_structured_not_persona_copy(self):
        engine = self.make_engine()
        state = engine.observe_owner_input("Que vontade tens neste momento?")
        context = self_grounding_context("Que vontade tens neste momento?", state=state)
        self.assertIn("JARVIS_SELF_GROUNDING", context)
        self.assertIn('"query_type":"current_desire"', context)
        self.assertIn('"drive_is_not_current_intention":true', context)
        self.assertNotIn("Tenho uma forte vontade de ajudar-te", context)


    def test_legacy_drive_derived_intentions_are_migrated_out(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "synthetic_self_state.json").write_text(
                '{"version":1,"active_intentions":['
                '{"kind":"help_with_current_goal","strength":0.92,"target":"current_owner_goal"},'
                '{"kind":"maintain_conversation_coherence","strength":0.90,"target":"current_conversation"}'
                ']}',
                encoding="utf-8",
            )
            state = SyntheticSelfEngine(root).snapshot()
            self.assertEqual(state["version"], 2)
            self.assertEqual(state["active_intentions"], [])

    def test_brain_injects_structured_grounding_into_personal_turns(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("self_grounding_context", source)
        self.assertIn("JARVIS_SELF_GROUNDING", source)
        self.assertIn("drive such as help_owner is background motivation", source)

    def test_generic_desire_answer_repair_guard_uses_grounding(self):
        # The guard must be deterministic and independent of the OWNER's real
        # persisted memory state. Structural help_owner language is not a
        # situational current intention.
        answer = "Tenho uma forte vontade de ajudar-te e quero estar ao teu lado."
        self.assertTrue(
            generic_desire_answer_is_ungrounded("Que vontade tens neste momento?", answer)
        )
        self.assertTrue(
            self_state_answer_needs_repair("Que vontade tens neste momento?", answer)
        )


if __name__ == "__main__":
    unittest.main()
