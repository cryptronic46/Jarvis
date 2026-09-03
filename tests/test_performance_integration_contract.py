import unittest
from pathlib import Path


class PerformanceIntegrationContractTests(unittest.TestCase):
    def test_cli_has_performance_modes(self):
        cli = Path(
            "jarvis_core/cli.py"
        ).read_text(encoding="utf-8")
        for command in (
            "/perf status",
            "/perf auto",
            "/perf fast",
            "/perf balanced",
            "/perf deep",
            "/perf eco",
            "/perf release",
        ):
            self.assertIn(command, cli)

    def test_brain_has_resource_release(self):
        brain = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "def release_model",
            brain,
        )
        self.assertIn(
            "keep_alive=0",
            brain,
        )

    def test_cyber_context_is_request_scoped(self):
        brain = Path(
            "jarvis_core/core/brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Cyber RAG is request-scoped",
            brain,
        )
        self.assertIn(
            "self._request_messages(",
            brain,
        )
        self.assertNotIn(
            'self.messages.append({\n                "role": "system",\n                "content": cyber_context',
            brain,
        )

    def test_background_services_have_resource_guard(self):
        security = Path(
            "jarvis_core/services/security_watch.py"
        ).read_text(encoding="utf-8")
        cyber = Path(
            "jarvis_core/services/cyber_knowledge.py"
        ).read_text(encoding="utf-8")

        self.assertIn("resource_guard", security)
        self.assertIn("resource_guard", cyber)
        self.assertIn(
            "BACKGROUND_WORK_DEFERRED",
            security,
        )
        self.assertIn(
            "BACKGROUND_WORK_DEFERRED",
            cyber,
        )

    def test_hybrid_offloads_only_as_local_first_escalation(self):
        hybrid = Path(
            "jarvis_core/core/hybrid_brain.py"
        ).read_text(encoding="utf-8")
        self.assertIn("complexity_score", hybrid)
        self.assertIn("Local-first: always attempt the local model first", hybrid)
        self.assertIn("_learning_gap_offer", hybrid)
        self.assertIn("studied_knowledge_still_insufficient", hybrid)
        self.assertIn('capability="cloud_reasoning"', hybrid)
        self.assertNotIn("should_offload_to_cloud(decision.text)", hybrid)


if __name__ == "__main__":
    unittest.main()
