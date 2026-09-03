import unittest
from pathlib import Path
class RoutineSafetyTests(unittest.TestCase):
    def test_only_safe_actions_are_allowed(self):
        t=Path('jarvis_core/services/routines.py').read_text(encoding='utf-8'); self.assertIn('ALLOWED_ACTIONS = {"open_app", "volume", "mute"}',t); low=t.lower(); self.assertNotIn('powershell.exe',low); self.assertNotIn('subprocess.run',low); self.assertNotIn('os.system',low)
if __name__=='__main__': unittest.main()
