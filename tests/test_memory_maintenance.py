from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jarvis_core.services.memory_index import UnifiedMemoryIndex
from jarvis_core.services.memory_maintenance import (
    RUNTIME_PERSONAL_SOURCES,
    TOOL_SOURCE_REFRESH,
    refresh_after_personal_cognition,
    refresh_after_tool,
    refresh_memory_sources,
    refresh_runtime_personal_memory,
)
from jarvis_core.skills.builtin.memory_graph import MemoryGraphStore


class RuntimeMemoryMaintenanceTests(
    unittest.TestCase
):
    def _root(
        self,
        temp_dir: str,
    ) -> Path:
        root = Path(
            temp_dir
        )

        memory = (
            root
            / "memory"
        )

        knowledge = (
            root
            / "knowledge"
            / "autonomy"
        )

        memory.mkdir(
            parents=True,
            exist_ok=True,
        )

        knowledge.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            memory
            / "user_profile.json"
        ).write_text(
            json.dumps(
                {
                    "name": "Test Owner",
                }
            ),
            encoding="utf-8",
        )

        (
            memory
            / "facts.jsonl"
        ).write_text(
            "",
            encoding="utf-8",
        )

        (
            memory
            / "context.jsonl"
        ).write_text(
            "",
            encoding="utf-8",
        )

        (
            memory
            / "memory_graph.json"
        ).write_text(
            json.dumps(
                {
                    "nodes": {},
                    "edges": [],
                    "decisions": [],
                    "projects": {},
                }
            ),
            encoding="utf-8",
        )

        (
            memory
            / "personal_model.json"
        ).write_text(
            json.dumps(
                {
                    "preferences": [],
                    "goals": [],
                    "projects": [],
                }
            ),
            encoding="utf-8",
        )

        (
            knowledge
            / "authorized_learning.jsonl"
        ).write_text(
            "",
            encoding="utf-8",
        )

        return root

    def _build(
        self,
        root: Path,
    ) -> Path:
        index_path = (
            root
            / "memory"
            / "unified_memory.sqlite3"
        )

        result = UnifiedMemoryIndex(
            index_path
        ).rebuild(
            root=root
        )

        self.assertTrue(
            result.get("ok"),
            result,
        )

        self.assertTrue(
            index_path.is_file()
        )

        return index_path

    @staticmethod
    def _hash(
        path: Path,
    ) -> str:
        return hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    def test_tool_source_map_is_exact(
        self,
    ):
        self.assertEqual(
            dict(
                TOOL_SOURCE_REFRESH
            ),
            {
                "remember_user_fact": (
                    "explicit_fact",
                    "memory_graph",
                ),
                "record_jarvis_learning_goal": (
                    "personal_model",
                ),
                "record_local_teaching": (
                    "personal_model",
                ),
                "remember_project_state": (
                    "memory_graph",
                ),
                "remember_decision": (
                    "memory_graph",
                ),
                "relate_memory_entities": (
                    "memory_graph",
                ),
            },
        )

        self.assertEqual(
            RUNTIME_PERSONAL_SOURCES,
            (
                "user_profile",
                "explicit_fact",
                "personal_model",
                "memory_graph",
            ),
        )

    def test_unmapped_tool_is_true_noop(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            before = self._hash(
                index_path
            )

            result = refresh_after_tool(
                "get_memory_status",
                root=root,
                index_path=index_path,
            )

            after = self._hash(
                index_path
            )

            self.assertTrue(
                result.get("ok")
            )

            self.assertFalse(
                result.get("attempted")
            )

            self.assertEqual(
                before,
                after,
            )

    def test_nonindexed_cognition_mode_tool_is_noop(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            before = self._hash(
                index_path
            )

            result = refresh_after_tool(
                "set_personal_cognition_mode",
                root=root,
                index_path=index_path,
            )

            self.assertFalse(
                result.get("attempted")
            )

            self.assertEqual(
                before,
                self._hash(
                    index_path
                ),
            )

    def test_remember_user_fact_refreshes_exact_two_lanes(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            fact_path = (
                root
                / "memory"
                / "facts.jsonl"
            )

            with fact_path.open(
                "a",
                encoding="utf-8",
            ) as stream:
                stream.write(
                    json.dumps(
                        {
                            "timestamp": "2026-01-01T00:00:00+00:00",
                            "category": "general",
                            "fact": "Owner likes green tea",
                        }
                    )
                    + "\n"
                )

            graph_result = MemoryGraphStore(
                root
                / "memory"
                / "memory_graph.json"
            ).ingest_explicit_fact(
                "Owner likes green tea",
                "general",
            )

            self.assertTrue(
                graph_result.get("ok")
            )

            result = refresh_after_tool(
                "remember_user_fact",
                root=root,
                index_path=index_path,
            )

            self.assertTrue(
                result.get("ok"),
                result,
            )

            self.assertTrue(
                result.get("attempted")
            )

            self.assertEqual(
                result.get("changed_sources"),
                [
                    "explicit_fact",
                    "memory_graph",
                ],
            )

    def test_personal_cognition_refreshes_personal_model_only(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            model_path = (
                root
                / "memory"
                / "personal_model.json"
            )

            model_path.write_text(
                json.dumps(
                    {
                        "preferences": [
                            "Owner prefers quiet mode",
                        ],
                        "goals": [],
                        "projects": [],
                    }
                ),
                encoding="utf-8",
            )

            result = refresh_after_personal_cognition(
                {
                    "ok": True,
                    "learning_enabled": True,
                    "learned": [],
                },
                root=root,
                index_path=index_path,
            )

            self.assertTrue(
                result.get("ok"),
                result,
            )

            self.assertEqual(
                result.get("changed_sources"),
                [
                    "personal_model",
                ],
            )

    def test_disabled_personal_learning_is_noop(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            before = self._hash(
                index_path
            )

            result = refresh_after_personal_cognition(
                {
                    "ok": True,
                    "learning_enabled": False,
                    "learned": [],
                },
                root=root,
                index_path=index_path,
            )

            self.assertTrue(
                result.get("ok")
            )

            self.assertFalse(
                result.get("attempted")
            )

            self.assertEqual(
                before,
                self._hash(
                    index_path
                ),
            )

    def test_startup_personal_refresh_is_noop_when_fresh(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            before = self._hash(
                index_path
            )

            result = refresh_runtime_personal_memory(
                root=root,
                index_path=index_path,
            )

            self.assertTrue(
                result.get("ok"),
                result,
            )

            self.assertTrue(
                result.get("attempted")
            )

            self.assertFalse(
                result.get("refreshed")
            )

            self.assertEqual(
                set(
                    result.get(
                        "unchanged_sources"
                    )
                    or []
                ),
                set(
                    RUNTIME_PERSONAL_SOURCES
                ),
            )

            self.assertEqual(
                before,
                self._hash(
                    index_path
                ),
            )

    def test_missing_index_fails_soft_without_rebuild(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = (
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            self.assertFalse(
                index_path.exists()
            )

            result = refresh_memory_sources(
                (
                    "personal_model",
                ),
                root=root,
                index_path=index_path,
            )

            self.assertFalse(
                result.get("ok")
            )

            self.assertTrue(
                result.get("attempted")
            )

            self.assertEqual(
                result.get("error"),
                "MEMORY_INDEX_NOT_AVAILABLE",
            )

            self.assertFalse(
                index_path.exists()
            )

    def test_forbidden_source_fails_closed_read_only(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build(
                root
            )

            before = self._hash(
                index_path
            )

            result = refresh_memory_sources(
                (
                    "conversation",
                ),
                root=root,
                index_path=index_path,
            )

            self.assertFalse(
                result.get("ok")
            )

            self.assertFalse(
                result.get("attempted")
            )

            self.assertEqual(
                result.get("error"),
                "MEMORY_RUNTIME_SOURCE_FORBIDDEN",
            )

            self.assertEqual(
                before,
                self._hash(
                    index_path
                ),
            )


if __name__ == "__main__":
    unittest.main()
