from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jarvis_core.core.tool_registry as registry_module
import jarvis_core.services.memory_maintenance as maintenance_module

from jarvis_core.core.tool_registry import (
    RiskLevel,
    ToolDef,
    ToolRegistry,
)
from jarvis_core.services.memory_index import UnifiedMemoryIndex
from jarvis_core.services.user_memory import UserMemoryStore
from jarvis_core.skills.builtin.memory_graph import MemoryGraphStore


class _Events:
    def __init__(self):
        self.rows = []

    def emit(
        self,
        event,
        **payload,
    ):
        self.rows.append(
            (
                event,
                payload,
            )
        )


class _Profile:
    @staticmethod
    def tool_allowed(
        name,
    ):
        return True

    @staticmethod
    def active_id():
        return "test"


class MemoryRuntimeEndToEndTests(
    unittest.TestCase
):
    def _root(
        self,
        temp_dir,
    ):
        root = Path(
            temp_dir
        ).resolve()

        memory = (
            root
            / "memory"
        )

        autonomy = (
            root
            / "knowledge"
            / "autonomy"
        )

        memory.mkdir(
            parents=True,
            exist_ok=True,
        )

        autonomy.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            memory
            / "user_profile.json"
        ).write_text(
            json.dumps(
                {
                    "name": "E2E Test Owner",
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
                    "constraints": [],
                    "projects": [],
                }
            ),
            encoding="utf-8",
        )

        (
            autonomy
            / "authorized_learning.jsonl"
        ).write_text(
            "",
            encoding="utf-8",
        )

        return root

    def _build_index(
        self,
        root,
    ):
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

        return index_path

    def _registry(
        self,
        name,
        handler,
    ):
        registry = object.__new__(
            ToolRegistry
        )

        registry.events = _Events()
        registry.security = None

        tool = ToolDef(
            name,
            "isolated memory E2E tool",
            handler,
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description":
                        "isolated memory E2E tool",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
            RiskLevel.LOW,
        )

        registry._tools = {
            name: tool,
        }

        registry._validate_arguments = (
            lambda tool_def, arguments:
                (
                    True,
                    None,
                )
        )

        return registry

    @staticmethod
    def _source_counts(
        index_path,
    ):
        uri = (
            "file:"
            + Path(
                index_path
            ).resolve().as_posix()
            + "?mode=ro"
        )

        conn = sqlite3.connect(
            uri,
            uri=True,
        )

        try:
            return dict(
                conn.execute(
                    """
                    SELECT source, COUNT(*)
                    FROM records
                    GROUP BY source
                    ORDER BY source
                    """
                ).fetchall()
            )

        finally:
            conn.close()

    def test_explicit_fact_tool_write_refreshes_and_is_immediately_searchable(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build_index(
                root
            )

            store = UserMemoryStore(
                memory_dir=(
                    root
                    / "memory"
                )
            )

            marker = (
                "orchid cobalt lighthouse 47291"
            )

            registry = self._registry(
                "remember_user_fact",
                store.remember,
            )

            old_cwd = Path.cwd()

            try:
                os.chdir(
                    root
                )

                with patch.object(
                    registry_module,
                    "profile_manager",
                    return_value=_Profile(),
                ):
                    raw_result = registry.execute(
                        "remember_user_fact",
                        {
                            "fact": marker,
                            "category": "e2e",
                        },
                        bypass_profile_permission=True,
                    )

            finally:
                os.chdir(
                    old_cwd
                )

            result = json.loads(
                raw_result
            )

            self.assertTrue(
                result.get("ok"),
                result,
            )

            facts_text = (
                root
                / "memory"
                / "facts.jsonl"
            ).read_text(
                encoding="utf-8",
            )

            self.assertIn(
                marker,
                facts_text,
            )

            graph_text = (
                root
                / "memory"
                / "memory_graph.json"
            ).read_text(
                encoding="utf-8",
            )

            self.assertIn(
                marker,
                graph_text,
            )

            search_result = UnifiedMemoryIndex(
                index_path
            ).search(
                marker,
                limit=10,
                sources=(
                    "explicit_fact",
                    "memory_graph",
                ),
            )

            self.assertTrue(
                search_result.get("ok"),
                search_result,
            )

            hits = list(
                search_result.get("results")
                or []
            )

            self.assertTrue(
                hits,
                search_result,
            )

            hit_sources = {
                row.get("source")
                for row in hits
            }

            self.assertIn(
                "explicit_fact",
                hit_sources,
            )

            self.assertIn(
                "memory_graph",
                hit_sources,
            )

            counts = self._source_counts(
                index_path
            )

            self.assertEqual(
                counts.get(
                    "explicit_fact"
                ),
                1,
            )

            self.assertGreater(
                counts.get(
                    "memory_graph",
                    0,
                ),
                0,
            )

    def test_graph_tool_write_refreshes_graph_lane_and_is_searchable(
        self,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(
                td
            )

            index_path = self._build_index(
                root
            )

            graph_store = MemoryGraphStore(
                root
                / "memory"
                / "memory_graph.json"
            )

            marker = (
                "decision amber compass 61842"
            )

            def handler():
                return graph_store.remember_decision(
                    marker,
                    "isolated e2e",
                )

            registry = self._registry(
                "remember_decision",
                handler,
            )

            old_cwd = Path.cwd()

            try:
                os.chdir(
                    root
                )

                with patch.object(
                    registry_module,
                    "profile_manager",
                    return_value=_Profile(),
                ):
                    raw_result = registry.execute(
                        "remember_decision",
                        {},
                        bypass_profile_permission=True,
                    )

            finally:
                os.chdir(
                    old_cwd
                )

            result = json.loads(
                raw_result
            )

            self.assertTrue(
                result.get("ok"),
                result,
            )

            search_result = UnifiedMemoryIndex(
                index_path
            ).search(
                marker,
                limit=10,
                sources=(
                    "memory_graph",
                ),
            )

            self.assertTrue(
                search_result.get("ok"),
                search_result,
            )

            hits = list(
                search_result.get("results")
                or []
            )

            self.assertTrue(
                hits,
                search_result,
            )

            self.assertTrue(
                all(
                    row.get("source")
                    == "memory_graph"
                    for row in hits
                )
            )

    def test_failed_tool_result_does_not_run_memory_refresh(
        self,
    ):
        registry = self._registry(
            "remember_decision",
            lambda: {
                "ok": False,
                "error":
                    "EXPECTED_E2E_HANDLER_FAILURE",
            },
        )

        with patch.object(
            registry_module,
            "profile_manager",
            return_value=_Profile(),
        ):
            with patch.object(
                maintenance_module,
                "refresh_after_tool",
            ) as refresh:
                raw_result = registry.execute(
                    "remember_decision",
                    {},
                    bypass_profile_permission=True,
                )

        result = json.loads(
            raw_result
        )

        self.assertFalse(
            result.get("ok")
        )

        self.assertEqual(
            result.get("error"),
            "EXPECTED_E2E_HANDLER_FAILURE",
        )

        refresh.assert_not_called()

    def test_refresh_exception_is_fail_soft_and_preserves_real_tool_result(
        self,
    ):
        expected = {
            "ok": True,
            "value":
                "CANONICAL_HANDLER_RESULT_PRESERVED",
        }

        registry = self._registry(
            "remember_decision",
            lambda: dict(
                expected
            ),
        )

        with patch.object(
            registry_module,
            "profile_manager",
            return_value=_Profile(),
        ):
            with patch.object(
                maintenance_module,
                "refresh_after_tool",
                side_effect=RuntimeError(
                    "EXPECTED_DERIVED_INDEX_FAILURE"
                ),
            ):
                raw_result = registry.execute(
                    "remember_decision",
                    {},
                    bypass_profile_permission=True,
                )

        result = json.loads(
            raw_result
        )

        self.assertEqual(
            result,
            expected,
        )

    def test_unmapped_successful_tool_never_refreshes_memory(
        self,
    ):
        expected = {
            "ok": True,
            "value":
                "READ_ONLY_TOOL_RESULT",
        }

        registry = self._registry(
            "get_memory_status",
            lambda: dict(
                expected
            ),
        )

        with patch.object(
            registry_module,
            "profile_manager",
            return_value=_Profile(),
        ):
            with patch.object(
                maintenance_module,
                "refresh_after_tool",
                wraps=(
                    maintenance_module
                    .refresh_after_tool
                ),
            ) as refresh:
                raw_result = registry.execute(
                    "get_memory_status",
                    {},
                    bypass_profile_permission=True,
                )

        result = json.loads(
            raw_result
        )

        self.assertEqual(
            result,
            expected,
        )

        refresh.assert_called_once_with(
            "get_memory_status"
        )


if __name__ == "__main__":
    unittest.main()
