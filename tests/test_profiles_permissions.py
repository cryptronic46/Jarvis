import json
import tempfile
import unittest
from pathlib import Path
from jarvis_core.services.profiles import ProfileManager

class ProfilesPermissionsTests(unittest.TestCase):
    def make(self):
        tmp=tempfile.TemporaryDirectory(); root=Path(tmp.name); default=root/'default.json'
        default.write_text(json.dumps({'active_profile':'owner','profiles':{'owner':{'allowed_tools':['*'],'allowed_routines':['*']},'partner':{'allowed_tools':['get_current_time','run_routine'],'allowed_routines':['night']}}}),encoding='utf-8')
        return tmp, ProfileManager(root/'profiles.json', default)
    def test_owner_allows_every_tool(self):
        tmp,m=self.make()
        try: self.assertTrue(m.tool_allowed('anything'))
        finally: tmp.cleanup()
    def test_partner_is_restricted(self):
        tmp,m=self.make()
        try:
            m.activate('partner'); self.assertTrue(m.tool_allowed('get_current_time')); self.assertFalse(m.tool_allowed('run_security_audit')); self.assertTrue(m.routine_allowed('night')); self.assertFalse(m.routine_allowed('game'))
        finally: tmp.cleanup()
if __name__=='__main__': unittest.main()
