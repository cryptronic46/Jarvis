import unittest
from pathlib import Path


class CyberKnowledgeBrainContractTests(unittest.TestCase):
    def test_brain_retrieves_vault_context(self):
        text = Path("jarvis_core/core/brain.py").read_text(encoding="utf-8")
        self.assertIn("cyber_vault().knowledge_context", text)
        self.assertIn("CYBER_KNOWLEDGE_RETRIEVED", text)
        self.assertIn("search_cyber_knowledge", text)

    def test_cyber_reasoning_is_local_first(self):
        text = Path("jarvis_core/core/hybrid_brain.py").read_text(encoding="utf-8")
        self.assertIn('return HybridDecision("local", "local_first"', text)
        self.assertNotIn('route="cloud"', text)

    def test_vault_not_cloud_allowlisted(self):
        cloud = Path("jarvis_core/core/cloud_brain.py").read_text(encoding="utf-8")
        start = cloud.index("DEFAULT_ALLOWED_TOOLS = {")
        end = cloud.index("}", start)
        section = cloud[start:end]
        self.assertNotIn('"search_cyber_knowledge"', section)
        self.assertNotIn('"sync_cyber_knowledge"', section)


if __name__ == "__main__":
    unittest.main()
