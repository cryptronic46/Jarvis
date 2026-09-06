from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import sqlite3
import unittest

from jarvis_core.services.memory_index import UnifiedMemoryIndex


class UnifiedMemoryIndexTests(unittest.TestCase):
    def write_json(
        self,
        path: Path,
        value,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def write_jsonl(
        self,
        path: Path,
        rows,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            "".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                )
                + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

    def fixture(
        self,
        root: Path,
    ) -> None:
        self.write_json(
            root
            / "memory"
            / "user_profile.json",
            {
                "name":
                    "Test Owner",
                "home": {
                    "label":
                        "Furadouro Test",
                },
            },
        )

        self.write_jsonl(
            root
            / "memory"
            / "facts.jsonl",
            [
                {
                    "timestamp":
                        "2026-09-01T10:00:00+01:00",
                    "category":
                        "vehicle",
                    "fact":
                        "The OWNER drives a CUPRA MEMORYFACT.",
                },
            ],
        )

        self.write_jsonl(
            root
            / "memory"
            / "context.jsonl",
            [
                {
                    "turn_id":
                        "turn-test-001",
                    "timestamp":
                        "2026-09-02T10:00:00+01:00",
                    "user":
                        "We discussed CONTEXTNEEDLE yesterday.",
                    "assistant":
                        "Yes, this is the stored test turn.",
                    "route":
                        "LOCAL",
                    "content_hash":
                        "legacy-test-hash",
                },
                {
                    "timestamp":
                        "2026-09-02T11:00:00+01:00",
                    "user":
                        "Legacy CONTEXTNEEDLE row.",
                    "assistant":
                        "Legacy response.",
                    "route":
                        "LOCAL",
                },
                {
                    "timestamp":
                        "2026-09-02T11:00:00+01:00",
                    "user":
                        "Legacy CONTEXTNEEDLE row.",
                    "assistant":
                        "Legacy response.",
                    "route":
                        "LOCAL",
                },
            ],
        )

        self.write_json(
            root
            / "memory"
            / "memory_graph.json",
            {
                "version": 1,
                "updated_at":
                    "2026-09-02T12:00:00+01:00",
                "nodes": {
                    "node-1": {
                        "id":
                            "node-1",
                        "type":
                            "person",
                        "label":
                            "GRAPHNEEDLE Person",
                    },
                },
                "edges": [],
                "decisions": [
                    {
                        "id":
                            "decision-1",
                        "decision":
                            "Use GRAPHDECISION for testing.",
                        "context":
                            "Memory index test.",
                        "created_at":
                            "2026-09-02T12:00:00+01:00",
                    },
                ],
                "projects": {},
            },
        )

        self.write_json(
            root
            / "memory"
            / "personal_model.json",
            {
                "preferences": [
                    {
                        "statement":
                            "The OWNER prefers PERSONALNEEDLE.",
                        "first_seen":
                            "2026-09-03T10:00:00+01:00",
                    },
                ],
                "goals": [],
                "constraints": [],
                "projects": [],
                "jarvis_directives": [],
                "jarvis_learning_goals": [],
                "owner_learning_goals": [],
            },
        )

        self.write_jsonl(
            root
            / "knowledge"
            / "autonomy"
            / "authorized_learning.jsonl",
            [
                {
                    "timestamp":
                        "2026-09-04T10:00:00+01:00",
                    "learned_at":
                        "2026-09-04T10:00:00+01:00",
                    "topic":
                        "LEARNINGNEEDLE topic",
                    "summary":
                        "Validated local research summary for LEARNINGNEEDLE.",
                    "source_type":
                        "authorized_direct_web_local_model_summary_v2",
                    "sources": [
                        {
                            "title":
                                "Test source",
                            "url":
                                "https://example.com/test",
                        },
                    ],
                },
            ],
        )

        self.write_jsonl(
            root
            / "knowledge"
            / "autonomy"
            / "authorized_learning_quarantine.jsonl",
            [
                {
                    "topic":
                        "QUARANTINENEEDLE",
                    "summary":
                        "This must never enter the active index.",
                },
            ],
        )

    @staticmethod
    def file_hash(
        path: Path,
    ) -> str:
        return hashlib.sha256(
            path.read_bytes()
        ).hexdigest()

    def test_rebuild_creates_sqlite_and_fts5_schema(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            result = index.rebuild(
                root=root
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertGreater(
                result["record_count"],
                0,
            )

            conn = sqlite3.connect(
                result["path"]
            )

            try:
                names = {
                    row[0]
                    for row
                    in conn.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        """
                    )
                }
            finally:
                conn.close()

            self.assertIn(
                "records",
                names,
            )

            self.assertIn(
                "records_fts",
                names,
            )

            self.assertIn(
                "meta",
                names,
            )

    def test_rebuild_indexes_all_active_memory_sources(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            result = index.rebuild(
                root=root
            )

            sources = result[
                "sources"
            ]

            for source in (
                "user_profile",
                "explicit_fact",
                "conversation",
                "memory_graph",
                "personal_model",
                "authorized_learning",
            ):
                self.assertGreater(
                    sources.get(
                        source,
                        0,
                    ),
                    0,
                    source,
                )

    def test_fts_search_retrieves_across_memory_sources(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            index.rebuild(
                root=root
            )

            expectations = {
                "MEMORYFACT":
                    "explicit_fact",
                "CONTEXTNEEDLE":
                    "conversation",
                "GRAPHNEEDLE":
                    "memory_graph",
                "PERSONALNEEDLE":
                    "personal_model",
                "LEARNINGNEEDLE":
                    "authorized_learning",
                "Furadouro":
                    "user_profile",
            }

            for query, source in expectations.items():
                result = index.search(
                    query,
                    limit=10,
                )

                self.assertTrue(
                    result["ok"]
                )

                self.assertTrue(
                    any(
                        row["source"]
                        == source
                        for row
                        in result[
                            "results"
                        ]
                    ),
                    (
                        query
                        + " -> "
                        + source
                    ),
                )

    def test_quarantined_learning_is_not_indexed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            index.rebuild(
                root=root
            )

            result = index.search(
                "QUARANTINENEEDLE"
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertEqual(
                result["results"],
                [],
            )

    def test_rebuild_is_idempotent_and_collapses_exact_legacy_rows(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            first = index.rebuild(
                root=root
            )

            second = index.rebuild(
                root=root
            )

            self.assertEqual(
                first["record_count"],
                second["record_count"],
            )

            result = index.search(
                "Legacy CONTEXTNEEDLE",
                limit=20,
            )

            legacy = [
                row
                for row
                in result["results"]
                if (
                    row["source"]
                    == "conversation"
                    and
                    "Legacy"
                    in row["text"]
                )
            ]

            self.assertEqual(
                len(legacy),
                1,
            )

    def test_rebuild_does_not_modify_authoritative_source_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            sources = [
                root
                / "memory"
                / "user_profile.json",

                root
                / "memory"
                / "facts.jsonl",

                root
                / "memory"
                / "context.jsonl",

                root
                / "memory"
                / "memory_graph.json",

                root
                / "memory"
                / "personal_model.json",

                root
                / "knowledge"
                / "autonomy"
                / "authorized_learning.jsonl",

                root
                / "knowledge"
                / "autonomy"
                / "authorized_learning_quarantine.jsonl",
            ]

            before = {
                str(path):
                    self.file_hash(
                        path
                    )
                for path
                in sources
            }

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            index.rebuild(
                root=root
            )

            after = {
                str(path):
                    self.file_hash(
                        path
                    )
                for path
                in sources
            }

            self.assertEqual(
                before,
                after,
            )

    def test_malformed_jsonl_is_ignored_without_poisoning_rebuild(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            facts = (
                root
                / "memory"
                / "facts.jsonl"
            )

            with facts.open(
                "a",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    "{malformed-json}\n"
                )

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            result = index.rebuild(
                root=root
            )

            self.assertTrue(
                result["ok"]
            )

            found = index.search(
                "MEMORYFACT"
            )

            self.assertTrue(
                found["results"]
            )

    def test_user_query_is_tokenized_not_executed_as_raw_fts_syntax(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)

            self.fixture(root)

            index = UnifiedMemoryIndex(
                root
                / "memory"
                / "unified_memory.sqlite3"
            )

            index.rebuild(
                root=root
            )

            result = index.search(
                'MEMORYFACT OR "broken syntax'
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertIsInstance(
                result["results"],
                list,
            )



class SourceAwareMemoryRerankingTests(unittest.TestCase):
    def test_authoritative_source_is_not_buried_by_conversation_volume(self):
        rows = []

        for index in range(8):
            rows.append({
                "id": "conversation-" + str(index),
                "source": "conversation",
                "content_hash": "conversation-hash-" + str(index),
                "created_at": "2026-09-06T18:00:0" + str(index) + "+01:00",
                "rank": -10.0 + index,
            })

        rows.insert(
            4,
            {
                "id": "fact-1",
                "source": "explicit_fact",
                "content_hash": "fact-hash-1",
                "created_at": "2026-09-01T10:00:00+01:00",
                "rank": -6.5,
            },
        )

        result = UnifiedMemoryIndex._rerank_candidates(
            rows,
            limit=5,
        )

        self.assertEqual(
            len(result),
            5,
        )

        self.assertIn(
            "explicit_fact",
            [
                row.get("source")
                for row in result[:3]
            ],
        )

    def test_same_source_exact_content_hash_is_collapsed(self):
        rows = [
            {
                "id": "a",
                "source": "conversation",
                "content_hash": "same",
                "created_at": "2026-09-06T10:00:00+01:00",
                "rank": -5.0,
            },
            {
                "id": "b",
                "source": "conversation",
                "content_hash": "same",
                "created_at": "2026-09-06T10:00:01+01:00",
                "rank": -4.9,
            },
            {
                "id": "c",
                "source": "conversation",
                "content_hash": "different",
                "created_at": "2026-09-06T10:00:02+01:00",
                "rank": -4.8,
            },
        ]

        result = UnifiedMemoryIndex._rerank_candidates(
            rows,
            limit=10,
        )

        hashes = [
            row.get("content_hash")
            for row in result
        ]

        self.assertEqual(
            hashes.count("same"),
            1,
        )

        self.assertEqual(
            len(result),
            2,
        )

    def test_same_content_hash_from_different_sources_preserves_provenance(self):
        rows = [
            {
                "id": "conversation-1",
                "source": "conversation",
                "content_hash": "shared",
                "created_at": "2026-09-06T10:00:00+01:00",
                "rank": -5.0,
            },
            {
                "id": "fact-1",
                "source": "explicit_fact",
                "content_hash": "shared",
                "created_at": "2026-09-01T10:00:00+01:00",
                "rank": -4.9,
            },
        ]

        result = UnifiedMemoryIndex._rerank_candidates(
            rows,
            limit=10,
        )

        self.assertEqual(
            {
                row.get("source")
                for row in result
            },
            {
                "conversation",
                "explicit_fact",
            },
        )

    def test_conversation_only_search_can_still_fill_requested_limit(self):
        rows = [
            {
                "id": "conversation-" + str(index),
                "source": "conversation",
                "content_hash": "hash-" + str(index),
                "created_at": "2026-09-06T10:00:00+01:00",
                "rank": -10.0 + index,
            }
            for index in range(8)
        ]

        result = UnifiedMemoryIndex._rerank_candidates(
            rows,
            limit=5,
        )

        self.assertEqual(
            len(result),
            5,
        )

        self.assertTrue(
            all(
                row.get("source")
                == "conversation"
                for row in result
            )
        )

    def test_source_boost_order_prefers_durable_owner_memory(self):
        self.assertGreater(
            UnifiedMemoryIndex._source_boost(
                "explicit_fact"
            ),
            UnifiedMemoryIndex._source_boost(
                "conversation"
            ),
        )

        self.assertGreater(
            UnifiedMemoryIndex._source_boost(
                "personal_model"
            ),
            UnifiedMemoryIndex._source_boost(
                "authorized_learning"
            ),
        )

    def test_search_contract_supports_parameterized_source_filter(self):
        import inspect

        signature = inspect.signature(
            UnifiedMemoryIndex.search
        )

        self.assertIn(
            "sources",
            signature.parameters,
        )

        implementation = inspect.getsource(
            UnifiedMemoryIndex.search
        )

        self.assertIn(
            "r.source IN",
            implementation,
        )

        self.assertIn(
            "INVALID_MEMORY_SOURCE_FILTER",
            implementation,
        )

        self.assertNotIn(
            "source_filter)",
            implementation,
        )


if __name__ == "__main__":
    unittest.main()


class IncrementalMemoryIndexRefreshTests(
    unittest.TestCase
):
    def _fixture(
        self,
        root,
    ):
        import json

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
            json.dumps({
                "name":
                    "Fixture Owner",
                "preference":
                    "profilealpha",
            }),
            encoding="utf-8",
        )

        (
            memory
            / "facts.jsonl"
        ).write_text(
            json.dumps({
                "timestamp":
                    "2026-09-01T10:00:00+01:00",
                "category":
                    "preference",
                "fact":
                    "factsalpha",
            })
            + "\n",
            encoding="utf-8",
        )

        (
            memory
            / "context.jsonl"
        ).write_text(
            json.dumps({
                "turn_id":
                    "fixture-turn",
                "timestamp":
                    "2026-09-01T10:00:00+01:00",
                "user":
                    "contextalpha",
                "assistant":
                    "context reply",
                "route":
                    "LOCAL",
            })
            + "\n",
            encoding="utf-8",
        )

        (
            memory
            / "memory_graph.json"
        ).write_text(
            json.dumps({
                "nodes": {
                    "node-1": {
                        "type":
                            "fact",
                        "label":
                            "graphalpha",
                        "value":
                            "graphalpha",
                    }
                },
                "edges": [],
                "decisions": [],
                "projects": {},
            }),
            encoding="utf-8",
        )

        (
            memory
            / "personal_model.json"
        ).write_text(
            json.dumps({
                "preferences": [
                    {
                        "statement":
                            "personalalpha",
                        "first_seen":
                            "2026-09-01T10:00:00+01:00",
                    }
                ]
            }),
            encoding="utf-8",
        )

        (
            autonomy
            / "authorized_learning.jsonl"
        ).write_text(
            json.dumps({
                "id":
                    "learning-1",
                "topic":
                    "learningalpha",
                "summary":
                    "learningalpha summary",
                "source_type":
                    "test",
            })
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _meta(
        db,
    ):
        import sqlite3

        conn = sqlite3.connect(
            str(db)
        )

        try:
            return dict(
                conn.execute(
                    """
                    SELECT key, value
                    FROM meta
                    """
                ).fetchall()
            )

        finally:
            conn.close()

    @staticmethod
    def _records(
        db,
        source=None,
    ):
        import sqlite3

        conn = sqlite3.connect(
            str(db)
        )

        try:
            if source is None:
                rows = conn.execute(
                    """
                    SELECT
                        source,
                        id,
                        content_hash
                    FROM records
                    ORDER BY source, id
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT
                        source,
                        id,
                        content_hash
                    FROM records
                    WHERE source=?
                    ORDER BY source, id
                    """,
                    (
                        source,
                    ),
                ).fetchall()

            return [
                tuple(row)
                for row in rows
            ]

        finally:
            conn.close()

    def test_rebuild_establishes_all_source_fingerprints(
        self,
    ):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            result = UnifiedMemoryIndex(
                db
            ).rebuild(
                root=root
            )

            self.assertTrue(
                result["ok"]
            )

            meta = self._meta(
                db
            )

            expected = {
                (
                    "source_fingerprint:"
                    + source
                )
                for source in (
                    "user_profile",
                    "explicit_fact",
                    "conversation",
                    "memory_graph",
                    "personal_model",
                    "authorized_learning",
                )
            }

            self.assertTrue(
                expected.issubset(
                    set(meta)
                )
            )

            for key in expected:
                self.assertTrue(
                    meta[key].startswith(
                        "sha256:"
                    )
                )

    def test_noop_refresh_preserves_database_bytes(
        self,
    ):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            index = UnifiedMemoryIndex(
                db
            )

            index.rebuild(
                root=root
            )

            before = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            result = index.refresh_sources(
                root=root,
                sources=(
                    "memory_graph",
                ),
            )

            after = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            self.assertTrue(
                result["ok"]
            )

            self.assertFalse(
                result["refreshed"]
            )

            self.assertEqual(
                result["changed_sources"],
                [],
            )

            self.assertEqual(
                result["unchanged_sources"],
                [
                    "memory_graph",
                ],
            )

            self.assertEqual(
                before,
                after,
            )

    def test_changed_source_replaces_only_that_lane(
        self,
    ):
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            index = UnifiedMemoryIndex(
                db
            )

            index.rebuild(
                root=root
            )

            before_other = [
                row
                for row in self._records(
                    db
                )
                if row[0]
                != "memory_graph"
            ]

            self.assertTrue(
                index.search(
                    "graphalpha",
                    sources=(
                        "memory_graph",
                    ),
                )["results"]
            )

            (
                root
                / "memory"
                / "memory_graph.json"
            ).write_text(
                json.dumps({
                    "nodes": {
                        "node-2": {
                            "type":
                                "fact",
                            "label":
                                "graphbeta",
                            "value":
                                "graphbeta",
                        }
                    },
                    "edges": [],
                    "decisions": [],
                    "projects": {},
                }),
                encoding="utf-8",
            )

            result = index.refresh_sources(
                root=root,
                sources=(
                    "memory_graph",
                ),
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertEqual(
                result["changed_sources"],
                [
                    "memory_graph",
                ],
            )

            after_other = [
                row
                for row in self._records(
                    db
                )
                if row[0]
                != "memory_graph"
            ]

            self.assertEqual(
                before_other,
                after_other,
            )

            self.assertEqual(
                index.search(
                    "graphalpha",
                    sources=(
                        "memory_graph",
                    ),
                )["results"],
                [],
            )

            self.assertTrue(
                index.search(
                    "graphbeta",
                    sources=(
                        "memory_graph",
                    ),
                )["results"]
            )

    def test_legacy_database_without_fingerprint_bootstraps_requested_source(
        self,
    ):
        import sqlite3
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            index = UnifiedMemoryIndex(
                db
            )

            index.rebuild(
                root=root
            )

            conn = sqlite3.connect(
                str(db)
            )

            try:
                conn.execute(
                    """
                    DELETE FROM meta
                    WHERE key=?
                    """,
                    (
                        "source_fingerprint:"
                        "memory_graph",
                    ),
                )

                conn.commit()

            finally:
                conn.close()

            result = index.refresh_sources(
                root=root,
                sources=(
                    "memory_graph",
                ),
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertTrue(
                result["refreshed"]
            )

            self.assertEqual(
                result["changed_sources"],
                [
                    "memory_graph",
                ],
            )

            self.assertTrue(
                self._meta(
                    db
                )[
                    "source_fingerprint:"
                    "memory_graph"
                ].startswith(
                    "sha256:"
                )
            )

    def test_missing_canonical_source_removes_stale_rows(
        self,
    ):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            index = UnifiedMemoryIndex(
                db
            )

            index.rebuild(
                root=root
            )

            (
                root
                / "memory"
                / "facts.jsonl"
            ).unlink()

            result = index.refresh_sources(
                root=root,
                sources=(
                    "explicit_fact",
                ),
            )

            self.assertTrue(
                result["ok"]
            )

            self.assertEqual(
                result["changed_sources"],
                [
                    "explicit_fact",
                ],
            )

            self.assertEqual(
                self._records(
                    db,
                    "explicit_fact",
                ),
                [],
            )

            self.assertEqual(
                self._meta(
                    db
                )[
                    "source_fingerprint:"
                    "explicit_fact"
                ],
                "missing",
            )

    def test_invalid_source_filter_is_read_only(
        self,
    ):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            index = UnifiedMemoryIndex(
                db
            )

            index.rebuild(
                root=root
            )

            before = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            result = index.refresh_sources(
                root=root,
                sources=(
                    "not_a_memory_source",
                ),
            )

            after = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            self.assertFalse(
                result["ok"]
            )

            self.assertEqual(
                result["error"],
                "INVALID_MEMORY_SOURCE_FILTER",
            )

            self.assertEqual(
                before,
                after,
            )

    def test_refresh_failure_rolls_back_deleted_source(
        self,
    ):
        import json
        import tempfile
        from pathlib import Path

        class FailingIndex(
            UnifiedMemoryIndex
        ):
            @classmethod
            def _index_graph(
                cls,
                conn,
                root,
            ):
                raise RuntimeError(
                    "synthetic indexing failure"
                )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            baseline = UnifiedMemoryIndex(
                db
            )

            baseline.rebuild(
                root=root
            )

            before_rows = self._records(
                db,
                "memory_graph",
            )

            before_meta = self._meta(
                db
            )

            (
                root
                / "memory"
                / "memory_graph.json"
            ).write_text(
                json.dumps({
                    "nodes": {
                        "fail": {
                            "type":
                                "fact",
                            "label":
                                "shouldnotpersist",
                        }
                    },
                    "edges": [],
                    "decisions": [],
                    "projects": {},
                }),
                encoding="utf-8",
            )

            result = FailingIndex(
                db
            ).refresh_sources(
                root=root,
                sources=(
                    "memory_graph",
                ),
            )

            self.assertFalse(
                result["ok"]
            )

            self.assertEqual(
                self._records(
                    db,
                    "memory_graph",
                ),
                before_rows,
            )

            self.assertEqual(
                self._meta(
                    db
                ),
                before_meta,
            )

    def test_full_rebuild_rejects_source_change_during_population(
        self,
    ):
        import hashlib
        import json
        import tempfile
        from pathlib import Path

        class MutatingRebuildIndex(
            UnifiedMemoryIndex
        ):
            @classmethod
            def _index_graph(
                cls,
                conn,
                root,
            ):
                count = super()._index_graph(
                    conn,
                    root,
                )

                (
                    root
                    / "memory"
                    / "memory_graph.json"
                ).write_text(
                    json.dumps({
                        "nodes": {
                            "changed-during-rebuild": {
                                "type":
                                    "fact",
                                "label":
                                    "changedlater",
                            }
                        },
                        "edges": [],
                        "decisions": [],
                        "projects": {},
                    }),
                    encoding="utf-8",
                )

                return count

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            self._fixture(
                root
            )

            db = (
                root
                / "memory"
                / "unified.sqlite3"
            )

            baseline = UnifiedMemoryIndex(
                db
            )

            baseline.rebuild(
                root=root
            )

            before = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            with self.assertRaisesRegex(
                RuntimeError,
                "MEMORY_SOURCE_CHANGED_DURING_REBUILD",
            ):
                MutatingRebuildIndex(
                    db
                ).rebuild(
                    root=root
                )

            after = hashlib.sha256(
                db.read_bytes()
            ).hexdigest()

            self.assertEqual(
                before,
                after,
            )
