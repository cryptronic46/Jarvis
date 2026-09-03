import unittest
from pathlib import Path
class PersonalOpsToolPermissionsTests(unittest.TestCase):
    def test_registry_has_profile_gate(self):
        t=Path('jarvis_core/core/tool_registry.py').read_text(encoding='utf-8'); self.assertIn('profile_manager().tool_allowed(name)',t); self.assertIn('PROFILE_PERMISSION_DENIED',t)
    def test_sensitive_local_tools_not_cloud_allowlisted(self):
        c=Path('jarvis_core/core/cloud_brain.py').read_text(encoding='utf-8'); s=c[c.index('DEFAULT_ALLOWED_TOOLS = {'):c.index('}',c.index('DEFAULT_ALLOWED_TOOLS = {'))]
        for name in ('read_local_document','search_local_files','run_security_audit','check_security_watch'): self.assertNotIn(f'"{name}"',s)
if __name__=='__main__': unittest.main()
