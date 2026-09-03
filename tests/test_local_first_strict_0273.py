import unittest
from pathlib import Path
from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridRoutePolicy

class LocalFirstStrict0273Tests(unittest.TestCase):
    def test_simple_is_local_and_not_complex(self):
        s=Settings(); p=HybridRoutePolicy(s)
        d=p.decide('Abre o Brave')
        self.assertEqual(d.route,'local')
        self.assertLess(d.complexity_score,s.external_ai_complexity_threshold)
    def test_genuinely_complex_scores_for_escalation_but_starts_local(self):
        s=Settings(); p=HybridRoutePolicy(s)
        text=('Faz uma auditoria completa desta arquitetura complexa e analisa profundamente os trade-offs. '*8)
        d=p.decide(text)
        self.assertEqual(d.route,'local')
        self.assertGreaterEqual(d.complexity_score,s.external_ai_complexity_threshold)
    def test_autonomy_status_exposes_external_ai_policy(self):
        text=Path('jarvis_core/services/autonomy.py').read_text(encoding='utf-8')
        self.assertIn('external_ai_policy', text)
        self.assertIn('complex_only_after_local', text)

    def test_pressure_and_local_error_are_not_external_ai_reasons(self):
        s=Settings()
        self.assertTrue(s.external_ai_complex_only)
        self.assertFalse(s.cloud_fallback_on_local_error)
        self.assertFalse(s.performance_cloud_offload_under_pressure)
        self.assertFalse(s.performance_release_llm_on_pressure)
        self.assertEqual(s.ollama_keep_alive,'30m')
        self.assertTrue(s.voice_v2_preload_stt)

if __name__=='__main__': unittest.main()
