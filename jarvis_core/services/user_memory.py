from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import re
import unicodedata


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value).lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip()


def _looks_like_credential_secret(value: str) -> bool:
    """Block actual credential material from ordinary persistent memory.

    Merely mentioning a credential concept is allowed (for example, a
    preference about API-key storage). The guard triggers when credential or
    recovery material is assigned/provided, or when a recognizable private
    key/API-key form is present. Ordinary personal facts remain allowed.
    """
    raw = str(value or "")
    text = _norm(raw)
    labels = (
        r"password", r"palavra[ -]?passe", r"passphrase",
        r"api key", r"chave api", r"secret key", r"chave secreta",
        r"access token", r"refresh token", r"bearer token",
        r"token de acesso", r"private key", r"chave privada",
        r"seed phrase", r"frase semente", r"recovery phrase",
        r"frase de recuperacao",
    )
    label_expr = "(?:" + "|".join(labels) + ")"
    if re.search(
        rf"\b{label_expr}\b\s*(?:e|:|=|is)\s*\S+",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", raw, flags=re.IGNORECASE):
        return True
    if re.search(r"\bsk-[A-Za-z0-9_-]{8,}\b", raw):
        return True
    if re.search(r"\b(?:pin|cvv|cvc)\b\s*(?:e|:|=)\s*[0-9]{3,12}\b", text):
        return True
    return False


class UserMemoryStore:
    def __init__(self, memory_dir: str | Path = "memory", default_profile: str | Path = "defaults/user_profile.json"):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.memory_dir / "user_profile.json"
        self.facts_path = self.memory_dir / "facts.jsonl"
        self.default_profile_path = Path(default_profile)
        self.ensure_profile()

    def ensure_profile(self) -> dict[str, Any]:
        if self.profile_path.exists():
            return self.profile()
        profile = json.loads(self.default_profile_path.read_text(encoding="utf-8")) if self.default_profile_path.exists() else {
            "name": "Tiago", "address_as": "Senhor", "language": "pt-PT", "timezone": "Europe/Lisbon", "home": {}
        }
        self.profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return profile

    def profile(self) -> dict[str, Any]:
        if not self.profile_path.exists():
            return self.ensure_profile()
        try:
            data = json.loads(self.profile_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def remember(self, fact: str, category: str = "general") -> dict[str, Any]:
        text = str(fact).strip()
        if not text:
            return {"ok": False, "error": "EMPTY_MEMORY"}
        if _looks_like_credential_secret(text):
            return {
                "ok": False,
                "error": "SECRET_MEMORY_BLOCKED",
                "message": (
                    "Não vou guardar credenciais, chaves, tokens, PIN/CVV ou "
                    "frases de recuperação na memória normal, Senhor."
                ),
            }
        record = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "category": str(category or "general")[:64],
            "fact": text[:2000],
        }
        with self.facts_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        graph_result = None
        try:
            # Relational memory is a secondary local index. It receives only
            # facts that have already passed the explicit-memory/secret guard.
            from jarvis_core.skills.builtin.memory_graph import ingest_explicit_memory_fact
            graph_result = ingest_explicit_memory_fact(text, record["category"])
        except Exception:
            graph_result = {"ok": False, "error": "MEMORY_GRAPH_INDEX_FAILED"}
        return {"ok": True, "stored": record, "graph": graph_result}

    def facts(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.facts_path.exists():
            return []
        rows = []
        for line in self.facts_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except json.JSONDecodeError:
                continue
        return rows[-max(1, min(int(limit), 200)):]

    def recall(self, query: str = "", limit: int = 20) -> dict[str, Any]:
        rows = self.facts(limit=200)
        q = _norm(query)
        cap = max(1, min(int(limit), 50))
        if q:
            words = {w for w in q.split() if len(w) >= 3}
            scored = []
            for index, row in enumerate(rows):
                hay = _norm(f"{row.get('category','')} {row.get('fact','')}")
                score = sum(1 for w in words if w in hay)
                if score:
                    # Prefer higher lexical relevance; on ties prefer newer facts.
                    scored.append((score, index, row))
            scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
            rows = [row for _, _, row in scored[:cap]]
        else:
            rows = rows[-cap:]
        return {"ok": True, "profile": self.profile(), "facts": rows}

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "memory_dir": str(self.memory_dir),
            "profile_path": str(self.profile_path),
            "facts_path": str(self.facts_path),
            "fact_count": len(self.facts(limit=200)),
            "profile": self.profile(),
        }


_STORE: UserMemoryStore | None = None

def store() -> UserMemoryStore:
    global _STORE
    if _STORE is None:
        _STORE = UserMemoryStore()
    return _STORE

def get_user_profile() -> dict[str, Any]:
    return {"ok": True, "profile": store().profile()}

def remember_user_fact(fact: str, category: str = "general") -> dict[str, Any]:
    return store().remember(fact=fact, category=category)

def recall_user_memory(query: str = "", limit: int = 20) -> dict[str, Any]:
    return store().recall(query=query, limit=limit)

def get_memory_status() -> dict[str, Any]:
    return store().status()
