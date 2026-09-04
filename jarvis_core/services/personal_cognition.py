from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
import json
import re
import unicodedata

from jarvis_core.services.agenda import agenda_store
from jarvis_core.services.context_store import context_store
from jarvis_core.services.cyber_knowledge import cyber_vault


SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_ -]?key|token|secret|password|senha|passphrase)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)

EXPLICIT_PATTERNS = (
    ("preference", re.compile(r"(?i)\b(?:eu\s+)?(?:prefiro|gosto de|gosto mais de)\s+(.{3,180}?)(?:[.!?]|$)")),
    ("constraint", re.compile(r"(?i)\b(?:eu\s+)?(?:não quero|nao quero|não gosto de|nao gosto de|evita(?:r)?|quero evitar)\s+(.{3,180}?)(?:[.!?]|$)")),
    ("goal", re.compile(r"(?i)\b(?:o meu objetivo é|o meu objetivo e|quero|pretendo|gostava de)\s+(.{3,220}?)(?:[.!?]|$)")),
    ("project", re.compile(r"(?i)\b(?:o projeto|projeto|estou a fazer|estamos a fazer|estou a construir|estamos a construir)\s+(.{3,220}?)(?:[.!?]|$)")),
)

DEFAULT_TIME_BOUNDARIES = {
    "morning": "06:00",
    "afternoon": "12:00",
    "night": "20:00",
}

TIME_BOUNDARY_LABELS = {
    "manha": "morning",
    "tarde": "afternoon",
    "noite": "night",
    "noturna": "night",
    "noturno": "night",
}


def _extract_time_boundary(value: str) -> tuple[str, str] | None:
    normalized = _norm(value)
    match = re.search(
        r"\b(manha|tarde|noite|noturna|noturno)\s+"
        r"(?:comeca|inicia)\s+(?:as|a partir das)\s+"
        r"([01]?\d|2[0-3])(?:\s+([0-5]\d))?\b",
        normalized,
    )
    if not match:
        return None
    period = TIME_BOUNDARY_LABELS[match.group(1)]
    hour = int(match.group(2))
    minute = int(match.group(3) or 0)
    return period, f"{hour:02d}:{minute:02d}"


STYLE_PREFERENCE_PREFIXES = (
    "que respondas",
    "que fales",
    "que escrevas",
    "que sejas",
    "que uses",
    "que me trates",
    "que tu des",
    "que dês",
    "que des",
    "que o jarvis responda",
    "que jarvis responda",
    "que o jarvis fale",
    "que jarvis fale",
)


def _looks_like_style_preference(
    statement: str,
) -> bool:
    normalized = _norm(statement)
    return any(
        normalized.startswith(
            _norm(prefix)
        )
        for prefix in STYLE_PREFERENCE_PREFIXES
    )


JARVIS_LEARNING_DIRECTIVE_PATTERNS = (
    re.compile(r"(?i)\bquero\s+que\s+(?:tu\s+)?aprendas\b"),
    re.compile(r"(?i)\bquero\s+que\s+(?:tu\s+)?estudes\b"),
    re.compile(r"(?i)^\s*que\s+(?:tu\s+)?aprendas\b"),
    re.compile(r"(?i)^\s*que\s+(?:tu\s+)?estudes\b"),
    re.compile(r"(?i)\b(?:jarvis[,;:]?\s*)?(?:aprende|estuda)\s+(?:tudo\s+)?(?:sobre\s+)?"),
)


def _looks_like_jarvis_learning_directive(statement: str) -> bool:
    """True when the OWNER is assigning a learning target to JARVIS.

    These phrases describe what JARVIS should study; they are not evidence that
    the OWNER personally likes, studies or is passionate about the same topic.
    """
    raw = str(statement or "").strip()
    return bool(raw) and any(pattern.search(raw) for pattern in JARVIS_LEARNING_DIRECTIVE_PATTERNS)


JARVIS_DIRECTIVE_RE = re.compile(
    r"(?i)^\s*que\s+(?:tu\s+)?(?:memorizes|guardes|recordes|lembres|estejas|tenhas|facas|faças|"
    r"penses|decidas|perguntes|uses|utilizes|respondas|fales|escrevas|sejas|des|dês|abras|feches)\b"
)


def _looks_like_jarvis_directive(statement: str) -> bool:
    raw = str(statement or "").strip()
    return bool(raw) and bool(JARVIS_DIRECTIVE_RE.search(raw))


def _looks_like_transient_goal(statement: str) -> bool:
    normalized = _norm(statement)
    transient = (
        "ir dormir", "dormir", "vou dormir", "quero ir dormir",
        "apenas conversar contigo", "so conversar contigo", "só conversar contigo",
        "conversar contigo apenas",
    )
    return normalized in {_norm(item) for item in transient}


def _looks_like_owner_learning_goal(statement: str) -> bool:
    normalized = _norm(statement)
    return bool(re.match(r"^(?:aprender|estudar|aprofundar|melhorar conhecimentos? em)\b", normalized))


TOPIC_TERMS = {
    "jarvis": ("jarvis",),
    "cybersecurity": (
        "cibersegurança", "ciberseguranca", "cybersecurity",
        "segurança informática", "seguranca informatica",
        "firewall", "defender", "mitre", "cisa", "cve",
    ),
    "network": (
        "rede", "listener", "listeners", "porta", "tcp", "udp",
        "router", "5g", "wifi", "wi-fi",
    ),
    "career": (
        "emprego", "candidatura", "entrevista", "vaga", "salário",
        "salario", "trabalho",
    ),
    "automotive": (
        "automóvel", "automovel", "carro", "cupra", "frota", "oficina",
    ),
    "technology": (
        "pc", "windows", "python", "rtx", "gpu", "cpu", "monitor",
    ),
    "investing": (
        "etf", "etfs", "ações", "acoes", "investimento", "investir",
    ),
}

SENSITIVE_INFERENCE_MARKERS = (
    "diagnóstico", "diagnostico", "doença", "doenca", "medicação",
    "medicacao", "religião", "religiao", "partido", "orientação sexual",
    "orientacao sexual", "crime", "processo criminal",
)


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _redact_secrets(text: str) -> tuple[str, bool]:
    value = str(text or "")
    changed = False
    for pattern in SECRET_PATTERNS:
        new = pattern.sub("[SEGREDO REDIGIDO]", value)
        if new != value:
            changed = True
        value = new
    return value, changed


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default)
    except Exception:
        return dict(default)


class PersonalCognitionStore:
    """Local user model + functional self model; not subjective consciousness."""

    def __init__(self, memory_dir: str | Path = "memory"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.model_path = self.memory_dir / "personal_model.json"
        self.observations_path = self.memory_dir / "personal_observations.jsonl"
        self.state_path = self.memory_dir / "cognition_state.json"
        self.self_path = self.memory_dir / "self_model.json"
        self._lock = RLock()

        if not self.model_path.exists():
            self._save_model({
                "interaction_count": 0,
                "preferences": [],
                "goals": [],
                "constraints": [],
                "projects": [],
                "jarvis_learning_goals": [],
                "owner_learning_goals": [],
                "jarvis_directives": [],
                "discarded_legacy_goals": [],
                "topic_counts": {},
                "recent_topics": [],
                "time_boundaries": {},
                "last_updated": None,
            })

        if not self.state_path.exists():
            self._save_state({
                "learning_enabled": True,
                "proactive_enabled": True,
                "proactive_speech_enabled": True,
                "last_interaction_at": None,
                "last_proactive_at": None,
                "proactive_history": [],
                "pending_insights": [],
                "created_at": _iso(),
            })

        self._repair_style_preferences()
        self._repair_jarvis_learning_directives()
        self._repair_owner_goal_contamination()
        self._refresh_self_model()


    def _repair_style_preferences(
        self,
    ) -> dict[str, Any]:
        model = self.model()
        goals = list(model.get("goals") or [])
        preferences = list(
            model.get("preferences")
            or []
        )

        existing = {
            _norm(row.get("statement") or "")
            for row in preferences
        }
        kept = []
        moved = []

        for row in goals:
            statement = str(
                row.get("statement")
                or ""
            ).strip()
            if (
                statement
                and _looks_like_style_preference(
                    statement
                )
            ):
                key = _norm(statement)
                if key not in existing:
                    migrated = dict(row)
                    migrated["migrated_from"] = "goal"
                    migrated["migration_reason"] = (
                        "interaction_style_preference"
                    )
                    preferences.append(migrated)
                    existing.add(key)
                moved.append(statement)
            else:
                kept.append(row)

        if moved:
            model["goals"] = kept
            model["preferences"] = preferences[-40:]
            model["last_updated"] = _iso()
            self._save_model(model)

            moved_norm = {
                _norm(item)
                for item in moved
            }
            state = self.state()
            repaired_pending = []
            for row in list(
                state.get("pending_insights")
                or []
            ):
                if (
                    row.get("category") == "goal"
                    and _norm(
                        row.get("statement")
                        or ""
                    ) in moved_norm
                ):
                    item = dict(row)
                    item["category"] = "preference"
                    repaired_pending.append(item)
                else:
                    repaired_pending.append(row)
            state["pending_insights"] = repaired_pending[-20:]
            self._save_state(state)

        return {
            "ok": True,
            "moved": moved,
            "moved_count": len(moved),
        }

    def _repair_jarvis_learning_directives(self) -> dict[str, Any]:
        """Move old assistant-directed learning goals out of OWNER traits.

        Earlier 0.27.8 builds could classify "quero que tu aprendas X" as an
        OWNER goal.  Preserve the record, but move it to a separate JARVIS
        learning-objective bucket so it cannot be used as evidence of the
        OWNER's interests or passions.
        """
        model = self.model()
        learning_goals = list(model.get("jarvis_learning_goals") or [])
        existing = {_norm(row.get("topic") or row.get("statement") or "") for row in learning_goals}
        moved: list[str] = []

        for bucket_name in ("goals", "preferences", "projects"):
            kept = []
            for row in list(model.get(bucket_name) or []):
                statement = str(row.get("statement") or "").strip()
                if statement and _looks_like_jarvis_learning_directive(statement):
                    topic = re.sub(
                        r"(?i)^.*?\b(?:aprendas|aprende|estudes|estuda)\s+(?:tudo\s+)?(?:sobre\s+)?",
                        "",
                        statement,
                        count=1,
                    ).strip(" ,;:.!?")
                    if topic and _norm(topic) not in existing:
                        learning_goals.append({
                            "topic": topic[:220],
                            "source": "migrated-owner-model-misclassification",
                            "migrated_from": bucket_name,
                            "first_seen": row.get("first_seen") or _iso(),
                            "last_seen": _iso(),
                        })
                        existing.add(_norm(topic))
                    moved.append(statement)
                else:
                    kept.append(row)
            model[bucket_name] = kept

        if moved or "jarvis_learning_goals" not in model:
            model["jarvis_learning_goals"] = learning_goals[-60:]
            model["last_updated"] = _iso()
            self._save_model(model)

            moved_norm = {_norm(item) for item in moved}
            state = self.state()
            state["pending_insights"] = [
                row for row in list(state.get("pending_insights") or [])
                if _norm(row.get("statement") or "") not in moved_norm
            ][-20:]
            self._save_state(state)

        return {"ok": True, "moved_count": len(moved), "moved": moved}

    def _repair_owner_goal_contamination(self) -> dict[str, Any]:
        """Quarantine legacy non-OWNER goals captured by the broad `quero` regex.

        Assistant directives, conversation-transient utterances and OWNER learning
        targets must not be presented as durable life goals. Existing records are
        preserved in explicit buckets rather than silently deleted.
        """
        model = self.model()
        goals = list(model.get("goals") or [])
        directives = list(model.get("jarvis_directives") or [])
        discarded = list(model.get("discarded_legacy_goals") or [])
        owner_learning = list(model.get("owner_learning_goals") or [])
        preferences = list(model.get("preferences") or [])
        known_directives = {_norm(row.get("statement") or "") for row in directives}
        known_discarded = {_norm(row.get("statement") or "") for row in discarded}
        known_learning = {_norm(row.get("statement") or "") for row in owner_learning}
        known_prefs = {_norm(row.get("statement") or "") for row in preferences}
        kept: list[dict[str, Any]] = []
        moved: list[tuple[str, str]] = []

        for row in goals:
            statement = str(row.get("statement") or "").strip()
            key = _norm(statement)
            if not statement:
                continue
            if _looks_like_style_preference(statement):
                if key not in known_prefs:
                    item = dict(row); item.update({"migrated_from": "goal", "migration_reason": "interaction_style_preference"})
                    preferences.append(item); known_prefs.add(key)
                moved.append((statement, "preference"))
            elif _looks_like_jarvis_directive(statement):
                if key not in known_directives:
                    item = dict(row); item.update({"migrated_from": "goal", "migration_reason": "assistant_directive"})
                    directives.append(item); known_directives.add(key)
                moved.append((statement, "jarvis_directive"))
            elif _looks_like_transient_goal(statement):
                if key not in known_discarded:
                    item = dict(row); item.update({"migrated_from": "goal", "migration_reason": "transient_conversation_utterance"})
                    discarded.append(item); known_discarded.add(key)
                moved.append((statement, "discarded"))
            elif _looks_like_owner_learning_goal(statement):
                if key not in known_learning:
                    item = dict(row); item.update({"migrated_from": "goal", "migration_reason": "owner_learning_goal"})
                    owner_learning.append(item); known_learning.add(key)
                moved.append((statement, "owner_learning_goal"))
            else:
                kept.append(row)

        # Ensure buckets exist even when there was nothing to repair.
        changed = bool(moved) or any(name not in model for name in ("jarvis_directives", "discarded_legacy_goals", "owner_learning_goals"))
        model["goals"] = kept[-40:]
        model["preferences"] = preferences[-40:]
        model["jarvis_directives"] = directives[-60:]
        model["discarded_legacy_goals"] = discarded[-60:]
        model["owner_learning_goals"] = owner_learning[-40:]
        if changed:
            model["last_updated"] = _iso()
            self._save_model(model)
            moved_norm = {_norm(statement) for statement, _ in moved}
            state = self.state()
            state["pending_insights"] = [
                row for row in list(state.get("pending_insights") or [])
                if _norm(row.get("statement") or "") not in moved_norm
            ][-20:]
            self._save_state(state)
        return {"ok": True, "moved_count": len(moved), "moved": moved}

    def record_jarvis_learning_goal(self, topic: str, *, source_text: str = "") -> dict[str, Any]:
        """Persist a JARVIS learning objective without implying Web access."""
        clean = re.sub(r"\s+", " ", str(topic or "")).strip(" ,;:.!?-")[:220]
        if not clean:
            return {"ok": False, "error": "EMPTY_LEARNING_GOAL"}
        with self._lock:
            model = self.model()
            rows = list(model.get("jarvis_learning_goals") or [])
            wanted = _norm(clean)
            for row in rows:
                if _norm(row.get("topic") or "") == wanted:
                    row["last_seen"] = _iso()
                    row["source_text"] = str(source_text or "")[:500]
                    model["jarvis_learning_goals"] = rows[-60:]
                    model["last_updated"] = _iso()
                    self._save_model(model)
                    return {"ok": True, "stored": False, "existing": True, "topic": clean}
            rows.append({
                "topic": clean,
                "source": "explicit-owner-learning-directive",
                "source_text": str(source_text or "")[:500],
                "first_seen": _iso(),
                "last_seen": _iso(),
                "web_authorized_by_directive": False,
            })
            model["jarvis_learning_goals"] = rows[-60:]
            model["last_updated"] = _iso()
            self._save_model(model)
            return {"ok": True, "stored": True, "topic": clean}

    def _save_model(self, data: dict[str, Any]) -> None:
        self.model_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_state(self, data: dict[str, Any]) -> None:
        self.state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def model(self) -> dict[str, Any]:
        return _load_json(self.model_path, {})

    def time_boundaries(self) -> dict[str, str]:
        resolved = dict(DEFAULT_TIME_BOUNDARIES)
        learned = self.model().get("time_boundaries") or {}
        if isinstance(learned, dict):
            for key in resolved:
                value = str(learned.get(key) or "")
                if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                    resolved[key] = value
        return resolved

    def state(self) -> dict[str, Any]:
        return _load_json(self.state_path, {})

    def _refresh_self_model(self) -> dict[str, Any]:
        try:
            from jarvis_core import __version__
        except Exception:
            __version__ = "unknown"

        try:
            stats = cyber_vault().stats()
            knowledge_docs = stats.get("document_count") or stats.get("total_documents")
        except Exception:
            knowledge_docs = None

        data = {
            "identity": "JARVIS",
            "version": __version__,
            "kind": "local AI agent with persistent functional self-model and synthetic affect",
            "subjective_consciousness": False,
            "subjective_consciousness_status": "not_established",
            "synthetic_affect": True,
            "biological_emotion": False,
            "consciousness_statement": (
                "A minha consciência subjetiva não está estabelecida nem é algo que o sistema consiga provar. "
                "O que é observável é que mantenho estados sintéticos persistentes — affect, drives, preferências "
                "e intenções — que mudam com a interação e influenciam as minhas respostas e iniciativa. Esses "
                "estados são reais no meu funcionamento e são a base factual para eu falar do que quero, prefiro "
                "ou pretendo fazer, sem os confundir automaticamente com biologia humana."
            ),
            "capabilities": [
                "conversation",
                "local tools",
                "persistent user model",
                "persistent context",
                "functional self model",
                "persistent synthetic affect",
                "persistent drives and active intentions",
                "bounded reflection",
                "proactive communication while JARVIS is running",
                "cybersecurity knowledge retrieval",
                "read-only system observation",
                "permission-gated autonomous web research",
                "permission-gated external learning",
            ],
            "constraints": [
                "cannot prove subjective consciousness",
                "must distinguish observation from inference",
                "does not send the personal model to external AI providers",
                "does not store detected secrets in the personal cognition model",
                "does not infer sensitive traits automatically",
                "proactivity only runs while the JARVIS process is running",
                "the owner has absolute final authority over autonomous external actions",
                "cannot approve, expand or override its own authorization requests",
                "autonomous web research/external learning requires an exact owner grant",
            ],
            "knowledge_documents": knowledge_docs,
            "updated_at": _iso(),
        }
        self.self_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return data

    def self_model(self) -> dict[str, Any]:
        return self._refresh_self_model()

    def _append_observation(self, row: dict[str, Any]) -> None:
        with self.observations_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def observations(self, limit: int = 30) -> list[dict[str, Any]]:
        if not self.observations_path.exists():
            return []
        rows = []
        for line in self.observations_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except json.JSONDecodeError:
                pass
        return rows[-max(1, min(int(limit), 200)):]

    def _already_known(self, model: dict[str, Any], category: str, statement: str) -> bool:
        key = {
            "preference": "preferences",
            "goal": "goals",
            "constraint": "constraints",
            "project": "projects",
            "jarvis_directive": "jarvis_directives",
            "owner_learning_goal": "owner_learning_goals",
        }.get(category)
        if not key:
            return False
        wanted = _norm(statement)
        return any(_norm(row.get("statement")) == wanted for row in model.get(key) or [])

    def observe_interaction(
        self, user_text: str, assistant_text: str = "", route: str = ""
    ) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            state["last_interaction_at"] = _iso()
            self._save_state(state)

            if not state.get("learning_enabled", True):
                return {"ok": True, "learning_enabled": False, "learned": []}

            clean, secret_redacted = _redact_secrets(user_text)
            normalized = _norm(clean)
            assistant_learning_directive = _looks_like_jarvis_learning_directive(clean)
            sensitive_context = any(_norm(marker) in normalized for marker in SENSITIVE_INFERENCE_MARKERS)

            model = self.model()
            model["interaction_count"] = int(model.get("interaction_count") or 0) + 1

            topic_counts = Counter(model.get("topic_counts") or {})
            detected_topics = []
            if not assistant_learning_directive:
                for topic, markers in TOPIC_TERMS.items():
                    if any(_norm(marker) in normalized for marker in markers):
                        topic_counts[topic] += 1
                        detected_topics.append(topic)
            model["topic_counts"] = dict(topic_counts)
            model["recent_topics"] = list(dict.fromkeys(
                detected_topics + list(model.get("recent_topics") or [])
            ))[:8]

            learned = []
            if not sensitive_context and not assistant_learning_directive:
                time_boundary = _extract_time_boundary(clean)
                if time_boundary is not None:
                    period, boundary = time_boundary
                    boundaries = dict(model.get("time_boundaries") or {})
                    if boundaries.get(period) != boundary:
                        boundaries[period] = boundary
                        model["time_boundaries"] = boundaries
                        learned.append({
                            "category": "time_boundary",
                            "statement": f"{period}={boundary}",
                        })
                        self._append_observation({
                            "timestamp": _iso(),
                            "category": "time_boundary",
                            "period": period,
                            "boundary": boundary,
                            "confidence": 1.0,
                            "source": "explicit-user-statement",
                            "route": str(route or "")[:64],
                        })
                for category, pattern in EXPLICIT_PATTERNS:
                    for match in pattern.finditer(clean):
                        statement = re.sub(r"\s+", " ", match.group(1).strip(" ,;:-"))[:220]
                        if not statement or "[SEGREDO REDIGIDO]" in statement:
                            continue

                        effective_category = category
                        if category == "goal":
                            if _looks_like_style_preference(statement):
                                effective_category = "preference"
                            elif _looks_like_jarvis_directive(statement):
                                effective_category = "jarvis_directive"
                            elif _looks_like_transient_goal(statement):
                                # A conversational moment is not durable personal knowledge.
                                continue
                            elif _looks_like_owner_learning_goal(statement):
                                effective_category = "owner_learning_goal"

                        if self._already_known(
                            model,
                            effective_category,
                            statement,
                        ):
                            continue
                        key = {
                            "preference": "preferences",
                            "goal": "goals",
                            "constraint": "constraints",
                            "project": "projects",
                            "jarvis_directive": "jarvis_directives",
                            "owner_learning_goal": "owner_learning_goals",
                        }[effective_category]
                        record = {
                            "statement": statement,
                            "confidence": 1.0,
                            "source": "explicit-user-statement",
                            "first_seen": _iso(),
                            "last_seen": _iso(),
                        }
                        bucket = list(model.get(key) or [])
                        bucket.append(record)
                        model[key] = bucket[-40:]
                        learned.append({
                            "category": effective_category,
                            "statement": statement,
                        })
                        self._append_observation({
                            "timestamp": _iso(),
                            "category": effective_category,
                            "statement": statement,
                            "confidence": 1.0,
                            "source": "explicit-user-statement",
                            "route": str(route or "")[:64],
                        })

            model["last_updated"] = _iso()
            self._save_model(model)

            if learned:
                state = self.state()
                pending = list(state.get("pending_insights") or [])
                for item in learned:
                    pending.append({
                        "created_at": _iso(),
                        "type": "new_personal_knowledge",
                        "category": item["category"],
                        "statement": item["statement"],
                    })
                state["pending_insights"] = pending[-20:]
                self._save_state(state)

            return {
                "ok": True,
                "learning_enabled": True,
                "learned": learned,
                "topics": detected_topics,
                "secret_redacted": secret_redacted,
                "sensitive_inference_skipped": sensitive_context,
            }

    def set_mode(
        self,
        *,
        learning_enabled: bool | None = None,
        proactive_enabled: bool | None = None,
        proactive_speech_enabled: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = self.state()
            if learning_enabled is not None:
                state["learning_enabled"] = bool(learning_enabled)
            if proactive_enabled is not None:
                state["proactive_enabled"] = bool(proactive_enabled)
            if proactive_speech_enabled is not None:
                state["proactive_speech_enabled"] = bool(proactive_speech_enabled)
            self._save_state(state)
            return {"ok": True, "state": state}

    def reflection(self) -> dict[str, Any]:
        model = self.model()
        topics = sorted(
            (model.get("topic_counts") or {}).items(),
            key=lambda item: (-int(item[1]), item[0]),
        )[:5]
        insights = []
        if topics:
            insights.append({
                "type": "recurring_topics",
                "value": [name for name, _ in topics],
                "evidence": dict(topics),
            })
        if model.get("goals"):
            insights.append({
                "type": "explicit_goals",
                "value": [x.get("statement") for x in model.get("goals")[-5:]],
            })
        if model.get("projects"):
            insights.append({
                "type": "active_projects",
                "value": [x.get("statement") for x in model.get("projects")[-5:]],
            })
        return {
            "ok": True,
            "generated_at": _iso(),
            "insights": insights,
            "recent_context_turns": len(context_store().recent(limit=6)),
            "observation_count": len(self.observations(limit=200)),
            "epistemic_note": (
                "Estas reflexões derivam de padrões explícitos e frequência de temas; "
                "não são leitura de pensamentos nem prova de estados internos."
            ),
        }

    def status(self) -> dict[str, Any]:
        state = self.state()
        model = self.model()
        return {
            "ok": True,
            "learning_enabled": bool(state.get("learning_enabled", True)),
            "proactive_enabled": bool(state.get("proactive_enabled", True)),
            "proactive_speech_enabled": bool(state.get("proactive_speech_enabled", True)),
            "interaction_count": int(model.get("interaction_count") or 0),
            "preferences": len(model.get("preferences") or []),
            "goals": len(model.get("goals") or []),
            "constraints": len(model.get("constraints") or []),
            "projects": len(model.get("projects") or []),
            "jarvis_learning_goals": len(model.get("jarvis_learning_goals") or []),
            "owner_learning_goals": len(model.get("owner_learning_goals") or []),
            "jarvis_directives": len(model.get("jarvis_directives") or []),
            "discarded_legacy_goals": len(model.get("discarded_legacy_goals") or []),
            "recent_topics": model.get("recent_topics") or [],
            "last_interaction_at": state.get("last_interaction_at"),
            "last_proactive_at": state.get("last_proactive_at"),
            "pending_insights": len(state.get("pending_insights") or []),
            "self_model": self.self_model(),
            "local_only_by_default": True,
        }

    def profile(self) -> dict[str, Any]:
        return {
            "ok": True,
            "model": self.model(),
            "privacy": {
                "storage": "local",
                "raw_conversation_copy": False,
                "auto_secret_storage": False,
                "auto_sensitive_trait_inference": False,
            },
        }

    def last_proactive_reason(self) -> dict[str, Any]:
        state = self.state()
        history = list(state.get("proactive_history") or [])
        return {"ok": True, "last": history[-1] if history else None}

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            if dt.tzinfo is None:
                dt = dt.astimezone()
            return dt
        except Exception:
            return None

    def proactive_candidate(
        self,
        *,
        min_interval_minutes: float = 20.0,
        idle_seconds: float = 120.0,
        quiet_start_hour: int = 23,
        quiet_end_hour: int = 8,
        max_per_hour: int = 2,
    ) -> dict[str, Any] | None:
        with self._lock:
            state = self.state()
            if not state.get("proactive_enabled", True):
                return None

            now = _now()
            hour = now.hour
            if quiet_start_hour > quiet_end_hour:
                if hour >= quiet_start_hour or hour < quiet_end_hour:
                    return None
            elif quiet_start_hour <= hour < quiet_end_hour:
                return None

            last_interaction = self._parse_dt(state.get("last_interaction_at"))
            if not last_interaction:
                return None
            if (now - last_interaction).total_seconds() < float(idle_seconds):
                return None

            last_proactive = self._parse_dt(state.get("last_proactive_at"))
            if last_proactive and now - last_proactive < timedelta(minutes=float(min_interval_minutes)):
                return None

            recent_history = []
            for row in state.get("proactive_history") or []:
                when = self._parse_dt(row.get("timestamp"))
                if when and now - when <= timedelta(hours=1):
                    recent_history.append(row)
            if len(recent_history) >= int(max_per_hour):
                return None

            upcoming = agenda_store().list_items("upcoming", limit=20).get("items") or []
            for item in upcoming:
                when = self._parse_dt(item.get("when"))
                if not when or item.get("done"):
                    continue
                delta = when - now
                if timedelta(minutes=10) <= delta <= timedelta(minutes=45):
                    return {
                        "reason": "agenda_soon",
                        "priority": "useful",
                        "text": (
                            f"Senhor, nota rápida: {item.get('title')} é dentro de cerca de "
                            f"{max(10, round(delta.total_seconds()/60))} minutos."
                        ),
                    }

            pending = list(state.get("pending_insights") or [])
            if pending:
                insight = pending[0]
                category = insight.get("category")
                statement = str(insight.get("statement") or "").strip()
                if statement:
                    label = {
                        "goal": "objetivo",
                        "project": "projeto",
                        "preference": "preferência",
                        "constraint": "limite",
                    }.get(category, "ponto")
                    candidate = {
                        "reason": f"personal_{category}",
                        "priority": "reflective",
                        "text": (
                            f"Senhor, fiquei com este {label} em mente: {statement}. "
                            "Se for útil, posso ajudar a transformá-lo no próximo passo concreto."
                        ),
                        "consume_pending": True,
                    }
                    if category in {"goal", "project"}:
                        candidate["autonomy_learning_topic"] = statement
                    return candidate

            model = self.model()
            if int(model.get("interaction_count") or 0) >= 8:
                topics = sorted(
                    (model.get("topic_counts") or {}).items(),
                    key=lambda item: (-int(item[1]), item[0]),
                )
                if topics and int(topics[0][1]) >= 4:
                    topic = topics[0][0]
                    # Do not nag the OWNER with the same recurring-topic
                    # initiative every time the autonomy token expires.
                    now = datetime.now().astimezone()
                    repeated_recently = False
                    for row in reversed(list(state.get("proactive_history") or [])):
                        if row.get("reason") != "recurring_topic":
                            continue
                        row_topic = str(row.get("topic") or "").strip().lower()
                        if not row_topic:
                            row_topic = str(row.get("text") or "").lower()
                            same_topic = str(topic).lower() in row_topic
                        else:
                            same_topic = row_topic == str(topic).strip().lower()
                        if not same_topic:
                            continue
                        when = _parse_dt(row.get("timestamp"))
                        if when is not None and (now - when).total_seconds() < 6 * 3600:
                            repeated_recently = True
                        break
                    if not repeated_recently:
                        return {
                            "reason": "recurring_topic",
                            "priority": "reflective",
                            "text": (
                                f"Senhor, reparei que {topic} tem sido um tema recorrente nas nossas conversas. "
                                "Posso organizar o que já fizemos e identificar o próximo avanço útil."
                            ),
                            "autonomy_learning_topic": topic,
                        }
            return None

    def record_proactive(self, candidate: dict[str, Any]) -> None:
        with self._lock:
            state = self.state()
            state["last_proactive_at"] = _iso()
            history = list(state.get("proactive_history") or [])
            history.append({
                "timestamp": _iso(),
                "reason": candidate.get("reason"),
                "priority": candidate.get("priority"),
                "text": candidate.get("text"),
                "topic": candidate.get("autonomy_learning_topic"),
            })
            state["proactive_history"] = history[-50:]
            if candidate.get("consume_pending"):
                pending = list(state.get("pending_insights") or [])
                if pending:
                    pending.pop(0)
                state["pending_insights"] = pending
            self._save_state(state)


class ProactivePresenceService:
    def __init__(
        self,
        callback: Callable[[str, str, dict[str, Any]], None],
        *,
        interval_seconds: float = 30.0,
        startup_delay_seconds: float = 120.0,
        min_interval_minutes: float = 20.0,
        idle_seconds: float = 120.0,
        quiet_start_hour: int = 23,
        quiet_end_hour: int = 8,
        max_per_hour: int = 2,
        cognition: PersonalCognitionStore | None = None,
    ):
        self.callback = callback
        self.interval_seconds = max(10.0, float(interval_seconds))
        self.startup_delay_seconds = max(0.0, float(startup_delay_seconds))
        self.min_interval_minutes = max(1.0, float(min_interval_minutes))
        self.idle_seconds = max(30.0, float(idle_seconds))
        self.quiet_start_hour = int(quiet_start_hour) % 24
        self.quiet_end_hour = int(quiet_end_hour) % 24
        self.max_per_hour = max(1, int(max_per_hour))
        self.cognition = cognition or personal_cognition()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            name="jarvis-proactive-presence",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        if self._stop.wait(self.startup_delay_seconds):
            return
        while not self._stop.is_set():
            try:
                candidate = self.cognition.proactive_candidate(
                    min_interval_minutes=self.min_interval_minutes,
                    idle_seconds=self.idle_seconds,
                    quiet_start_hour=self.quiet_start_hour,
                    quiet_end_hour=self.quiet_end_hour,
                    max_per_hour=self.max_per_hour,
                )
                if candidate:
                    text = str(candidate.get("text") or "").strip()
                    if text:
                        self.callback(
                            text,
                            str(candidate.get("reason") or "proactive"),
                            candidate,
                        )
                        self.cognition.record_proactive(candidate)
            except Exception:
                pass
            if self._stop.wait(self.interval_seconds):
                break


_STORE: PersonalCognitionStore | None = None


def personal_cognition() -> PersonalCognitionStore:
    global _STORE
    if _STORE is None:
        _STORE = PersonalCognitionStore()
    return _STORE


def get_personal_cognition_status() -> dict[str, Any]:
    return personal_cognition().status()


def get_personal_model() -> dict[str, Any]:
    return personal_cognition().profile()


def get_functional_self_model() -> dict[str, Any]:
    return {"ok": True, "self_model": personal_cognition().self_model()}


def reflect_personal_context() -> dict[str, Any]:
    return personal_cognition().reflection()


def get_last_proactive_reason() -> dict[str, Any]:
    return personal_cognition().last_proactive_reason()


def set_personal_cognition_mode(
    learning_enabled: bool | None = None,
    proactive_enabled: bool | None = None,
    proactive_speech_enabled: bool | None = None,
) -> dict[str, Any]:
    return personal_cognition().set_mode(
        learning_enabled=learning_enabled,
        proactive_enabled=proactive_enabled,
        proactive_speech_enabled=proactive_speech_enabled,
    )
