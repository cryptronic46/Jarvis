import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.core.hybrid_brain import HybridRoutePolicy
from jarvis_core.services.context_store import ContextStore, recall_answer_needs_repair, deterministic_recall_answer
from jarvis_core.services.request_intent import classify_request_intent


class NativeBrain0277Tests(unittest.TestCase):
    def test_defaults_are_native_and_external_ai_off(self):
        s = Settings()
        self.assertEqual(s.local_llm_backend, 'jarvis_local')
        self.assertTrue(s.local_llm_allow_ollama_compat)
        self.assertFalse(s.external_ai_enabled)
        self.assertFalse(s.cloud_enabled)
        self.assertFalse(s.external_ai_auto_escalate_complex)

    def test_brain_does_not_import_ollama_directly(self):
        text = Path('jarvis_core/core/brain.py').read_text(encoding='utf-8')
        self.assertNotIn('from ollama import', text)
        self.assertIn('build_local_client', text)
        req = Path('requirements.txt').read_text(encoding='utf-8')
        self.assertNotIn('ollama==', req.lower())

    def test_setup_uses_native_runtime_not_ollama_command(self):
        setup = Path('setup.ps1').read_text(encoding='utf-8')
        native = Path('setup_native_brain.ps1').read_text(encoding='utf-8')
        self.assertIn('setup_native_brain.ps1', setup)
        self.assertNotIn('ollama pull', setup.lower())
        self.assertIn('llama-server.exe', native)
        self.assertIn('qwen3-8b.gguf', native)
        self.assertIn('Find-OllamaQwenBlob', native)  # migration source
        self.assertIn('bin-win-vulkan-x64.zip', native)
        self.assertIn('Test-OllamaCompatExecutor', native)

    def test_cloud_words_are_hard_blocked(self):
        policy = HybridRoutePolicy(Settings())
        self.assertEqual(policy.decide('/cloud explica isto').route, 'external_ai_blocked')
        self.assertEqual(policy.decide('pergunta ao chatgpt').route, 'external_ai_blocked')
        self.assertFalse(Settings().external_ai_enabled)

    def test_conversation_recall_is_first_class_intent(self):
        for q in ('Recordas-te da nossa conversa de ontem a noite?', 'Falamos sobre o quê?'):
            self.assertEqual(classify_request_intent(q).kind, 'CONVERSATION_RECALL')

    def test_yesterday_recall_is_date_grounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(Path(tmp) / 'context.jsonl')
            now = datetime.now().astimezone()
            yesterday = now - timedelta(days=1)
            rows = [
                {'timestamp': yesterday.replace(hour=19, minute=15).isoformat(timespec='seconds'), 'user':'Falámos ainda durante a tarde.', 'assistant':'Sim.', 'route':'LOCAL'},
                {'timestamp': yesterday.replace(hour=21, minute=15).isoformat(timespec='seconds'), 'user':'Falámos sobre a identidade da Jarvis.', 'assistant':'Sim.', 'route':'LOCAL'},
                {'timestamp': now.replace(hour=8, minute=0).isoformat(timespec='seconds'), 'user':'Bom dia', 'assistant':'Bom dia.', 'route':'LOCAL'},
            ]
            store.path.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n', encoding='utf-8')
            result = store.recall_for_query('Recordas-te da nossa conversa de ontem à noite?')
            self.assertTrue(result['evidence_available'])
            self.assertEqual(len(result['turns']), 1)
            self.assertIn('identidade', result['turns'][0]['user'])
            block = store.recall_prompt_block(result)
            self.assertIn('Only say you remember', block)
            self.assertIn('evidence_available=true', block)

    def test_recall_without_evidence_is_explicitly_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ContextStore(Path(tmp) / 'context.jsonl')
            result = store.recall_for_query('Recordas-te da nossa conversa de ontem à noite?')
            self.assertFalse(result['evidence_available'])
            self.assertIn('evidence_available=false', store.recall_prompt_block(result))

    def test_recall_truth_gate_rejects_false_positive_memory(self):
        result = {'period': 'ontem à noite', 'turns': [], 'evidence_available': False}
        self.assertTrue(recall_answer_needs_repair(
            'Recordas-te da nossa conversa de ontem à noite?',
            'Sim, lembro-me. Foi muito interessante.',
            result,
        ))
        fallback = deterministic_recall_answer(result)
        self.assertIn('Não tenho registo persistente suficiente', fallback)

    def test_recall_followup_rejects_generic_topic_switch(self):
        result = {
            'period': 'ontem à noite',
            'evidence_available': True,
            'turns': [{'user': 'Falámos sobre a identidade da Jarvis.', 'assistant': 'Sim.'}],
        }
        self.assertTrue(recall_answer_needs_repair(
            'Falámos sobre o quê?',
            'Falamos sobre o que quiseres. Como posso ajudar?',
            result,
        ))
        self.assertFalse(recall_answer_needs_repair(
            'Falámos sobre o quê?',
            'Falámos sobre a identidade da Jarvis.',
            result,
        ))

    def test_native_runtime_is_pinned_and_runtime_code_has_no_ollama_import(self):
        native = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        local_llm = Path('jarvis_core/core/local_llm.py').read_text(encoding='utf-8')
        self.assertIn('$LlamaCppTag = "b10516"', native)
        self.assertIn('96d64faeb5b8e655341f32b26ad3e51fbea8bff0bc8120ad3dbffdc0b05b8ad3', native)
        self.assertIn('d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785', native)
        self.assertIn('Assert-Sha256', native)
        self.assertNotIn('from ollama import', local_llm)
        self.assertNotIn('ollama.Client', local_llm)

    def test_optional_vision_setup_does_not_require_ollama(self):
        vision = Path('setup_vision.ps1').read_text(encoding='utf-8-sig').lower()
        self.assertNotIn('ollama pull', vision)
        self.assertNotIn('get-command ollama', vision)

    def test_shutdown_acceptance_checks_state_and_orphan_native_server(self):
        run = Path('run.ps1').read_text(encoding='utf-8-sig')
        accept = Path('acceptance_real_machine.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('Get-Process -Name "llama-server"', run)
        self.assertIn(r'runtime\llama.cpp', run)
        self.assertIn('native_llama_orphan_process', accept)


if __name__ == '__main__':
    unittest.main()
