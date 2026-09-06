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

    def test_pending_reuse_requires_exact_action(self):
        tmp, guardian = self.make_guardian()

        try:
            guardian.settings.autonomy_max_pending = max(
                2,
                int(
                    guardian.settings.autonomy_max_pending
                ),
            )

            payload = {
                "topic": "Python",
                "query": "estudar Python",
                "deep": False,
            }

            first = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            second = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar e retomar",
                action="external_learning_resume_query",
            )

            self.assertTrue(
                first["pending"]
            )

            self.assertTrue(
                second["pending"]
            )

            self.assertFalse(
                second.get(
                    "reused_pending",
                    False,
                )
            )

            self.assertNotEqual(
                first["token"],
                second["token"],
            )

        finally:
            tmp.cleanup()


    def test_grant_auto_consumption_requires_exact_action(self):
        tmp, guardian = self.make_guardian()

        try:
            payload = {
                "topic": "Python",
                "query": "estudar Python",
                "deep": False,
            }

            requested = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            approved = guardian.authorize(
                requested["token"]
            )

            self.assertTrue(
                approved["authorized"]
            )

            wrong_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar e retomar",
                action="external_learning_resume_query",
            )

            self.assertFalse(
                wrong_action["allowed"]
            )

            self.assertTrue(
                wrong_action["pending"]
            )

            exact_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            self.assertTrue(
                exact_action["allowed"]
            )

            replay = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            self.assertFalse(
                replay["allowed"]
            )

        finally:
            tmp.cleanup()


    def test_exact_token_consumption_requires_exact_action(self):
        tmp, guardian = self.make_guardian()

        try:
            payload = {
                "topic": "Python",
                "query": "estudar Python",
                "deep": False,
                "scope":
                    "single_research_session",
            }

            requested = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            approved = guardian.authorize(
                requested["token"]
            )

            self.assertTrue(
                approved["authorized"]
            )

            wrong_action = (
                guardian.consume_authorized_grant(
                    token=requested["token"],
                    capability="external_learning",
                    payload=payload,
                    action=(
                        "external_learning_resume_query"
                    ),
                )
            )

            self.assertFalse(
                wrong_action["allowed"]
            )

            self.assertEqual(
                wrong_action["error"],
                "AUTHORIZATION_ACTION_MISMATCH",
            )

            exact_action = (
                guardian.consume_authorized_grant(
                    token=requested["token"],
                    capability="external_learning",
                    payload=payload,
                    action="external_learning",
                )
            )

            self.assertTrue(
                exact_action["allowed"]
            )

            replay = (
                guardian.consume_authorized_grant(
                    token=requested["token"],
                    capability="external_learning",
                    payload=payload,
                    action="external_learning",
                )
            )

            self.assertFalse(
                replay["allowed"]
            )

        finally:
            tmp.cleanup()


    def test_denial_requires_exact_action(self):
        tmp, guardian = self.make_guardian()

        try:
            payload = {
                "topic": "Python",
                "query": "estudar Python",
                "deep": False,
            }

            requested = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            denied = guardian.deny(
                requested["token"]
            )

            self.assertTrue(
                denied["denied"]
            )

            other_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar e retomar",
                action="external_learning_resume_query",
            )

            self.assertFalse(
                other_action.get(
                    "denied_recently",
                    False,
                )
            )

            self.assertTrue(
                other_action["pending"]
            )

            exact_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            self.assertTrue(
                exact_action[
                    "denied_recently"
                ]
            )

            self.assertFalse(
                exact_action["allowed"]
            )

        finally:
            tmp.cleanup()


    def test_expired_cooldown_requires_exact_action(self):
        tmp, guardian = self.make_guardian()

        try:
            payload = {
                "topic": "Python",
                "query": "estudar Python",
                "deep": False,
            }

            guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            state = guardian._load()

            state["pending"][0][
                "expires_at"
            ] = (
                "2000-01-01T00:00:00+00:00"
            )

            guardian._save(
                state
            )

            other_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar e retomar",
                action="external_learning_resume_query",
            )

            self.assertFalse(
                other_action.get(
                    "cooldown",
                    False,
                )
            )

            self.assertTrue(
                other_action["pending"]
            )

            exact_action = guardian.request(
                capability="external_learning",
                payload=payload,
                reason="owner_request",
                description="estudar",
                action="external_learning",
            )

            self.assertTrue(
                exact_action["cooldown"]
            )

            self.assertFalse(
                exact_action["allowed"]
            )

        finally:
            tmp.cleanup()



if __name__ == "__main__":
    unittest.main()
