import unittest
from pathlib import Path
class PrivacyCloudGateTests(unittest.TestCase):
    def test_cloud_available_checks_privacy(self):
        t=Path('jarvis_core/core/cloud_brain.py').read_text(encoding='utf-8'); block=t[t.index('def available'):t.index('def status',t.index('def available'))]; self.assertIn('privacy_state().enabled',block); self.assertIn('return False',block)
if __name__=='__main__': unittest.main()
