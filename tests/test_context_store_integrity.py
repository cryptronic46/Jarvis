from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jarvis_core.services.context_store import ContextStore


class ContextStoreIntegrityTests(unittest.TestCase):
    def rows(self, path: Path) -> list[dict]:
        if not path.exists():
            return []

        return [
            json.loads(line)
            for line in path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]

    def test_new_turn_has_durable_identity_and_content_hash(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "context.jsonl"

            store = ContextStore(
                path
            )

            store.record(
                "owner turn",
                "assistant turn",
                "LOCAL",
            )

            rows = self.rows(
                path
            )

            self.assertEqual(
                len(rows),
                1,
            )

            row = rows[0]

            self.assertEqual(
                len(
                    row["turn_id"]
                ),
                32,
            )

            int(
                row["turn_id"],
                16,
            )

            self.assertEqual(
                len(
                    row["content_hash"]
                ),
                64,
            )

            int(
                row["content_hash"],
                16,
            )

            parsed = datetime.fromisoformat(
                row["timestamp"]
            )

            self.assertIsNotNone(
                parsed.tzinfo
            )

            self.assertEqual(
                row["user"],
                "owner turn",
            )

            self.assertEqual(
                row["assistant"],
                "assistant turn",
            )

            self.assertEqual(
                row["route"],
                "LOCAL",
            )

    def test_immediate_exact_duplicate_is_not_written_twice(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "context.jsonl"

            store = ContextStore(
                path
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "LOCAL",
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "LOCAL",
            )

            rows = self.rows(
                path
            )

            self.assertEqual(
                len(rows),
                1,
            )

    def test_same_content_with_different_route_is_preserved(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "context.jsonl"

            store = ContextStore(
                path
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "LOCAL",
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "FAST/test",
            )

            rows = self.rows(
                path
            )

            self.assertEqual(
                len(rows),
                2,
            )

    def test_deduplication_can_be_disabled_without_changing_api(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "context.jsonl"

            store = ContextStore(
                path,
                dedupe_window_seconds=0.0,
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "LOCAL",
            )

            store.record(
                "same owner turn",
                "same assistant turn",
                "LOCAL",
            )

            rows = self.rows(
                path
            )

            self.assertEqual(
                len(rows),
                2,
            )

    def test_legacy_row_without_hash_is_still_protected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "context.jsonl"

            now = datetime.now().astimezone().isoformat(
                timespec="microseconds"
            )

            path.write_text(
                json.dumps(
                    {
                        "timestamp": now,
                        "user": "legacy owner turn",
                        "assistant": "legacy assistant turn",
                        "route": "LOCAL",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            store = ContextStore(
                path
            )

            store.record(
                "legacy owner turn",
                "legacy assistant turn",
                "LOCAL",
            )

            rows = self.rows(
                path
            )

            self.assertEqual(
                len(rows),
                1,
            )


if __name__ == "__main__":
    unittest.main()
