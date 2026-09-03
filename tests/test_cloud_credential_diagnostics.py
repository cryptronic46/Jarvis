import os
import sys
import types
import unittest
from unittest.mock import patch

from jarvis_core.services.secret_store import (
    secret_status,
)


class CloudCredentialDiagnosticsTests(unittest.TestCase):
    def fake_keyring(self, value):
        module = types.SimpleNamespace(
            get_password=lambda service, username: value
        )
        return patch.dict(
            sys.modules,
            {"keyring": module},
        )

    def test_environment_has_priority_without_exposing_secret(self):
        with self.fake_keyring(
            "credential-secret"
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "environment-secret"},
            clear=False,
        ):
            result = secret_status(
                "openai_api_key",
                "OPENAI_API_KEY",
            )

        self.assertEqual(
            result["effective_source"],
            "process_environment",
        )
        self.assertTrue(
            result[
                "environment_overrides_credential_manager"
            ]
        )
        dumped = str(result)
        self.assertNotIn(
            "environment-secret",
            dumped,
        )
        self.assertNotIn(
            "credential-secret",
            dumped,
        )

    def test_credential_manager_used_when_environment_absent(self):
        with self.fake_keyring(
            "credential-secret"
        ), patch.dict(
            os.environ,
            {},
            clear=True,
        ):
            result = secret_status(
                "openai_api_key",
                "OPENAI_API_KEY",
            )

        self.assertEqual(
            result["effective_source"],
            "windows_credential_manager",
        )


if __name__ == "__main__":
    unittest.main()
