import unittest
from pathlib import Path


class ExternalResearchRetryContractTests(unittest.TestCase):
    def test_failed_learning_requeues_exact_scope_without_standing_grant(self):
        text = Path("jarvis_core/cli.py").read_text(encoding="utf-8")
        start = text.index("def queue_external_learning_retry(")
        end = text.index("def execute_direct_external_learning(", start)
        block = text[start:end]
        self.assertIn('capability="external_learning"', block)
        self.assertIn('"external_learning_resume_query"', block)
        self.assertIn('else "external_learning"', block)
        self.assertIn('"SEARCH_FAILED"', block)
        self.assertIn('"FETCH_FAILED"', block)
        self.assertIn('"LOCAL_SYNTHESIS_FAILED"', block)
        self.assertNotIn("record_direct_authorization", block)
        self.assertNotIn("OPENAI_", block)


if __name__ == "__main__":
    unittest.main()
