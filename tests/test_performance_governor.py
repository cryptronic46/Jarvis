import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from jarvis_core.core.brain import JarvisBrain
from jarvis_core.core.config import Settings
from jarvis_core.services.performance import PerformanceGovernor


class Events:
    def emit(self, *args, **kwargs):
        pass


class Telemetry:
    def __init__(self, sample=None):
        self.sample = sample or {
            "cpu_percent": 10.0,
            "memory_percent": 30.0,
            "gpu": [{
                "utilization_percent": 10.0,
                "memory_used_mib": 1000,
                "memory_total_mib": 12000,
            }],
        }

    def latest(self):
        return dict(self.sample)


class PerformanceGovernorTests(unittest.TestCase):
    def make_governor(self, sample=None):
        tmp = tempfile.TemporaryDirectory()
        governor = PerformanceGovernor(
            Settings(),
            Events(),
            Telemetry(sample),
            state_path=Path(tmp.name) / "perf.json",
        )
        return tmp, governor

    def test_brain_compaction_uses_prompt_budget_not_runtime_context(self):
        class CapturingEvents:
            def __init__(self):
                self.rows = []

            def emit(
                self,
                name,
                **payload,
            ):
                self.rows.append(
                    (
                        name,
                        dict(payload),
                    )
                )

        brain = JarvisBrain.__new__(
            JarvisBrain
        )

        brain.settings = SimpleNamespace(
            llm_num_ctx=8192,
        )

        brain.events = CapturingEvents()

        old_history = (
            "OLD_HISTORY_MARKER_"
            + ("x" * 14000)
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "BASE_SYSTEM_CONTRACT"
                ),
            },
            {
                "role": "user",
                "content": old_history,
            },
            {
                "role": "assistant",
                "content": (
                    "old assistant reply"
                ),
            },
            {
                "role": "user",
                "content": (
                    "CURRENT_OWNER_TURN"
                ),
            },
        ]

        brain._request_messages = (
            lambda *args, **kwargs:
                list(messages)
        )

        # Deliberately make the legacy num_ctx look like the
        # full runtime capacity. If the Brain incorrectly uses
        # it, this request will not be compacted.
        plan = SimpleNamespace(
            prompt_budget_ctx=2048,
            num_ctx=8192,
        )

        bounded = (
            JarvisBrain
            ._bounded_request_messages(
                brain,
                plan,
            )
        )

        rendered = str(bounded)

        self.assertNotIn(
            "OLD_HISTORY_MARKER_",
            rendered,
        )

        self.assertIn(
            "BASE_SYSTEM_CONTRACT",
            rendered,
        )

        self.assertIn(
            "CURRENT_OWNER_TURN",
            rendered,
        )

        compacted = [
            payload
            for name, payload
            in brain.events.rows
            if name
            == "PROMPT_BUDGET_COMPACTED"
        ]

        self.assertEqual(
            len(compacted),
            1,
        )

        self.assertEqual(
            compacted[0][
                "target_chars"
            ],
            12000,
        )

    def test_plan_separates_runtime_context_from_prompt_budget(self):
        tmp, governor = self.make_governor()
        try:
            plan = governor.plan(
                "Quem ? Alan Turing?"
            )

            self.assertEqual(
                plan.runtime_ctx,
                int(
                    governor.settings.llm_num_ctx
                ),
            )

            self.assertEqual(
                plan.prompt_budget_ctx,
                plan.num_ctx,
            )

            self.assertLess(
                plan.prompt_budget_ctx,
                plan.runtime_ctx,
            )

            data = plan.to_dict()

            self.assertEqual(
                data["runtime_ctx"],
                int(
                    governor.settings.llm_num_ctx
                ),
            )

            self.assertEqual(
                data["prompt_budget_ctx"],
                plan.num_ctx,
            )

            self.assertEqual(
                data["context_contract"],
                (
                    "fixed_runtime_ctx_with_"
                    "request_prompt_budget"
                ),
            )
        finally:
            tmp.cleanup()

    def test_simple_query_is_fast_when_idle(self):
        tmp, governor = self.make_governor()
        try:
            plan = governor.plan("Quem é Alan Turing?")
            self.assertEqual(plan.profile, "fast")
            self.assertFalse(plan.think)
            self.assertLessEqual(plan.num_ctx, 4096)
        finally:
            tmp.cleanup()

    def test_complex_query_is_deep_when_idle(self):
        tmp, governor = self.make_governor()
        try:
            plan = governor.plan(
                "Faz uma análise profunda desta arquitetura complexa."
            )
            self.assertEqual(plan.profile, "deep")
            self.assertTrue(plan.think)
        finally:
            tmp.cleanup()

    def test_high_pressure_uses_eco_for_simple_query(self):
        sample = {
            "cpu_percent": 20.0,
            "memory_percent": 40.0,
            "gpu": [{
                "utilization_percent": 92.0,
                "memory_used_mib": 9000,
                "memory_total_mib": 12000,
            }],
        }
        tmp, governor = self.make_governor(sample)
        try:
            plan = governor.plan("Olá Jarvis")
            self.assertEqual(plan.profile, "eco")
            self.assertFalse(plan.think)
        finally:
            tmp.cleanup()

    def test_manual_deep_overrides_auto_pressure_reduction(self):
        sample = {
            "cpu_percent": 90.0,
            "memory_percent": 40.0,
            "gpu": [],
        }
        tmp, governor = self.make_governor(sample)
        try:
            governor.set_mode("deep")
            plan = governor.plan("Olá")
            self.assertEqual(plan.profile, "deep")
            self.assertTrue(plan.think)
        finally:
            tmp.cleanup()

    def test_resource_pressure_never_forces_external_ai(self):
        sample = {
            "cpu_percent": 10.0,
            "memory_percent": 40.0,
            "gpu": [{
                "utilization_percent": 95.0,
                "memory_used_mib": 9500,
                "memory_total_mib": 12000,
            }],
        }
        tmp, governor = self.make_governor(sample)
        try:
            self.assertFalse(governor.should_offload_to_cloud("Conta-me uma curiosidade histórica"))
            self.assertFalse(governor.should_offload_to_cloud("Analisa a segurança do meu PC"))
        finally:
            tmp.cleanup()



if __name__ == "__main__":
    unittest.main()
