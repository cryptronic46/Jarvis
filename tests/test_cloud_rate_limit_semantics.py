import unittest
from jarvis_core.core.cloud_brain import CloudBrain


class FakeRateLimitError(Exception):
    pass


class RateLimitError(Exception):
    def __init__(self, body=None):
        super().__init__("429")
        self.body = body


class CloudRateLimitSemanticsTests(unittest.TestCase):
    def test_temporary_rate_limit_is_retryable(self):
        exc = RateLimitError({"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error"}})
        error, message, provider, retryable = CloudBrain._classify_cloud_error(exc)
        self.assertEqual(error, "OPENAI_RATE_LIMIT_TEMPORARY")
        self.assertEqual(provider, "rate_limit_exceeded")
        self.assertTrue(retryable)
        self.assertIn("limite temporário", message)

    def test_credit_exhaustion_is_not_retryable_until_fixed(self):
        exc = RateLimitError({"error": {"code": "credit_balance_exhausted", "type": "insufficient_quota"}})
        error, message, provider, retryable = CloudBrain._classify_cloud_error(exc)
        self.assertEqual(error, "OPENAI_QUOTA_OR_BILLING")
        self.assertEqual(provider, "credit_balance_exhausted")
        self.assertFalse(retryable)
        self.assertIn("quota", message)

    def test_provider_payload_is_not_returned(self):
        exc = RateLimitError({"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error", "message": "secret-ish raw detail"}})
        _, message, _, _ = CloudBrain._classify_cloud_error(exc)
        self.assertNotIn("secret-ish", message)


if __name__ == "__main__":
    unittest.main()
