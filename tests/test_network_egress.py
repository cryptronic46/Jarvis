from __future__ import annotations

import unittest

from jarvis_core.services.network_egress import (
    NetworkEgressError,
    NetworkEgressGate,
    require_loopback_url,
)


class ExactGuardian:
    def __init__(
        self,
        *,
        research=False,
        learning=False,
    ):
        self.research = bool(research)
        self.learning = bool(learning)
        self.tokens = {}
        self.consume_calls = []

    def issue(
        self,
        token,
        capability,
        payload,
    ):
        self.tokens[str(token)] = {
            "capability": str(capability),
            "payload": dict(payload),
        }

    def consume_direct_authorization(
        self,
        *,
        execution_token,
        capability,
        payload,
    ):
        self.consume_calls.append({
            "execution_token":
                execution_token,
            "capability":
                capability,
            "payload":
                dict(payload),
        })

        row = self.tokens.pop(
            str(execution_token),
            None,
        )

        if row is None:
            return {
                "ok": False,
                "allowed": False,
                "error":
                    "TEST_TOKEN_INVALID",
            }

        if (
            row["capability"]
            != str(capability)
            or row["payload"]
            != dict(payload)
        ):
            return {
                "ok": False,
                "allowed": False,
                "error":
                    "TEST_SCOPE_MISMATCH",
            }

        return {
            "ok": True,
            "allowed": True,
        }

    def has_standing_public_web_research(
        self,
    ):
        return self.research

    def has_standing_public_web_learning(
        self,
    ):
        return self.learning


class NetworkEgressTests(unittest.TestCase):
    @staticmethod
    def public_url():
        return (
            "https://"
            + "8.8.8.8/"
            + "test"
        )

    def test_loopback_requirement_allows_only_loopback(
        self,
    ):
        ipv4 = (
            "http://"
            + "127.0.0.1:11434"
        )
        localhost = (
            "http://"
            + "localhost:11434"
        )

        self.assertEqual(
            require_loopback_url(ipv4),
            ipv4,
        )
        self.assertEqual(
            require_loopback_url(localhost),
            localhost,
        )

        with self.assertRaises(
            NetworkEgressError
        ):
            require_loopback_url(
                "http://"
                + "8.8.8.8"
            )

    def test_public_web_rejects_non_public_targets(
        self,
    ):
        gate = NetworkEgressGate(
            ExactGuardian(
                research=True
            )
        )

        blocked = (
            "127.0.0.1",
            "10.0.0.1",
            "169.254.169.254",
        )

        for host in blocked:
            with self.subTest(host=host):
                result = gate.allow_public_web(
                    "http://" + host + "/",
                    purpose="research",
                )

                self.assertFalse(
                    result["allowed"]
                )
                self.assertEqual(
                    result["error"],
                    "PUBLIC_WEB_TARGET_NOT_PUBLIC",
                )

    def test_exact_owner_token_opens_bounded_session(
        self,
    ):
        guardian = ExactGuardian()
        payload = {
            "operation":
                "bounded_research",
            "topic":
                "network egress test",
        }

        guardian.issue(
            "TOKEN-ONE",
            "web_research",
            payload,
        )

        gate = NetworkEgressGate(
            guardian
        )

        opened = gate.open_public_web_session(
            purpose="research",
            capability="web_research",
            payload=payload,
            execution_token="TOKEN-ONE",
        )

        self.assertTrue(
            opened["allowed"]
        )
        self.assertEqual(
            opened["authority"],
            "exact_owner_authorization",
        )
        self.assertEqual(
            len(guardian.consume_calls),
            1,
        )

        allowed = gate.allow_public_web(
            self.public_url(),
            purpose="research",
            session_token=
                opened["session_token"],
        )

        self.assertTrue(
            allowed["allowed"]
        )

        gate.close_public_web_session(
            opened["session_token"]
        )

        replay_session = (
            gate.allow_public_web(
                self.public_url(),
                purpose="research",
                session_token=
                    opened["session_token"],
            )
        )

        self.assertFalse(
            replay_session["allowed"]
        )
        self.assertEqual(
            replay_session["error"],
            "PUBLIC_WEB_SESSION_INVALID",
        )

        replay_token = (
            gate.open_public_web_session(
                purpose="research",
                capability="web_research",
                payload=payload,
                execution_token=
                    "TOKEN-ONE",
            )
        )

        self.assertFalse(
            replay_token["allowed"]
        )

    def test_session_cannot_cross_purpose_boundary(
        self,
    ):
        guardian = ExactGuardian(
            research=True,
        )
        gate = NetworkEgressGate(
            guardian
        )

        opened = gate.open_public_web_session(
            purpose="research",
            capability="web_research",
            payload={
                "operation":
                    "scope_test",
            },
        )

        self.assertTrue(
            opened["allowed"]
        )

        escaped = gate.allow_public_web(
            self.public_url(),
            purpose="learning",
            session_token=
                opened["session_token"],
        )

        self.assertFalse(
            escaped["allowed"]
        )
        self.assertEqual(
            escaped["error"],
            "PUBLIC_WEB_SESSION_SCOPE_MISMATCH",
        )

    def test_standing_permissions_are_separate(
        self,
    ):
        guardian = ExactGuardian(
            research=True,
            learning=True,
        )
        gate = NetworkEgressGate(
            guardian
        )

        research = gate.open_public_web_session(
            purpose="research",
            capability="web_research",
            payload={
                "operation":
                    "standing_research",
            },
        )

        learning = gate.open_public_web_session(
            purpose="learning",
            capability="external_learning",
            payload={
                "operation":
                    "standing_learning",
            },
        )

        self.assertTrue(
            research["allowed"]
        )
        self.assertTrue(
            learning["allowed"]
        )
        self.assertEqual(
            research["authority"],
            "standing_owner_permission",
        )
        self.assertEqual(
            learning["authority"],
            "standing_owner_permission",
        )

        self.assertTrue(
            gate.allow_public_web(
                self.public_url(),
                purpose="research",
                session_token=
                    research["session_token"],
            )["allowed"]
        )

        self.assertTrue(
            gate.allow_public_web(
                self.public_url(),
                purpose="learning",
                session_token=
                    learning["session_token"],
            )["allowed"]
        )

        gate.close_public_web_session(
            research["session_token"]
        )
        gate.close_public_web_session(
            learning["session_token"]
        )

    def test_capability_mismatch_fails_closed(
        self,
    ):
        guardian = ExactGuardian(
            research=True,
            learning=True,
        )
        gate = NetworkEgressGate(
            guardian
        )

        result = gate.open_public_web_session(
            purpose="research",
            capability="external_learning",
            payload={
                "operation":
                    "wrong_capability",
            },
        )

        self.assertFalse(
            result["allowed"]
        )
        self.assertEqual(
            result["error"],
            "PUBLIC_WEB_CAPABILITY_MISMATCH",
        )
        self.assertEqual(
            guardian.consume_calls,
            [],
        )


if __name__ == "__main__":
    unittest.main()
