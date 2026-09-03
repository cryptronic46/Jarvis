import unittest
from jarvis_core.security.policy import SecurityPolicy, RiskLevel

class SecurityTests(unittest.TestCase):
    def test_pending_confirmation(self):
        s = SecurityPolicy()
        s.register("close_application", RiskLevel.CONFIRM, "close")
        p = s.request_confirmation("close_application", {"app_name":"discord"}, "close")
        self.assertEqual(p.tool_name, "close_application")
        self.assertEqual(len(s.pending()), 1)
        popped = s.pop_pending(p.token)
        self.assertIsNotNone(popped)
        self.assertEqual(len(s.pending()), 0)

if __name__ == "__main__":
    unittest.main()
