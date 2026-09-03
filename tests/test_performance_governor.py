import tempfile
import unittest
from pathlib import Path

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
