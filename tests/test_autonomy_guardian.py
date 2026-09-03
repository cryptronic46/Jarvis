import tempfile
import unittest
from pathlib import Path

from jarvis_core.core.config import Settings
from jarvis_core.services.autonomy import (
    AutonomyGuardian,
    scope_hash,
)


class Events:
    def emit(self, *args, **kwargs):
        pass


class AutonomyGuardianTests(unittest.TestCase):
    def make_guardian(self):
        tmp = tempfile.TemporaryDirectory()
        guardian = AutonomyGuardian(
            Settings(),
            Events(),
            state_path=Path(tmp.name) / "state.json",
            audit_path=Path(tmp.name) / "audit.jsonl",
        )
        return tmp, guardian

    def test_request_is_not_authorization(self):
        tmp, guardian = self.make_guardian()
        try:
            payload = {
                "query": "noticias de hoje",
                "use_web": True,
            }
            result = guardian.request(
                capability="web_research",
                payload=payload,
                reason="web_required",
                description="pesquisar notícias",
            )
            self.assertTrue(result["pending"])
            self.assertFalse(result["allowed"])
        finally:
            tmp.cleanup()

    def test_authorization_is_exact_scope_and_one_shot(self):
        tmp, guardian = self.make_guardian()
        try:
            payload = {
                "query": "noticias de hoje",
                "use_web": True,
            }
            requested = guardian.request(
                capability="web_research",
                payload=payload,
                reason="web_required",
                description="pesquisar notícias",
            )
            token = requested["token"]

            approved = guardian.authorize(token)
            self.assertTrue(approved["authorized"])

            consumed = guardian.request(
                capability="web_research",
                payload=payload,
                reason="web_required",
                description="pesquisar notícias",
            )
            self.assertTrue(consumed["allowed"])

            second = guardian.request(
                capability="web_research",
                payload=payload,
                reason="web_required",
                description="pesquisar notícias",
            )
            self.assertFalse(second["allowed"])
            self.assertTrue(second["pending"])
        finally:
            tmp.cleanup()

    def test_authorization_cannot_expand_scope(self):
        tmp, guardian = self.make_guardian()
        try:
            approved_payload = {
                "query": "tema A",
                "use_web": True,
            }
            req = guardian.request(
                capability="web_research",
                payload=approved_payload,
                reason="web_required",
                description="pesquisar A",
            )
            guardian.authorize(req["token"])

            broader = guardian.request(
                capability="web_research",
                payload={
                    "query": "tema A e B",
                    "use_web": True,
                },
                reason="web_required",
                description="pesquisar A e B",
            )
            self.assertFalse(
                broader["allowed"]
            )
        finally:
            tmp.cleanup()

    def test_denial_blocks_repeated_prompt_during_cooldown(self):
        tmp, guardian = self.make_guardian()
        try:
            payload = {
                "query": "tema",
            }
            req = guardian.request(
                capability="cloud_reasoning",
                payload=payload,
                reason="complex_task",
                description="usar cloud",
            )
            guardian.deny(req["token"])

            again = guardian.request(
                capability="cloud_reasoning",
                payload=payload,
                reason="complex_task",
                description="usar cloud",
            )
            self.assertTrue(
                again["denied_recently"]
            )
            self.assertFalse(
                again["allowed"]
            )
        finally:
            tmp.cleanup()

    def test_revoke_clears_grants_and_pending(self):
        tmp, guardian = self.make_guardian()
        try:
            req = guardian.request(
                capability="cloud_reasoning",
                payload={"query": "x"},
                reason="complex_task",
                description="usar cloud",
            )
            guardian.authorize(req["token"])
            guardian.request(
                capability="web_research",
                payload={"query": "y"},
                reason="web_required",
                description="usar web",
            )
            revoked = guardian.revoke_all()
            self.assertGreaterEqual(
                revoked["revoked_grants"],
                1,
            )
            self.assertGreaterEqual(
                revoked["revoked_pending"],
                1,
            )
            self.assertEqual(
                guardian.status()["active_grants"],
                0,
            )
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
