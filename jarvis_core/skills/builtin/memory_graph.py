from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any
import json
import re
import unicodedata

from jarvis_core.security.policy import RiskLevel
from jarvis_core.skills.base import Skill, SkillContext, SkillTool


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _id(kind: str, label: str) -> str:
    slug = sha256(f"{kind}:{_norm(label)}".encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{slug}"


class MemoryGraphStore:
    """Local graph layered on top of explicit user-memory writes.

    The graph does not scrape ordinary conversation. It receives facts only
    after the existing memory boundary accepted an explicit remember action, or
    through an explicit graph write tool.
    """

    def __init__(self, path: str | Path = "memory/memory_graph.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self.path.exists():
            self._save(self._empty())

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": 1,
            "nodes": {},
            "edges": [],
            "decisions": [],
            "projects": {},
            "updated_at": None,
        }

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else self._empty()
        except Exception:
            return self._empty()

    def _save(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _now()
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _upsert_node(data: dict[str, Any], kind: str, label: str, **attrs: Any) -> str:
        node_id = _id(kind, label)
        nodes = data.setdefault("nodes", {})
        row = nodes.setdefault(node_id, {
            "id": node_id,
            "kind": kind,
            "label": str(label).strip(),
            "attributes": {},
            "created_at": _now(),
        })
        row["label"] = str(label).strip() or row.get("label")
        row.setdefault("attributes", {}).update({k: v for k, v in attrs.items() if v not in (None, "")})
        row["updated_at"] = _now()
        return node_id

    @staticmethod
    def _add_edge(data: dict[str, Any], source: str, relation: str, target: str, **attrs: Any) -> None:
        relation = str(relation or "RELATED_TO").strip().upper()[:80]
        edges = data.setdefault("edges", [])
        for row in edges:
            if row.get("source") == source and row.get("relation") == relation and row.get("target") == target:
                row.setdefault("attributes", {}).update({k: v for k, v in attrs.items() if v not in (None, "")})
                row["updated_at"] = _now()
                return
        edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            "attributes": {k: v for k, v in attrs.items() if v not in (None, "")},
            "created_at": _now(),
        })

    def ingest_explicit_fact(self, fact: str, category: str = "general") -> dict[str, Any]:
        text = str(fact or "").strip()
        if not text:
            return {"ok": False, "error": "EMPTY_FACT"}
        with self._lock:
            data = self._load()
            owner = self._upsert_node(data, "person", "OWNER", role="owner")
            fact_node = self._upsert_node(data, "fact", text, category=str(category or "general"))
            self._add_edge(data, owner, "HAS_EXPLICIT_FACT", fact_node, category=category)

            # Deterministic relationship extraction for the most useful common
            # personal facts. This is not an inference engine: relations are
            # created only when the fact literally states them.
            normalized = _norm(text)
            patterns = [
                (r"(?:minha|a minha) (?:mulher|esposa|companheira) (?:se chama|chama-se|e|é) ([^,.;]+)", "PARTNER"),
                (r"(?:meu|o meu) (?:marido|esposo|companheiro) (?:se chama|chama-se|e|é) ([^,.;]+)", "PARTNER"),
                (r"(?:minha|a minha) filha (?:se chama|chama-se|e|é) ([^,.;]+)", "CHILD"),
                (r"(?:meu|o meu) filho (?:se chama|chama-se|e|é) ([^,.;]+)", "CHILD"),
            ]
            extracted: list[dict[str, Any]] = []
            # Run against original text case-insensitively to preserve names.
            for pattern, relation in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if not match:
                    continue
                label = match.group(1).strip(" .,-")[:160]
                # Remove trailing birth clause when present.
                label = re.split(r"\s+(?:e\s+)?(?:nasceu|nascida|nascido)\b", label, maxsplit=1, flags=re.IGNORECASE)[0].strip()
                if len(label) < 2:
                    continue
                person = self._upsert_node(data, "person", label)
                self._add_edge(data, owner, relation, person, source_fact=text[:500])
                birth = re.search(
                    r"(?:nasceu|nascida|nascido)(?:\s+em|\s+a)?\s+([^,.;]+)",
                    text,
                    flags=re.IGNORECASE,
                )
                if birth:
                    data["nodes"][person].setdefault("attributes", {})["birth_date_text"] = birth.group(1).strip()[:120]
                extracted.append({"entity": label, "relation": relation})

            # Explicit project wording becomes a project node/state without
            # pretending that every goal is a project.
            project_match = re.search(r"(?:projeto|projecto)\s+([^,:;]+)", text, flags=re.IGNORECASE)
            if project_match:
                project_label = project_match.group(1).strip()[:160]
                project = self._upsert_node(data, "project", project_label)
                self._add_edge(data, owner, "OWNS_PROJECT", project, source_fact=text[:500])
                extracted.append({"entity": project_label, "relation": "OWNS_PROJECT"})

            self._save(data)
            return {"ok": True, "fact_node": fact_node, "extracted": extracted}

    def relate(self, subject: str, relation: str, object: str) -> dict[str, Any]:
        if not all(str(x or "").strip() for x in (subject, relation, object)):
            return {"ok": False, "error": "INVALID_RELATION"}
        with self._lock:
            data = self._load()
            source = self._upsert_node(data, "entity", subject)
            target = self._upsert_node(data, "entity", object)
            self._add_edge(data, source, relation, target, explicit=True)
            self._save(data)
        return {"ok": True, "source": source, "relation": str(relation).upper(), "target": target}

    def remember_decision(self, decision: str, context: str = "") -> dict[str, Any]:
        value = str(decision or "").strip()
        if not value:
            return {"ok": False, "error": "EMPTY_DECISION"}
        with self._lock:
            data = self._load()
            row = {
                "id": _id("decision", value + _now()),
                "decision": value[:2000],
                "context": str(context or "")[:2000],
                "created_at": _now(),
            }
            data.setdefault("decisions", []).append(row)
            data["decisions"] = data["decisions"][-200:]
            self._save(data)
        return {"ok": True, "stored": row}

    def remember_project(self, project: str, state: str, next_step: str = "") -> dict[str, Any]:
        name = str(project or "").strip()
        if not name:
            return {"ok": False, "error": "EMPTY_PROJECT"}
        with self._lock:
            data = self._load()
            node = self._upsert_node(data, "project", name, state=str(state or "")[:1000], next_step=str(next_step or "")[:1000])
            data.setdefault("projects", {})[node] = {
                "name": name,
                "state": str(state or "")[:2000],
                "next_step": str(next_step or "")[:2000],
                "updated_at": _now(),
            }
            self._save(data)
        return {"ok": True, "project": data["projects"][node], "node": node}

    def recall(self, query: str = "", limit: int = 20) -> dict[str, Any]:
        data = self._load()
        terms = {word for word in _norm(query).split() if len(word) >= 3}
        nodes = list((data.get("nodes") or {}).values())
        edges = list(data.get("edges") or [])
        decisions = list(data.get("decisions") or [])
        projects = list((data.get("projects") or {}).values())
        if terms:
            def score(value: Any) -> int:
                hay = _norm(json.dumps(value, ensure_ascii=False))
                return sum(1 for term in terms if term in hay)
            nodes = [row for row in nodes if score(row)]
            edges = [row for row in edges if score(row)]
            decisions = [row for row in decisions if score(row)]
            projects = [row for row in projects if score(row)]
        cap = max(1, min(int(limit), 50))
        return {
            "ok": True,
            "query": query,
            "nodes": nodes[:cap],
            "edges": edges[:cap],
            "decisions": decisions[-cap:],
            "projects": projects[:cap],
        }

    def status(self) -> dict[str, Any]:
        data = self._load()
        return {
            "ok": True,
            "path": str(self.path),
            "nodes": len(data.get("nodes") or {}),
            "edges": len(data.get("edges") or []),
            "decisions": len(data.get("decisions") or []),
            "projects": len(data.get("projects") or {}),
            "updated_at": data.get("updated_at"),
        }


# MEMORY_GRAPH_PATH_ISOLATION_V1
# Stores are cached by resolved path. A custom/test graph can therefore
# never silently alias the canonical runtime graph because another path
# happened to initialize the old process-wide singleton first.
_GRAPH_CACHE_LOCK = RLock()
_GRAPHS: dict[str, MemoryGraphStore] = {}


def _graph_cache_key(
    path: str | Path,
) -> str:
    return str(
        Path(path)
        .expanduser()
        .resolve()
    )


def memory_graph(
    path: str | Path = "memory/memory_graph.json",
) -> MemoryGraphStore:
    requested = Path(path)

    key = _graph_cache_key(
        requested
    )

    with _GRAPH_CACHE_LOCK:
        store = _GRAPHS.get(
            key
        )

        if store is None:
            store = MemoryGraphStore(
                requested
            )

            _GRAPHS[
                key
            ] = store

        return store


def ingest_explicit_memory_fact(
    fact: str,
    category: str = "general",
    *,
    path: str | Path = "memory/memory_graph.json",
) -> dict[str, Any]:
    return memory_graph(
        path
    ).ingest_explicit_fact(
        fact,
        category,
    )



class MemoryGraphSkill(Skill):
    skill_id = "memory_graph"
    name = "Long-Term Memory Graph"
    version = "1.0.0"
    description = "Relational memory for people, projects, decisions and explicit facts."

    def __init__(self, context: SkillContext) -> None:
        super().__init__(context)
        self.store = memory_graph(getattr(context.settings, "memory_graph_path", "memory/memory_graph.json"))
        context.services["memory_graph"] = self.store

    def tools(self) -> list[SkillTool]:
        markers = ("memória", "memoria", "recorda", "lembra", "projeto", "projecto", "decisão", "decisao", "relação", "relacao", "minha mulher", "família", "familia")
        return [
            SkillTool("get_memory_graph_status", "Read long-term relational memory statistics.", self.store.status, {"type":"object","properties":{}}, RiskLevel.READ_ONLY, markers),
            SkillTool("recall_memory_graph", "Recall relational memory about people, projects, decisions and explicit facts.", self.store.recall, {"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":50}}}, RiskLevel.READ_ONLY, markers),
            SkillTool("remember_project_state", "Persist an explicitly requested project state and next step in local relational memory.", self.store.remember_project, {"type":"object","properties":{"project":{"type":"string"},"state":{"type":"string"},"next_step":{"type":"string"}},"required":["project","state"]}, RiskLevel.LOW, markers),
            SkillTool("remember_decision", "Persist an explicitly requested decision and its context in local relational memory.", self.store.remember_decision, {"type":"object","properties":{"decision":{"type":"string"},"context":{"type":"string"}},"required":["decision"]}, RiskLevel.LOW, markers),
            SkillTool("relate_memory_entities", "Persist an explicit relation between two named entities in local memory.", self.store.relate, {"type":"object","properties":{"subject":{"type":"string"},"relation":{"type":"string"},"object":{"type":"string"}},"required":["subject","relation","object"]}, RiskLevel.LOW, markers),
        ]

    def status(self) -> dict[str, Any]:
        data = super().status(); data["service"] = self.store.status(); return data


def create_skill(context: SkillContext) -> Skill:
    return MemoryGraphSkill(context)
