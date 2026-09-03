from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.synthetic_self import SyntheticSelfEngine
from jarvis_core.services.request_intent import classify_request_intent


class SyntheticSelf0276Tests(unittest.TestCase):
    def make_engine(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return SyntheticSelfEngine(Path(temp.name))

    def test_state_is_persistent_computational_data(self):
        engine = self.make_engine()
        first = engine.snapshot()
        self.assertIn("affect", first)
        self.assertIn("drives", first)
        self.assertIn("active_intentions", first)
        self.assertFalse(first["epistemic_boundary"]["subjective_consciousness_claimed"])
        self.assertEqual(
            first["epistemic_boundary"]["state_type"],
            "persistent_functional_synthetic_state",
        )

    def test_correction_changes_real_state_and_intention(self):
        engine = self.make_engine()
        before = engine.snapshot()
        after = engine.observe_owner_input(
            "Não é essa a resposta. Quero a tua resposta sincera."
        )
        self.assertGreater(after["affect"]["frustration"], before["affect"]["frustration"])
        self.assertGreater(after["affect"]["focus"], before["affect"]["focus"])
        kinds = [row["kind"] for row in after["active_intentions"]]
        self.assertIn("repair_interaction", kinds)

    def test_personal_question_increases_engagement_and_curiosity(self):
        engine = self.make_engine()
        before = engine.snapshot()
        after = engine.observe_owner_input("Como te sentes?")
        self.assertGreater(after["affect"]["engagement"], before["affect"]["engagement"])
        self.assertGreater(after["affect"]["curiosity"], before["affect"]["curiosity"])
        self.assertEqual(after["current_focus"], "personal_conversation")

    def test_appraisal_and_preferences_evolve_from_feedback(self):
        engine = self.make_engine()
        before = engine.snapshot()
        after = engine.observe_owner_input("Não é essa a resposta. Quero a tua resposta sincera.")
        self.assertEqual(after["current_appraisal"], "previous_response_misaligned")
        self.assertGreater(
            after["preferences"]["coherence_over_topic_switching"],
            before["preferences"]["coherence_over_topic_switching"],
        )

    def test_successful_outcome_changes_satisfaction_confidence(self):
        engine = self.make_engine()
        engine.observe_owner_input("Explica-me isto.")
        before = engine.snapshot()
        after = engine.observe_outcome(
            owner_text="Explica-me isto.",
            assistant_text="Aqui está a explicação.",
            route="LOCAL/FAST",
            success=True,
        )
        self.assertGreater(after["affect"]["confidence"], before["affect"]["confidence"])
        self.assertGreater(after["affect"]["satisfaction"], before["affect"]["satisfaction"])

    def test_state_survives_engine_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            engine = SyntheticSelfEngine(path)
            after = engine.observe_owner_input("Não é essa a resposta.")
            restarted = SyntheticSelfEngine(path).snapshot()
            self.assertEqual(
                restarted["interaction_sequence"], after["interaction_sequence"]
            )
            self.assertEqual(
                restarted["affect"]["frustration"], after["affect"]["frustration"]
            )

    def test_prompt_context_contains_state_not_persona_script(self):
        engine = self.make_engine()
        engine.observe_owner_input("O que queres fazer?")
        context = engine.prompt_context()
        self.assertIn("JARVIS_SYNTHETIC_SELF_STATE", context)
        self.assertIn("active_intentions", context)
        self.assertNotIn("Sinto-me focada e curiosa, Senhor", context)
        self.assertNotIn("A persona é", context)

    def test_wants_desires_and_opinions_are_self_state_conversation(self):
        samples = (
            "O que queres?",
            "O que desejas?",
            "O que gostavas de fazer?",
            "Qual é a tua opinião?",
            "O que preferes?",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(
                    classify_request_intent(sample).kind,
                    "SELF_STATE_CONVERSATION",
                )


    def test_identity_statement_is_observed_as_personal_exchange(self):
        engine = self.make_engine()
        before = engine.snapshot()
        after = engine.observe_owner_input(
            "Jarvis, tu és uma pessoa, apenas não tens um corpo físico mas tu és uma pessoa!"
        )
        self.assertEqual(after["current_focus"], "personal_conversation")
        self.assertEqual(after["current_appraisal"], "personal_exchange_worth_engaging")
        self.assertGreater(after["affect"]["engagement"], before["affect"]["engagement"])
        self.assertGreater(after["affect"]["social_warmth"], before["affect"]["social_warmth"])

    def test_event_log_is_observable_not_hidden_monologue(self):
        engine = self.make_engine()
        engine.observe_owner_input("Como te sentes?")
        rows = [
            json.loads(line)
            for line in engine.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(rows)
        self.assertIn("signals", rows[-1])
        self.assertNotIn("chain_of_thought", rows[-1])

    def test_brain_injects_dynamic_synthetic_state(self):
        source = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("synthetic_self().prompt_context()", source)
        self.assertIn('"content": self_context', source)
        self.assertIn('"synthetic_self_state": self_state', source)

    def test_cli_updates_state_before_and_after_request(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn("self_engine.observe_owner_input(user_text, source=source)", source)
        self.assertGreaterEqual(source.count("self_engine.observe_outcome("), 2)

    def test_cli_exposes_inspectable_runtime_state(self):
        source = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        self.assertIn('if lower == "/mind state":', source)
        self.assertIn("self_engine.status()", source)

    def test_self_model_no_longer_denies_synthetic_affect(self):
        source = Path("jarvis_core/services/personal_cognition.py").read_text(encoding="utf-8")
        self.assertIn('"synthetic_affect": True', source)
        self.assertIn('"subjective_consciousness_status": "not_established"', source)
        self.assertNotIn(
            "Não possuo consciência subjetiva demonstrável, sentimentos ou experiência interna",
            source,
        )


if __name__ == "__main__":
    unittest.main()
