import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings


class Consolidated0278HotfixTests(unittest.TestCase):
    def test_release_and_epistemic_features_are_0278(self):
        init_text = Path('jarvis_core/__init__.py').read_text(encoding='utf-8')
        self.assertIn('__version__ = "0.27.8"', init_text)
        settings = Settings()
        self.assertTrue(settings.epistemic_learning_enabled)
        self.assertTrue(settings.epistemic_learning_rag_enabled)
        self.assertFalse(settings.expert_escalation_enabled)
        self.assertFalse(settings.external_ai_enabled)
        self.assertFalse(settings.cloud_enabled)
        self.assertEqual(settings.local_llm_backend, 'jarvis_local')

    def test_executor_abstraction_and_native_security_fixes_survive_0278(self):
        llm = Path('jarvis_core/core/local_llm.py').read_text(encoding='utf-8')
        native = Path('setup_native_brain.ps1').read_text(encoding='utf-8-sig')
        baseline = Path('repair_security_baseline.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('class JarvisLocalClient', llm)
        self.assertIn('/api/chat', llm)
        self.assertIn("Install-PinnedNativeRuntime 'vulkan'", native)
        self.assertIn('Format-WindowsExitCode', baseline)
        self.assertIn('COMPAT_OK', baseline)
        self.assertNotIn('[uint32]$LlamaCode', baseline)

    def test_appcontrol_is_observe_only_in_current_hotfix(self):
        trust = Path('setup_appcontrol_trust.ps1').read_text(encoding='utf-8-sig')
        self.assertIn('OBSERVE-ONLY', trust)
        self.assertIn('diagnose_app_control.ps1', trust)
        self.assertNotIn('New-CIPolicyRule', trust)
        self.assertNotIn('ConvertFrom-CIPolicy', trust)

    def test_setup_hard_blocks_external_ai(self):
        setup = Path('setup.ps1').read_text(encoding='utf-8-sig')
        cloud_setup = Path('setup_cloud.ps1').read_text(encoding='utf-8-sig')
        self.assertIn("'external_ai_enabled':False", setup)
        self.assertIn("'cloud_enabled':False", setup)
        self.assertIn("'expert_escalation_enabled':False", setup)
        self.assertIn('external ai hard blocked', setup.lower())
        self.assertNotIn("'external_ai_enabled':True", cloud_setup)
        self.assertNotIn("'cloud_enabled':True", cloud_setup)

    def test_settings_migration_forces_external_ai_off_and_preserves_native_trust_choice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'settings.json'
            path.write_text(json.dumps({
                'external_ai_enabled': True,
                'cloud_enabled': True,
                'expert_escalation_enabled': True,
                'local_llm_allow_ollama_compat': False,
            }), encoding='utf-8')
            Settings.ensure_file_schema(path)
            data = json.loads(path.read_text(encoding='utf-8'))
            self.assertFalse(data['external_ai_enabled'])
            self.assertFalse(data['cloud_enabled'])
            self.assertFalse(data['expert_escalation_enabled'])
            self.assertFalse(data['local_llm_allow_ollama_compat'])

    def test_block_audit_requires_current_corroboration(self):
        audit = Path('jarvis_core/services/windows_block_audit.py').read_text(encoding='utf-8')
        self.assertIn('current_block_corroborated', audit)
        self.assertIn('historical_uncorroborated', audit)
        self.assertIn('_probe_native_llama_binary', audit)

    def test_conversation_recall_and_self_grounding_are_retained(self):
        brain = Path('jarvis_core/core/brain.py').read_text(encoding='utf-8')
        self.assertIn('CONVERSATION_RECALL_EVIDENCE', brain)
        self.assertIn('Another AI/LLM is structurally prohibited', brain)
        self.assertIn('SELF_STATE_CONVERSATION', brain)

    def test_manifest_scope_contains_appcontrol_and_0278_audit(self):
        manifest = json.loads(Path('release_manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['release'], '0.27.8')
        self.assertIn('setup_appcontrol_trust.ps1', manifest['scope']['top_level'])
        self.assertIn('AUDIT_0.27.8.md', manifest['scope']['top_level'])


if __name__ == '__main__':
    unittest.main()
