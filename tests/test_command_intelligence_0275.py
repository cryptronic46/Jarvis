from pathlib import Path
import unittest
from jarvis_core.services.followup_intent import resolve_followup
from jarvis_core.services.request_intent import classify_request_intent

class CommandIntelligence0275Tests(unittest.TestCase):
    def test_capability_question_is_not_followup_acceptance(self):
        turns=[{"user":"Abre o Brave", "assistant":"Brave aberto.", "timestamp":""}]
        r=resolve_followup("O que você pode fazer?", turns)
        self.assertFalse(r.resolved)
        self.assertEqual(r.reason, "capability_question")

    def test_capability_question_classified_as_capability(self):
        r=classify_request_intent("O que você pode fazer?")
        self.assertEqual(r.kind, "KNOWLEDGE_CAPABILITY")

    def test_fast_router_contains_narrow_voice_repair(self):
        text=Path("jarvis_core/core/fast_router.py").read_text(encoding="utf-8")
        self.assertIn('"agrade"', text)
        self.assertIn('voice_app_open_repair', text)
        self.assertIn('capability_query', text)

    def test_shutdown_has_native_runtime_cleanup(self):
        text=Path("run.ps1").read_text(encoding="utf-8")
        self.assertIn('Stop-JarvisNativeBrain', text)
        self.assertIn('native_llama_runtime.json', text)
        self.assertNotIn('ollama ps', text.lower())

if __name__ == "__main__":
    unittest.main()
