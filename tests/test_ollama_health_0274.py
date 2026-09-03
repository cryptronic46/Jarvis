from pathlib import Path
import unittest
import sys
import types
from unittest.mock import patch


class NativeLocalHealth0277Tests(unittest.TestCase):
    def test_validator_uses_chat_and_disables_thinking(self):
        text = Path("jarvis_core/services/full_validation.py").read_text(encoding="utf-8")
        self.assertIn("client.chat", text)
        self.assertIn("think=False", text)
        self.assertIn('"num_predict": 24', text)
        self.assertNotIn('endpoint = str(settings.ollama_host).rstrip("/") + "/api/generate"', text)

    def test_runtime_retries_empty_response_locally(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("LOCAL_EMPTY_RESPONSE_RETRY", text)
        self.assertIn('retry_kwargs["think"] = False', text)
        self.assertIn("LOCAL_EMPTY_RESPONSE_RECOVERED", text)

    def test_validator_uses_native_client_contract(self):
        text = Path("jarvis_core/services/full_validation.py").read_text(encoding="utf-8")
        self.assertIn("build_local_client", text)
        self.assertIn("validate_local_brain", text)
        self.assertIn("think=False", text)
        self.assertIn('"num_predict": 24', text)

    def test_full_validation_report_path_is_current_release(self):
        py = Path("jarvis_core/services/full_validation.py").read_text(encoding="utf-8")
        ps = Path("full_system_validation.ps1").read_text(encoding="utf-8")
        self.assertIn("full_validation_0277.json", py)
        self.assertIn("full_validation_0277.json", ps)
        self.assertNotIn("full_validation_0273.json", ps)


if __name__ == "__main__":
    unittest.main()
