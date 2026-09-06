from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import os
import re
import sqlite3
import tempfile


SCHEMA_VERSION = "1"


def _clean(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip(),
    )


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(
        str(value).encode("utf-8")
    ).hexdigest()


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []

    rows: list[dict[str, Any]] = []

    for raw in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        if not raw.strip():
            continue

        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if isinstance(row, dict):
            rows.append(row)

    return rows


def _json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}

    try:
        value = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )
    except Exception:
        return {}

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _scalar_lines(
    value: Any,
    prefix: str = "",
) -> list[str]:
    rows: list[str] = []

    if isinstance(value, dict):
        for key in sorted(value):
            child = (
                str(key)
                if not prefix
                else prefix + "." + str(key)
            )

            rows.extend(
                _scalar_lines(
                    value[key],
                    child,
                )
            )

        return rows

    if isinstance(value, list):
        for index, item in enumerate(value):
            rows.extend(
                _scalar_lines(
                    item,
                    prefix + "[" + str(index) + "]",
                )
            )

        return rows

    text = _clean(value)

    if text:
        rows.append(
            (
                prefix + ": " + text
            )
            if prefix
            else text
        )

    return rows


class UnifiedMemoryIndex:
    """Rebuildable local retrieval index over trusted JARVIS memory stores.

    The SQLite database is a derived cache, never the source of truth.
    Source memories remain in their existing JSON/JSONL stores.

    This first version deliberately uses deterministic FTS5 lexical
    retrieval. Semantic/vector retrieval can be layered on later without
    changing the authoritative source stores.
    """

    def __init__(
        self,
        path: str | Path = "memory/unified_memory.sqlite3",
    ) -> None:
        self.path = Path(path)

    @staticmethod
    def _connect(
        path: Path,
        *,
        readonly: bool = False,
    ) -> sqlite3.Connection:
        if readonly:
            uri = (
                "file:"
                + path.resolve().as_posix()
                + "?mode=ro"
            )

            conn = sqlite3.connect(
                uri,
                uri=True,
            )
        else:
            conn = sqlite3.connect(
                str(path)
            )

        conn.row_factory = sqlite3.Row

        return conn

    @staticmethod
    def _initialize_schema(
        conn: sqlite3.Connection,
    ) -> None:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;

            CREATE TABLE meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE records(
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX idx_memory_records_source
                ON records(source);

            CREATE INDEX idx_memory_records_kind
                ON records(kind);

            CREATE INDEX idx_memory_records_content_hash
                ON records(content_hash);

            CREATE VIRTUAL TABLE records_fts USING fts5(
                record_id UNINDEXED,
                title,
                text,
                tags,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )

        conn.execute(
            """
            INSERT INTO meta(key, value)
            VALUES('schema_version', ?)
            """,
            (
                SCHEMA_VERSION,
            ),
        )

    @staticmethod
    def _record_id(
        source: str,
        source_id: str,
        kind: str,
    ) -> str:
        return _sha256(
            source
            + "\0"
            + source_id
            + "\0"
            + kind
        )

    @classmethod
    def _insert(
        cls,
        conn: sqlite3.Connection,
        *,
        source: str,
        source_id: str,
        kind: str,
        title: str,
        text: str,
        created_at: str = "",
        metadata: dict[str, Any] | None = None,
        tags: str = "",
    ) -> bool:
        clean_text = _clean(text)

        if not clean_text:
            return False

        clean_title = _clean(title)

        metadata = dict(
            metadata or {}
        )

        record_id = cls._record_id(
            source,
            source_id,
            kind,
        )

        content_hash = _sha256(
            clean_title
            + "\n"
            + clean_text
        )

        try:
            conn.execute(
                """
                INSERT INTO records(
                    id,
                    source,
                    source_id,
                    kind,
                    title,
                    text,
                    created_at,
                    content_hash,
                    metadata_json
                )
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    record_id,
                    source,
                    source_id,
                    kind,
                    clean_title,
                    clean_text,
                    _clean(created_at),
                    content_hash,
                    _stable_json(metadata),
                ),
            )
        except sqlite3.IntegrityError:
            return False

        conn.execute(
            """
            INSERT INTO records_fts(
                record_id,
                title,
                text,
                tags
            )
            VALUES(?,?,?,?)
            """,
            (
                record_id,
                clean_title,
                clean_text,
                _clean(tags),
            ),
        )

        return True

    @staticmethod
    def _source_id(
        row: dict[str, Any],
        *,
        preferred: Iterable[str] = (),
    ) -> str:
        for key in preferred:
            value = _clean(
                row.get(key)
            )

            if value:
                return value

        return _sha256(
            _stable_json(row)
        )

    @classmethod
    def _index_user_profile(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        data = _json_object(
            root
            / "memory"
            / "user_profile.json"
        )

        if not data:
            return 0

        text = "\n".join(
            _scalar_lines(data)
        )

        return int(
            cls._insert(
                conn,
                source="user_profile",
                source_id="owner_profile",
                kind="profile",
                title="OWNER profile",
                text=text,
                metadata={
                    "store":
                        "memory/user_profile.json",
                },
                tags="owner profile",
            )
        )

    @classmethod
    def _index_facts(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        rows = _jsonl_rows(
            root
            / "memory"
            / "facts.jsonl"
        )

        count = 0

        for row in rows:
            fact = _clean(
                row.get("fact")
            )

            if not fact:
                continue

            source_id = cls._source_id(
                row,
                preferred=(
                    "id",
                ),
            )

            count += int(
                cls._insert(
                    conn,
                    source="explicit_fact",
                    source_id=source_id,
                    kind=_clean(
                        row.get("category")
                        or "general"
                    ),
                    title="Explicit OWNER fact",
                    text=fact,
                    created_at=_clean(
                        row.get("timestamp")
                    ),
                    metadata={
                        "category":
                            row.get("category"),
                        "store":
                            "memory/facts.jsonl",
                    },
                    tags=(
                        "owner explicit fact "
                        + _clean(
                            row.get("category")
                        )
                    ),
                )
            )

        return count

    @classmethod
    def _index_context(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        rows = _jsonl_rows(
            root
            / "memory"
            / "context.jsonl"
        )

        count = 0

        for row in rows:
            user = _clean(
                row.get("user")
            )

            assistant = _clean(
                row.get("assistant")
            )

            if not user and not assistant:
                continue

            source_id = cls._source_id(
                row,
                preferred=(
                    "turn_id",
                ),
            )

            route = _clean(
                row.get("route")
            )

            parts = []

            if user:
                parts.append(
                    "OWNER: " + user
                )

            if assistant:
                parts.append(
                    "JARVIS: " + assistant
                )

            count += int(
                cls._insert(
                    conn,
                    source="conversation",
                    source_id=source_id,
                    kind="turn",
                    title=(
                        "Conversation"
                        + (
                            " " + route
                            if route
                            else ""
                        )
                    ),
                    text="\n".join(parts),
                    created_at=_clean(
                        row.get("timestamp")
                    ),
                    metadata={
                        "route":
                            route,
                        "store":
                            "memory/context.jsonl",
                        "turn_id":
                            row.get("turn_id"),
                        "source_content_hash":
                            row.get(
                                "content_hash"
                            ),
                    },
                    tags=(
                        "conversation owner jarvis "
                        + route
                    ),
                )
            )

        return count

    @classmethod
    def _index_graph(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        graph = _json_object(
            root
            / "memory"
            / "memory_graph.json"
        )

        if not graph:
            return 0

        count = 0

        nodes = graph.get(
            "nodes"
        ) or {}

        if isinstance(
            nodes,
            dict,
        ):
            for node_id, row in nodes.items():
                if not isinstance(
                    row,
                    dict,
                ):
                    continue

                label = _clean(
                    row.get("label")
                    or row.get("name")
                    or row.get("value")
                    or node_id
                )

                node_type = _clean(
                    row.get("type")
                    or row.get("kind")
                    or "entity"
                )

                text = "\n".join(
                    _scalar_lines(row)
                )

                count += int(
                    cls._insert(
                        conn,
                        source="memory_graph",
                        source_id=str(
                            node_id
                        ),
                        kind=(
                            "node:"
                            + node_type
                        ),
                        title=label,
                        text=text,
                        created_at=_clean(
                            row.get(
                                "created_at"
                            )
                        ),
                        metadata={
                            "store":
                                "memory/memory_graph.json",
                            "graph_record":
                                "node",
                        },
                        tags=(
                            "memory graph node "
                            + node_type
                        ),
                    )
                )

        edges = graph.get(
            "edges"
        ) or []

        if isinstance(
            edges,
            list,
        ):
            for row in edges:
                if not isinstance(
                    row,
                    dict,
                ):
                    continue

                relation = _clean(
                    row.get("relation")
                    or "relation"
                )

                source_id = _sha256(
                    _stable_json(row)
                )

                text = "\n".join(
                    _scalar_lines(row)
                )

                count += int(
                    cls._insert(
                        conn,
                        source="memory_graph",
                        source_id=source_id,
                        kind="edge",
                        title=relation,
                        text=text,
                        created_at=_clean(
                            row.get(
                                "created_at"
                            )
                        ),
                        metadata={
                            "store":
                                "memory/memory_graph.json",
                            "graph_record":
                                "edge",
                        },
                        tags=(
                            "memory graph relation "
                            + relation
                        ),
                    )
                )

        decisions = graph.get(
            "decisions"
        ) or []

        if isinstance(
            decisions,
            list,
        ):
            for row in decisions:
                if not isinstance(
                    row,
                    dict,
                ):
                    continue

                decision = _clean(
                    row.get("decision")
                )

                if not decision:
                    continue

                source_id = cls._source_id(
                    row,
                    preferred=(
                        "id",
                    ),
                )

                text = decision

                context = _clean(
                    row.get("context")
                )

                if context:
                    text += "\nContext: " + context

                count += int(
                    cls._insert(
                        conn,
                        source="memory_graph",
                        source_id=source_id,
                        kind="decision",
                        title="OWNER decision",
                        text=text,
                        created_at=_clean(
                            row.get(
                                "created_at"
                            )
                        ),
                        metadata={
                            "store":
                                "memory/memory_graph.json",
                            "graph_record":
                                "decision",
                        },
                        tags="memory graph decision",
                    )
                )

        projects = graph.get(
            "projects"
        ) or {}

        if isinstance(
            projects,
            dict,
        ):
            for project_id, row in projects.items():
                if not isinstance(
                    row,
                    dict,
                ):
                    continue

                title = _clean(
                    row.get("name")
                    or project_id
                )

                text = "\n".join(
                    _scalar_lines(row)
                )

                count += int(
                    cls._insert(
                        conn,
                        source="memory_graph",
                        source_id=str(
                            project_id
                        ),
                        kind="project",
                        title=title,
                        text=text,
                        created_at=_clean(
                            row.get(
                                "updated_at"
                            )
                        ),
                        metadata={
                            "store":
                                "memory/memory_graph.json",
                            "graph_record":
                                "project",
                        },
                        tags="memory graph project",
                    )
                )

        return count

    @classmethod
    def _index_personal_model(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        model = _json_object(
            root
            / "memory"
            / "personal_model.json"
        )

        if not model:
            return 0

        count = 0

        active_fields = (
            "preferences",
            "goals",
            "constraints",
            "projects",
            "jarvis_directives",
            "jarvis_learning_goals",
            "owner_learning_goals",
            "time_boundaries",
        )

        for field in active_fields:
            value = model.get(
                field
            )

            if isinstance(
                value,
                list,
            ):
                items = value
            elif isinstance(
                value,
                dict,
            ):
                items = [
                    {
                        "key": key,
                        "value": item,
                    }
                    for key, item
                    in value.items()
                ]
            elif value is None:
                continue
            else:
                items = [
                    value
                ]

            for item in items:
                if isinstance(
                    item,
                    dict,
                ):
                    text = _clean(
                        item.get("statement")
                        or item.get("topic")
                        or item.get("name")
                        or item.get("value")
                    )

                    if not text:
                        text = "\n".join(
                            _scalar_lines(
                                item
                            )
                        )

                    created_at = _clean(
                        item.get("first_seen")
                        or item.get("created_at")
                        or item.get("last_seen")
                    )

                    source_id = (
                        field
                        + ":"
                        + _sha256(
                            _stable_json(
                                item
                            )
                        )
                    )
                else:
                    text = _clean(
                        item
                    )

                    created_at = ""

                    source_id = (
                        field
                        + ":"
                        + _sha256(
                            text
                        )
                    )

                if not text:
                    continue

                count += int(
                    cls._insert(
                        conn,
                        source="personal_model",
                        source_id=source_id,
                        kind=field,
                        title=(
                            "Personal model "
                            + field
                        ),
                        text=text,
                        created_at=created_at,
                        metadata={
                            "store":
                                "memory/personal_model.json",
                            "field":
                                field,
                        },
                        tags=(
                            "personal model "
                            + field
                        ),
                    )
                )

        return count

    @classmethod
    def _index_authorized_learning(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> int:
        rows = _jsonl_rows(
            root
            / "knowledge"
            / "autonomy"
            / "authorized_learning.jsonl"
        )

        count = 0

        for row in rows:
            topic = _clean(
                row.get("topic")
            )

            summary = _clean(
                row.get("summary")
            )

            if not topic and not summary:
                continue

            source_id = cls._source_id(
                row,
                preferred=(
                    "id",
                ),
            )

            source_lines = []

            for source in list(
                row.get("sources")
                or []
            )[:12]:
                if not isinstance(
                    source,
                    dict,
                ):
                    continue

                title = _clean(
                    source.get("title")
                )

                url = _clean(
                    source.get("url")
                )

                if title or url:
                    source_lines.append(
                        (
                            title
                            + " "
                            + url
                        ).strip()
                    )

            text_parts = []

            if topic:
                text_parts.append(
                    "Topic: " + topic
                )

            if summary:
                text_parts.append(
                    summary
                )

            if source_lines:
                text_parts.append(
                    "Sources: "
                    + " | ".join(
                        source_lines
                    )
                )

            count += int(
                cls._insert(
                    conn,
                    source="authorized_learning",
                    source_id=source_id,
                    kind=_clean(
                        row.get(
                            "source_type"
                        )
                        or "authorized_learning"
                    ),
                    title=(
                        topic
                        or "Authorized learning"
                    ),
                    text="\n".join(
                        text_parts
                    ),
                    created_at=_clean(
                        row.get("learned_at")
                        or row.get("timestamp")
                    ),
                    metadata={
                        "store":
                            (
                                "knowledge/autonomy/"
                                "authorized_learning.jsonl"
                            ),
                        "source_type":
                            row.get(
                                "source_type"
                            ),
                        "source_count":
                            row.get(
                                "source_count"
                            ),
                        "confidence":
                            row.get(
                                "confidence"
                            ),
                    },
                    tags=(
                        "authorized learning "
                        + topic
                    ),
                )
            )

        return count

    @classmethod
    def _populate(
        cls,
        conn: sqlite3.Connection,
        root: Path,
    ) -> dict[str, int]:
        counts = {
            "user_profile":
                cls._index_user_profile(
                    conn,
                    root,
                ),

            "explicit_fact":
                cls._index_facts(
                    conn,
                    root,
                ),

            "conversation":
                cls._index_context(
                    conn,
                    root,
                ),

            "memory_graph":
                cls._index_graph(
                    conn,
                    root,
                ),

            "personal_model":
                cls._index_personal_model(
                    conn,
                    root,
                ),

            "authorized_learning":
                cls._index_authorized_learning(
                    conn,
                    root,
                ),
        }

        return counts

    def rebuild(
        self,
        *,
        root: str | Path = ".",
    ) -> dict[str, Any]:
        root_path = Path(
            root
        ).resolve()

        target = (
            self.path
            if self.path.is_absolute()
            else root_path
            / self.path
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        handle = tempfile.NamedTemporaryFile(
            prefix=(
                target.stem
                + "_"
            ),
            suffix=".sqlite3.tmp",
            dir=str(
                target.parent
            ),
            delete=False,
        )

        temp_path = Path(
            handle.name
        )

        handle.close()

        counts: dict[str, int] = {}

        try:
            conn = self._connect(
                temp_path
            )

            try:
                self._initialize_schema(
                    conn
                )

                # INCREMENTAL_SOURCE_REFRESH_V1
                # Capture canonical content before a full rebuild. If any source
                # changes while the temporary database is being populated, the
                # rebuild is rejected and the existing derived cache is preserved.
                rebuild_fingerprints_before = {
                    source_name: self._file_fingerprint(source_path)
                    for source_name, (source_path, _) in self._source_specs(
                        root_path
                    ).items()
                }

                counts = self._populate(
                    conn,
                    root_path,
                )

                rebuild_fingerprints_after = {
                    source_name: self._file_fingerprint(source_path)
                    for source_name, (source_path, _) in self._source_specs(
                        root_path
                    ).items()
                }

                if rebuild_fingerprints_before != rebuild_fingerprints_after:
                    raise RuntimeError(
                        "MEMORY_SOURCE_CHANGED_DURING_REBUILD"
                    )

                for source_name, fingerprint in rebuild_fingerprints_after.items():
                    self._set_meta(
                        conn,
                        "source_fingerprint:" + source_name,
                        fingerprint,
                    )

                conn.execute(
                    """
                    INSERT INTO meta(key, value)
                    VALUES('record_count', ?)
                    """,
                    (
                        str(
                            sum(
                                counts.values()
                            )
                        ),
                    ),
                )

                conn.commit()

            finally:
                conn.close()

            os.replace(
                temp_path,
                target,
            )

        finally:
            if temp_path.exists():
                temp_path.unlink()

        return {
            "ok": True,
            "path": str(
                target
            ),
            "schema_version":
                SCHEMA_VERSION,
            "record_count":
                sum(
                    counts.values()
                ),
            "sources":
                counts,
        }


    @classmethod
    def _source_specs(
        cls,
        root: Path,
    ) -> dict[str, tuple[Path, Any]]:
        """Map derived source names to canonical files and indexers."""
        return {
            "user_profile": (
                root
                / "memory"
                / "user_profile.json",
                cls._index_user_profile,
            ),
            "explicit_fact": (
                root
                / "memory"
                / "facts.jsonl",
                cls._index_facts,
            ),
            "conversation": (
                root
                / "memory"
                / "context.jsonl",
                cls._index_context,
            ),
            "memory_graph": (
                root
                / "memory"
                / "memory_graph.json",
                cls._index_graph,
            ),
            "personal_model": (
                root
                / "memory"
                / "personal_model.json",
                cls._index_personal_model,
            ),
            "authorized_learning": (
                root
                / "knowledge"
                / "autonomy"
                / "authorized_learning.jsonl",
                cls._index_authorized_learning,
            ),
        }

    @staticmethod
    def _file_fingerprint(
        path: Path,
    ) -> str:
        """
        Return a strong fingerprint of canonical source content.

        The SQLite database is derived state. Canonical JSON/JSONL remains
        authoritative, so freshness is based on file bytes, not timestamps.
        """
        if not path.is_file():
            return "missing"

        digest = hashlib.sha256()

        with path.open(
            "rb"
        ) as stream:
            while True:
                chunk = stream.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                digest.update(
                    chunk
                )

        return (
            "sha256:"
            + digest.hexdigest()
        )

    @staticmethod
    def _meta_value(
        conn: sqlite3.Connection,
        key: str,
    ) -> str | None:
        row = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key=?
            """,
            (
                key,
            ),
        ).fetchone()

        if row is None:
            return None

        return str(
            row[0]
        )

    @staticmethod
    def _set_meta(
        conn: sqlite3.Connection,
        key: str,
        value: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO meta(
                key,
                value
            )
            VALUES(?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value
            """,
            (
                str(key),
                str(value),
            ),
        )

    @staticmethod
    def _source_counts(
        conn: sqlite3.Connection,
    ) -> dict[str, int]:
        rows = conn.execute(
            """
            SELECT
                source,
                COUNT(*) AS count
            FROM records
            GROUP BY source
            ORDER BY source
            """
        ).fetchall()

        return {
            str(row["source"]):
                int(row["count"])
            for row in rows
        }

    @classmethod
    def _replace_source(
        cls,
        conn: sqlite3.Connection,
        root: Path,
        source: str,
    ) -> int:
        """
        Transactionally replace one derived source lane.

        records_fts is an independent FTS5 table, so its rows must be
        removed explicitly before the corresponding records rows.
        """
        specs = cls._source_specs(
            root
        )

        if source not in specs:
            raise ValueError(
                "INVALID_MEMORY_SOURCE_FILTER"
            )

        _, indexer = specs[
            source
        ]

        conn.execute(
            """
            DELETE FROM records_fts
            WHERE record_id IN (
                SELECT id
                FROM records
                WHERE source=?
            )
            """,
            (
                source,
            ),
        )

        conn.execute(
            """
            DELETE FROM records
            WHERE source=?
            """,
            (
                source,
            ),
        )

        return int(
            indexer(
                conn,
                root,
            )
        )

    def refresh_sources(
        self,
        *,
        root: str | Path = ".",
        sources: (
            list[str]
            | tuple[str, ...]
            | set[str]
            | str
            | None
        ) = None,
    ) -> dict[str, Any]:
        """
        Refresh only canonical sources whose content fingerprint changed.

        This method never changes canonical memory. Requested source
        replacements share one SQLite transaction and roll back together.
        """
        root_path = Path(
            root
        ).resolve()

        target = (
            self.path
            if self.path.is_absolute()
            else root_path
            / self.path
        )

        if not target.is_file():
            return {
                "ok": False,
                "error":
                    "MEMORY_INDEX_NOT_AVAILABLE",
                "path": str(
                    target
                ),
            }

        specs = self._source_specs(
            root_path
        )

        if sources is None:
            requested = tuple(
                specs.keys()
            )

        else:
            raw_sources = (
                (sources,)
                if isinstance(
                    sources,
                    str,
                )
                else tuple(
                    sources
                )
            )

            requested = tuple(
                dict.fromkeys(
                    str(item or "").strip()
                    for item in raw_sources
                    if str(
                        item
                        or ""
                    ).strip()
                )
            )

        invalid = sorted(
            set(
                requested
            )
            - set(
                specs
            )
        )

        if invalid:
            return {
                "ok": False,
                "error":
                    "INVALID_MEMORY_SOURCE_FILTER",
                "invalid_sources":
                    invalid,
            }

        conn = self._connect(
            target,
            readonly=True,
        )

        try:
            schema = self._meta_value(
                conn,
                "schema_version",
            )

            if schema != str(
                SCHEMA_VERSION
            ):
                return {
                    "ok": False,
                    "error":
                        "MEMORY_INDEX_SCHEMA_MISMATCH",
                    "expected":
                        str(
                            SCHEMA_VERSION
                        ),
                    "actual":
                        str(
                            schema
                            or ""
                        ),
                }

            record_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM records
                    """
                ).fetchone()[0]
            )

            existing_counts = (
                self._source_counts(
                    conn
                )
            )

            stored_fingerprints = {
                source:
                    self._meta_value(
                        conn,
                        (
                            "source_fingerprint:"
                            + source
                        ),
                    )
                for source in requested
            }

        finally:
            conn.close()

        if not requested:
            return {
                "ok": True,
                "refreshed": False,
                "changed_sources": [],
                "unchanged_sources": [],
                "record_count":
                    record_count,
                "sources":
                    existing_counts,
            }

        observed_once = {
            source:
                self._file_fingerprint(
                    specs[source][0]
                )
            for source in requested
        }

        observed_twice = {
            source:
                self._file_fingerprint(
                    specs[source][0]
                )
            for source in requested
        }

        stale = [
            source
            for source in requested
            if (
                observed_once[
                    source
                ]
                != observed_twice[
                    source
                ]
                or stored_fingerprints[
                    source
                ]
                != observed_twice[
                    source
                ]
            )
        ]

        if not stale:
            return {
                "ok": True,
                "refreshed": False,
                "changed_sources": [],
                "unchanged_sources":
                    list(
                        requested
                    ),
                "record_count":
                    record_count,
                "sources":
                    existing_counts,
            }

        conn = self._connect(
            target
        )

        changed_sources: list[str] = []
        unchanged_sources: list[str] = []

        try:
            conn.execute(
                "BEGIN IMMEDIATE"
            )

            schema = self._meta_value(
                conn,
                "schema_version",
            )

            if schema != str(
                SCHEMA_VERSION
            ):
                raise RuntimeError(
                    "MEMORY_INDEX_SCHEMA_MISMATCH"
                )

            for source in requested:
                source_path = specs[
                    source
                ][0]

                before = (
                    self._file_fingerprint(
                        source_path
                    )
                )

                stored = self._meta_value(
                    conn,
                    (
                        "source_fingerprint:"
                        + source
                    ),
                )

                if stored == before:
                    unchanged_sources.append(
                        source
                    )

                    continue

                self._replace_source(
                    conn,
                    root_path,
                    source,
                )

                after = (
                    self._file_fingerprint(
                        source_path
                    )
                )

                if after != before:
                    raise RuntimeError(
                        (
                            "MEMORY_SOURCE_CHANGED_"
                            "DURING_REFRESH:"
                        )
                        + source
                    )

                self._set_meta(
                    conn,
                    (
                        "source_fingerprint:"
                        + source
                    ),
                    after,
                )

                changed_sources.append(
                    source
                )

            record_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM records
                    """
                ).fetchone()[0]
            )

            self._set_meta(
                conn,
                "record_count",
                str(
                    record_count
                ),
            )

            counts = self._source_counts(
                conn
            )

            conn.commit()

        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()

            return {
                "ok": False,
                "error":
                    (
                        "MEMORY_SOURCE_REFRESH_FAILED:"
                        + type(exc).__name__
                    ),
                "reason":
                    str(exc),
                "changed_sources": [],
            }

        finally:
            conn.close()

        return {
            "ok": True,
            "refreshed":
                bool(
                    changed_sources
                ),
            "changed_sources":
                changed_sources,
            "unchanged_sources":
                unchanged_sources,
            "record_count":
                record_count,
            "sources":
                counts,
        }

    @staticmethod
    def _fts_query(
        query: str,
    ) -> str:
        normalized = _clean(
            query
        )

        tokens = re.findall(
            r"[\w.-]+",
            normalized,
            flags=re.UNICODE,
        )

        unique: list[str] = []

        seen = set()

        for token in tokens:
            clean = token.strip(
                "._-"
            )

            if len(clean) < 2:
                continue

            lowered = clean.lower()

            if lowered in seen:
                continue

            seen.add(
                lowered
            )

            unique.append(
                clean
            )

            if len(unique) >= 12:
                break

        return " OR ".join(
            '"'
            + token.replace(
                '"',
                '""',
            )
            + '"'
            for token in unique
        )

    # SOURCE_AWARE_MEMORY_RERANK_V1
    @staticmethod
    def _source_boost(
        source: str,
    ) -> float:
        """
        Deterministic retrieval preference for durable memory sources.

        This affects retrieval ranking only. It does not make retrieved
        memory authoritative over the OWNER, semantic resolver, policy,
        authorization or ToolRegistry.
        """
        weights = {
            "user_profile": 0.45,
            "explicit_fact": 0.40,
            "personal_model": 0.35,
            "memory_graph": 0.30,
            "authorized_learning": 0.12,
            "conversation": 0.00,
        }

        return float(
            weights.get(
                str(source or ""),
                0.0,
            )
        )

    @classmethod
    def _rerank_candidates(
        cls,
        rows: list[dict[str, Any]],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Rerank FTS candidates while preserving provenance.

        Exact duplicates are collapsed only inside the same source.
        The same content appearing in two distinct memory sources remains
        visible as separate provenance.
        """
        cap = max(
            1,
            min(
                int(limit),
                50,
            ),
        )

        if not rows:
            return []

        # The SQL candidate order is already BM25-first. Preserve that
        # information as a deterministic lexical score instead of allowing
        # corpus volume alone to determine the final top-N.
        deduped: list[dict[str, Any]] = []

        seen: set[
            tuple[str, str]
        ] = set()

        for row in rows:
            item = dict(row)

            source_name = str(
                item.get("source")
                or ""
            )

            content_hash = str(
                item.get("content_hash")
                or ""
            ).strip()

            identity = (
                content_hash
                or str(
                    item.get("id")
                    or ""
                )
            )

            key = (
                source_name,
                identity,
            )

            if identity and key in seen:
                continue

            if identity:
                seen.add(
                    key
                )

            deduped.append(
                item
            )

        if not deduped:
            return []

        total = len(
            deduped
        )

        denominator = max(
            1,
            total - 1,
        )

        # created_at is stored in sortable ISO form. The recency component
        # is deliberately small: freshness helps break comparable lexical
        # matches but cannot erase source quality or lexical relevance.
        recency_order = sorted(
            range(total),
            key=lambda index: str(
                deduped[index].get(
                    "created_at"
                )
                or ""
            ),
            reverse=True,
        )

        recency_position = {
            index: position
            for position, index
            in enumerate(
                recency_order
            )
        }

        ranked: list[
            dict[str, Any]
        ] = []

        for position, row in enumerate(
            deduped
        ):
            lexical_score = (
                1.0
                - (
                    position
                    / denominator
                )
            )

            recency_score = (
                1.0
                - (
                    recency_position[
                        position
                    ]
                    / denominator
                )
            )

            source_boost = (
                cls._source_boost(
                    str(
                        row.get(
                            "source"
                        )
                        or ""
                    )
                )
            )

            retrieval_score = (
                lexical_score
                + source_boost
                + (
                    0.05
                    * recency_score
                )
            )

            item = dict(
                row
            )

            item[
                "source_boost"
            ] = round(
                source_boost,
                6,
            )

            item[
                "retrieval_score"
            ] = round(
                retrieval_score,
                6,
            )

            ranked.append(
                item
            )

        def rank_key(
            item: dict[str, Any],
        ):
            try:
                raw_rank = float(
                    item.get("rank")
                    or 0.0
                )
            except Exception:
                raw_rank = 0.0

            return (
                float(
                    item.get(
                        "retrieval_score"
                    )
                    or 0.0
                ),
                -raw_rank,
                str(
                    item.get(
                        "created_at"
                    )
                    or ""
                ),
                str(
                    item.get(
                        "id"
                    )
                    or ""
                ),
            )

        ranked.sort(
            key=rank_key,
            reverse=True,
        )

        # First pass prevents one high-volume source from occupying every
        # early slot when other matching memory sources are available.
        # Second pass fills the requested limit, so conversation-only
        # queries do not lose recall depth.
        first_pass_source_cap = (
            2
            if cap >= 3
            else cap
        )

        selected: list[
            dict[str, Any]
        ] = []

        selected_ids: set[
            str
        ] = set()

        source_counts: dict[
            str,
            int,
        ] = {}

        for item in ranked:
            source_name = str(
                item.get("source")
                or ""
            )

            if (
                source_counts.get(
                    source_name,
                    0,
                )
                >= first_pass_source_cap
            ):
                continue

            selected.append(
                item
            )

            selected_ids.add(
                str(
                    item.get("id")
                    or ""
                )
            )

            source_counts[
                source_name
            ] = (
                source_counts.get(
                    source_name,
                    0,
                )
                + 1
            )

            if len(selected) >= cap:
                break

        if len(selected) < cap:
            for item in ranked:
                row_id = str(
                    item.get("id")
                    or ""
                )

                if row_id in selected_ids:
                    continue

                selected.append(
                    item
                )

                selected_ids.add(
                    row_id
                )

                if len(selected) >= cap:
                    break

        return selected[:cap]

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        sources: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> dict[str, Any]:
        path = self.path

        if not path.is_absolute():
            path = Path.cwd() / path

        if not path.is_file():
            return {
                "ok": False,
                "error":
                    "MEMORY_INDEX_NOT_AVAILABLE",
                "results": [],
            }

        fts_query = self._fts_query(
            query
        )

        if not fts_query:
            return {
                "ok": True,
                "query": query,
                "results": [],
            }

        cap = max(
            1,
            min(
                int(limit),
                50,
            ),
        )

        active_sources = {
            "user_profile",
            "explicit_fact",
            "conversation",
            "memory_graph",
            "personal_model",
            "authorized_learning",
        }

        source_filter = None

        if sources is not None:
            requested_sources = {
                str(value or "").strip()
                for value in sources
                if str(value or "").strip()
            }

            invalid_sources = sorted(
                requested_sources
                - active_sources
            )

            if invalid_sources:
                return {
                    "ok": False,
                    "error":
                        "INVALID_MEMORY_SOURCE_FILTER",
                    "invalid_sources":
                        invalid_sources,
                    "results": [],
                }

            if not requested_sources:
                return {
                    "ok": True,
                    "query": query,
                    "sources": [],
                    "results": [],
                }

            source_filter = sorted(
                requested_sources
            )

        # Retrieve a substantially larger lexical candidate pool before
        # source-aware reranking. This prevents the 1332-row conversation
        # source from excluding smaller durable stores before reranking can
        # compare them.
        candidate_cap = min(
            500,
            max(
                120,
                cap * 20,
            ),
        )

        sql = """
            SELECT
                r.id,
                r.source,
                r.source_id,
                r.kind,
                r.title,
                r.text,
                r.created_at,
                r.content_hash,
                r.metadata_json,
                bm25(records_fts) AS rank,
                snippet(
                    records_fts,
                    2,
                    '[',
                    ']',
                    '...',
                    24
                ) AS snippet
            FROM records_fts
            JOIN records AS r
              ON r.id = records_fts.record_id
            WHERE records_fts MATCH ?
        """

        parameters: list[Any] = [
            fts_query
        ]

        if source_filter is not None:
            placeholders = ",".join(
                "?"
                for _ in source_filter
            )

            sql += (
                " AND r.source IN ("
                + placeholders
                + ")"
            )

            parameters.extend(
                source_filter
            )

        sql += """
            ORDER BY rank ASC, r.created_at DESC
            LIMIT ?
        """

        parameters.append(
            candidate_cap
        )

        conn = self._connect(
            path,
            readonly=True,
        )

        try:
            raw_rows = conn.execute(
                sql,
                tuple(parameters),
            ).fetchall()

        finally:
            conn.close()

        candidates: list[
            dict[str, Any]
        ] = []

        for row in raw_rows:
            candidates.append({
                key: row[key]
                for key in row.keys()
            })

        selected = (
            self._rerank_candidates(
                candidates,
                limit=cap,
            )
        )

        results = []

        for row in selected:
            try:
                metadata = json.loads(
                    row.get(
                        "metadata_json"
                    )
                    or "{}"
                )

            except Exception:
                metadata = {}

            results.append(
                {
                    "id":
                        row.get("id"),
                    "source":
                        row.get("source"),
                    "source_id":
                        row.get("source_id"),
                    "kind":
                        row.get("kind"),
                    "title":
                        row.get("title"),
                    "text":
                        row.get("text"),
                    "snippet":
                        row.get("snippet"),
                    "created_at":
                        row.get("created_at"),
                    "content_hash":
                        row.get(
                            "content_hash"
                        ),
                    "rank":
                        row.get("rank"),
                    "source_boost":
                        row.get(
                            "source_boost"
                        ),
                    "retrieval_score":
                        row.get(
                            "retrieval_score"
                        ),
                    "metadata":
                        metadata,
                }
            )

        return {
            "ok": True,
            "query": query,
            "fts_query": fts_query,
            "candidate_count":
                len(candidates),
            "sources":
                source_filter,
            "results":
                results,
        }

    def status(
        self,
    ) -> dict[str, Any]:
        path = self.path

        if not path.is_absolute():
            path = Path.cwd() / path

        if not path.is_file():
            return {
                "ok": True,
                "exists": False,
                "path": str(path),
                "schema_version":
                    SCHEMA_VERSION,
                "record_count": 0,
                "sources": {},
            }

        conn = self._connect(
            path,
            readonly=True,
        )

        try:
            record_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM records
                    """
                ).fetchone()[0]
            )

            rows = conn.execute(
                """
                SELECT source, COUNT(*) AS count
                FROM records
                GROUP BY source
                ORDER BY source
                """
            ).fetchall()

            schema_row = conn.execute(
                """
                SELECT value
                FROM meta
                WHERE key='schema_version'
                """
            ).fetchone()

        finally:
            conn.close()

        return {
            "ok": True,
            "exists": True,
            "path": str(path),
            "schema_version": (
                str(schema_row[0])
                if schema_row
                else ""
            ),
            "record_count":
                record_count,
            "sources": {
                str(row["source"]):
                    int(row["count"])
                for row in rows
            },
        }
