from pathlib import Path
import unittest

class StabilityAutonomyKali0271(unittest.TestCase):
    def test_voice_stack_stays_simple(self):
        t=Path('jarvis_core/services/voice_engine_v2.py').read_text(encoding='utf-8')
        self.assertNotIn('_process_owner_wake_frame', t.split('def _run(self)',1)[1].split('# ------------------------------------------------------------------\n    # Diagnostics',1)[0])
    def test_fast_router_tolerates_abrem(self):
        t=Path('jarvis_core/core/fast_router.py').read_text(encoding='utf-8')
        self.assertIn('"abrem"', t)
    def test_local_first_cloud_escalation_is_gated(self):
        t=Path('jarvis_core/core/hybrid_brain.py').read_text(encoding='utf-8')
        self.assertIn('Local-first: always attempt the local model first', t)
        self.assertIn('capability="cloud_reasoning"', t)
        self.assertIn('_learning_gap_offer', t)
        self.assertIn('studied_knowledge_still_insufficient', t)
        self.assertIn('isolated', t)
    def test_standing_web_research_permission_exists(self):
        t=Path('jarvis_core/services/autonomy.py').read_text(encoding='utf-8')
        self.assertIn('public_web_read_only_research', t)
        self.assertIn('has_standing_public_web_research', t)
    def test_kali_vm_is_visible_and_no_arbitrary_shell(self):
        t=Path('jarvis_core/services/kali_bridge.py').read_text(encoding='utf-8')
        self.assertIn('start_vm', t)
        self.assertIn('"--type", "gui" if self.vm_visible else "headless"', t)
        self.assertIn('open_activity_console', t)
        reg=Path('jarvis_core/core/tool_registry.py').read_text(encoding='utf-8')
        self.assertNotIn('"run_kali_shell"', reg)
        self.assertNotIn('"execute_kali_command"', reg)
    def test_owner_can_authorize_exact_profile_override(self):
        reg=Path('jarvis_core/core/tool_registry.py').read_text(encoding='utf-8')
        aut=Path('jarvis_core/services/autonomy.py').read_text(encoding='utf-8')
        cli=Path('jarvis_core/cli.py').read_text(encoding='utf-8')
        self.assertIn('capability="tool_override"', reg)
        self.assertIn('OWNER_AUTHORIZATION_REQUIRED', reg)
        self.assertIn('bypass_profile_permission', reg)
        self.assertIn('"tool_override"', aut)
        self.assertIn('if action == "execute_tool":', cli)
        self.assertIn('bypass_profile_permission=True', cli)
        self.assertIn('tool.risk == RiskLevel.CRITICAL', reg)
    def test_owner_override_does_not_expand_lab_scope(self):
        t=Path('jarvis_core/services/kali_bridge.py').read_text(encoding='utf-8')
        self.assertIn('TARGET_NOT_AUTHORIZED_LAB', t)
        self.assertIn('KALI_HOST_NOT_AUTHORIZED_LAB', t)

if __name__=='__main__': unittest.main()
