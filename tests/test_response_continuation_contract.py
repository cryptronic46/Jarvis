import unittest
from pathlib import Path


class ResponseContinuationContractTests(unittest.TestCase):
    def test_brain_has_bounded_tool_free_continuation(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("def _complete_truncated_response", text)
        self.assertIn("RESPONSE_TRUNCATION_DETECTED", text)
        self.assertIn("RESPONSE_CONTINUATION_STARTED", text)
        self.assertIn("llm_max_continuations", text)
        self.assertIn("llm_continuation_num_predict", text)
        self.assertIn("think=False", text)
        continuation = text.split("def _complete_truncated_response", 1)[1].split("def ask", 1)[0]
        self.assertNotIn('"tools":', continuation)
        self.assertNotIn("tools=", continuation)

    def test_defaults_enable_auto_continuation(self):
        text = Path("jarvis_core/core/config.py").read_text(encoding="utf-8")
        self.assertIn("llm_auto_continue_truncated: bool = True", text)
        self.assertIn("llm_max_continuations: int = 3", text)


if __name__ == "__main__":
    unittest.main()
