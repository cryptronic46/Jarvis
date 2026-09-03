import json
import unittest
from jarvis_core.core.fast_router import FastCommandRouter


class DummyEvents:
    def emit(self, *args, **kwargs):
        pass


class DummyApps:
    def list_apps(self):
        return []


class DummyTools:
    request_started_at = None
    def execute(self, name, args):
        if name != "run_security_audit":
            return json.dumps({"ok": False})
        return json.dumps({
            "ok": True,
            "summary": {
                "current_user": "PC\\Tiago",
                "current_user_admin": True,
                "only_current_enabled_admin_detected": True,
                "other_admin_count": 0,
                "other_session_count": 0,
                "remote_interactive_session_count": 0,
                "smb_session_count": 0,
                "remote_access_software_count": 0,
                "active_remote_access_detected": False,
            },
        })


class SecurityFastRouteTests(unittest.TestCase):
    def test_connected_question_routes_to_security_audit(self):
        router = FastCommandRouter(DummyEvents(), DummyTools(), DummyApps())
        result = router.dispatch("Jarvis, há alguém ligado ao meu PC?")
        self.assertTrue(result.handled)
        self.assertEqual(result.tool, "run_security_audit")
        self.assertIn("único administrador", result.response)
        self.assertIn("Não encontrei outra sessão", result.response)

    def test_network_analysis_routes_locally(self):
        router = FastCommandRouter(DummyEvents(), DummyTools(), DummyApps())
        result = router.dispatch("Analisa a minha rede.")
        self.assertTrue(result.handled)
        self.assertEqual(result.route, "security_audit")


if __name__ == "__main__":
    unittest.main()
