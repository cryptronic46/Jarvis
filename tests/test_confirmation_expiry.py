import unittest
from datetime import datetime, timedelta

from jarvis_core.security.policy import (
    RiskLevel,
    SecurityPolicy,
)


class ConfirmationExpiryTests(unittest.TestCase):
    def test_confirmation_tokens_expire(self):
        policy = SecurityPolicy(
            confirmation_ttl_seconds=30
        )
        policy.register(
            "close_application",
            RiskLevel.CONFIRM,
            "Close app",
        )
        pending = policy.request_confirmation(
            "close_application",
            {"app_name": "demo"},
            "Close app",
        )
        pending.created_at = (
            datetime.now().astimezone()
            - timedelta(minutes=5)
        ).isoformat(timespec="seconds")

        self.assertIsNone(
            policy.pop_pending(pending.token)
        )

    def test_fresh_confirmation_token_is_accepted(self):
        policy = SecurityPolicy(
            confirmation_ttl_seconds=600
        )
        pending = policy.request_confirmation(
            "close_application",
            {"app_name": "demo"},
            "Close app",
        )
        self.assertIsNotNone(
            policy.pop_pending(pending.token)
        )

    def test_unknown_tool_policy_stays_critical(self):
        policy = SecurityPolicy()
        self.assertEqual(
            policy.policy_for("does_not_exist").risk,
            RiskLevel.CRITICAL,
        )


if __name__ == "__main__":
    unittest.main()
