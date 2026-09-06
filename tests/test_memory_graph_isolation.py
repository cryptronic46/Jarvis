import hashlib
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.user_memory import (
    UserMemoryStore,
)
from jarvis_core.skills.builtin.memory_graph import (
    ingest_explicit_memory_fact,
    memory_graph,
)


class MemoryGraphPathIsolationTests(
    unittest.TestCase
):
    @staticmethod
    def _sha256(
        path: Path,
    ) -> str:
        return hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    def test_graph_cache_is_scoped_by_resolved_path(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            first_path = (
                root
                / "one"
                / "graph.json"
            )

            second_path = (
                root
                / "two"
                / "graph.json"
            )

            first = memory_graph(
                first_path
            )

            first_again = memory_graph(
                first_path.resolve()
            )

            second = memory_graph(
                second_path
            )

            self.assertIs(
                first,
                first_again,
            )

            self.assertIsNot(
                first,
                second,
            )

            first.ingest_explicit_fact(
                "fixture graph one",
                "test",
            )

            second.ingest_explicit_fact(
                "fixture graph two",
                "test",
            )

            first_text = first_path.read_text(
                encoding="utf-8"
            )

            second_text = second_path.read_text(
                encoding="utf-8"
            )

            self.assertIn(
                "fixture graph one",
                first_text,
            )

            self.assertNotIn(
                "fixture graph two",
                first_text,
            )

            self.assertIn(
                "fixture graph two",
                second_text,
            )

            self.assertNotIn(
                "fixture graph one",
                second_text,
            )

    def test_explicit_ingest_respects_requested_path(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            graph_path = (
                Path(td)
                / "memory"
                / "memory_graph.json"
            )

            result = ingest_explicit_memory_fact(
                "isolated helper fixture",
                "test",
                path=graph_path,
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertTrue(
                graph_path.is_file()
            )

            self.assertIn(
                "isolated helper fixture",
                graph_path.read_text(
                    encoding="utf-8"
                ),
            )

    def test_custom_user_store_does_not_touch_runtime_graph(
        self,
    ):
        runtime_graph = Path(
            "memory/memory_graph.json"
        )

        self.assertTrue(
            runtime_graph.is_file()
        )

        before = self._sha256(
            runtime_graph
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            defaults = (
                root
                / "default.json"
            )

            defaults.write_text(
                '{"name":"Fixture Owner"}',
                encoding="utf-8",
            )

            memory_dir = (
                root
                / "memory"
            )

            store = UserMemoryStore(
                memory_dir,
                defaults,
            )

            marker = (
                "custom user memory isolation fixture"
            )

            result = store.remember(
                marker,
                "test",
            )

            self.assertTrue(
                result["ok"]
            )

            facts = (
                memory_dir
                / "facts.jsonl"
            )

            graph = (
                memory_dir
                / "memory_graph.json"
            )

            self.assertTrue(
                facts.is_file()
            )

            self.assertTrue(
                graph.is_file()
            )

            self.assertIn(
                marker,
                facts.read_text(
                    encoding="utf-8"
                ),
            )

            self.assertIn(
                marker,
                graph.read_text(
                    encoding="utf-8"
                ),
            )

        after = self._sha256(
            runtime_graph
        )

        self.assertEqual(
            before,
            after,
        )


if __name__ == "__main__":
    unittest.main()
