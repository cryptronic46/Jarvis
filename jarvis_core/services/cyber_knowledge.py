from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from threading import Event, Thread, RLock
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import html
import json
import re
import sqlite3
import time


SCHEMA_VERSION = 1
DEFAULT_DB = Path("knowledge/cyber/cyber_knowledge.sqlite3")
DEFAULT_SOURCES = Path("defaults/cyber_sources.json")
DEFAULT_STATE = Path("knowledge/cyber/state.json")
USER_AGENT = "JARVIS-CyberKnowledge/0.13 (+local personal knowledge base)"

ALLOWED_WEB_HOSTS = {
    "www.nist.gov",
    "nist.gov",
    "csrc.nist.gov",
    "owasp.org",
    "www.cisa.gov",
    "cisa.gov",
    "learn.microsoft.com",
    "raw.githubusercontent.com",
}

MITRE_OBJECT_TYPES = {
    "attack-pattern",
    "course-of-action",
    "intrusion-set",
    "malware",
    "tool",
    "x-mitre-tactic",
    "x-mitre-data-source",
    "x-mitre-data-component",
}

SEED_DOCS = [
    ("foundation-identity","Identidade, contas, UAC e privilégio mínimo","windows-security",
     "Contas de utilizador representam identidades. Privilégios administrativos aumentam o impacto potencial de erro, malware ou abuso. UAC cria uma fronteira de elevação para operações administrativas. A prática defensiva é usar o menor privilégio necessário, reduzir administradores permanentes e auditar mudanças de pertença a grupos privilegiados."),
    ("foundation-networking","TCP/IP, sub-redes, gateway, ARP, DNS e DHCP","network-security",
     "TCP/IP transporta comunicação entre hosts. A máscara e a sub-rede definem o alcance local; o gateway encaminha tráfego para outras redes. ARP associa IPv4 a MAC na LAN, DHCP atribui configuração e DNS traduz nomes. Uma entrada ARP ou ligação à Internet, isoladamente, não prova intrusão."),
    ("foundation-sockets","Portas, sockets, LISTEN e ESTABLISHED","network-security",
     "Uma porta em LISTEN indica um processo preparado para receber ligações num endereço local. ESTABLISHED indica uma ligação TCP atualmente estabelecida. A interpretação defensiva associa porta, endereço, processo, utilizador, firewall e contexto; números de portas por si só não provam risco."),
    ("foundation-firewall-defender","Firewall e Microsoft Defender","windows-security",
     "A Firewall do Windows controla tráfego segundo perfis e regras. Microsoft Defender fornece proteção antimalware e outras camadas. Nenhuma camada é suficiente sozinha: atualização, hardening, privilégio mínimo e monitorização continuam necessários."),
    ("foundation-remote","RDP, SMB e acesso remoto","windows-security",
     "RDP fornece sessão remota interativa e SMB suporta partilha de ficheiros e recursos. Serviços remotos desnecessários devem permanecer desativados ou restritos. Uma sessão RDP ou SMB ativa é evidência mais forte de acesso remoto do que tráfego HTTPS normal."),
    ("foundation-logs","Windows Event Logs e evidência","incident-response",
     "Logs de sistema, segurança e aplicações ajudam a reconstruir eventos. Auditoria séria separa facto observado, correlação e hipótese. Um alerta sem contexto deve iniciar validação, não uma conclusão automática de compromisso."),
    ("foundation-persistence","Persistência no Windows","windows-security",
     "Persistência pode usar serviços, tarefas agendadas, chaves Run, extensões, WMI e outros mecanismos. A defesa compara o estado atual com uma baseline conhecida e investiga alterações inesperadas com evidência adicional."),
    ("foundation-patching","Patching, vulnerabilidades e hardening","vulnerability-management",
     "Gestão de vulnerabilidades combina inventário, atualização, exposição, exploração conhecida e impacto. Hardening reduz funcionalidades e permissões desnecessárias. Prioridade deve considerar evidência de exploração real e contexto do sistema, não apenas uma pontuação isolada."),
    ("foundation-lan","Inventário da rede doméstica","network-security",
     "Uma baseline de dispositivos habituais facilita identificar mudanças. Estado Stale significa conhecido pela cache, não necessariamente ligado agora. Novo MAC ou IP deve ser identificado antes de ser classificado como host malicioso."),
    ("foundation-baseline","Baselines e deteção de alterações","defensive-monitoring",
     "Uma baseline representa um estado conhecido como normal: administradores, serviços, políticas, software remoto, dispositivos e configurações. Deteção de mudanças reduz ruído, mas uma diferença ainda precisa de interpretação antes de ser considerada incidente."),
    ("foundation-authorized-testing","Testes éticos e âmbito autorizado","security-testing",
     "Testes de segurança devem ser executados apenas em sistemas próprios ou explicitamente autorizados. Define-se o âmbito, minimiza-se impacto, preservam-se logs e documentam-se resultados. Aprender técnicas ofensivas deve servir validação, deteção e defesa dentro desse âmbito."),
    ("foundation-ir","Resposta a incidentes","incident-response",
     "Resposta a incidentes inclui preparação, identificação, contenção, preservação de evidência, erradicação, recuperação e lições aprendidas. A ordem exata depende do incidente; ações precipitadas podem destruir evidência ou aumentar impacto."),
]


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "canvas", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []
        self.title: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p","div","li","h1","h2","h3","h4","br","tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in {"p","div","li","h1","h2","h3","h4","tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if self.skip_depth:
            return
        text = str(data or "").strip()
        if not text:
            return
        if self.in_title:
            self.title.append(text)
        self.parts.append(text + " ")

    def result(self) -> tuple[str, str]:
        title = " ".join(self.title).strip()
        body = html.unescape("".join(self.parts))
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n\s*\n+", "\n", body)
        return title, body.strip()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _clean(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _attack_external_id(obj: dict[str, Any]) -> str | None:
    for ref in obj.get("external_references") or []:
        if ref.get("external_id"):
            return str(ref["external_id"])
    return None


class CyberKnowledgeVault:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_DB,
        sources_path: str | Path = DEFAULT_SOURCES,
        state_path: str | Path = DEFAULT_STATE,
    ):
        self.db_path = Path(db_path)
        self.sources_path = Path(sources_path)
        self.state_path = Path(state_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._fts = False
        self._init_db()
        self.seed_foundation()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _db(self):
        """Transaction + deterministic close for Windows file handles."""
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    url TEXT,
                    category TEXT,
                    publisher TEXT,
                    trust TEXT,
                    provenance TEXT NOT NULL,
                    published TEXT,
                    source_updated TEXT,
                    retrieved_at TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    metadata_json TEXT,
                    UNIQUE(source_id, external_id)
                );
                CREATE INDEX IF NOT EXISTS idx_documents_source
                    ON documents(source_id);
                CREATE INDEX IF NOT EXISTS idx_documents_category
                    ON documents(category);
            """)
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                    USING fts5(
                        doc_id UNINDEXED,
                        title,
                        body,
                        category,
                        publisher,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                """)
                self._fts = True
            except sqlite3.OperationalError:
                self._fts = False

    def _load_sources(self) -> dict[str, Any]:
        try:
            data = json.loads(self.sources_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"sources": []}
        except Exception:
            return {"sources": []}

    def sources(self) -> list[dict[str, Any]]:
        return list(self._load_sources().get("sources") or [])

    def _upsert(
        self,
        *,
        source_id: str,
        external_id: str,
        title: str,
        body: str,
        url: str = "",
        category: str = "",
        publisher: str = "",
        trust: str = "",
        provenance: str,
        published: str = "",
        source_updated: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[int, bool]:
        title = _clean(title) or external_id
        body = _clean(body)
        digest = sha256(body.encode("utf-8")).hexdigest()
        now = _now()
        metadata_json = json.dumps(
            metadata or {},
            ensure_ascii=False,
            sort_keys=True,
        )

        with self._lock, self._db() as conn:
            old = conn.execute(
                "SELECT id,sha256 FROM documents WHERE source_id=? AND external_id=?",
                (source_id, external_id),
            ).fetchone()
            changed = old is None or old["sha256"] != digest

            if old is None:
                cur = conn.execute("""
                    INSERT INTO documents(
                        source_id,external_id,title,body,url,category,publisher,
                        trust,provenance,published,source_updated,retrieved_at,
                        sha256,metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    source_id, external_id, title, body, url, category,
                    publisher, trust, provenance, published, source_updated,
                    now, digest, metadata_json,
                ))
                doc_id = int(cur.lastrowid)
            else:
                doc_id = int(old["id"])
                conn.execute("""
                    UPDATE documents
                    SET title=?,body=?,url=?,category=?,publisher=?,trust=?,
                        provenance=?,published=?,source_updated=?,retrieved_at=?,
                        sha256=?,metadata_json=?
                    WHERE id=?
                """, (
                    title, body, url, category, publisher, trust, provenance,
                    published, source_updated, now, digest, metadata_json,
                    doc_id,
                ))

            if self._fts:
                conn.execute("DELETE FROM documents_fts WHERE doc_id=?", (doc_id,))
                conn.execute("""
                    INSERT INTO documents_fts(
                        doc_id,title,body,category,publisher
                    ) VALUES(?,?,?,?,?)
                """, (doc_id, title, body, category, publisher))

        return doc_id, changed

    def seed_foundation(self) -> dict[str, Any]:
        changed = 0
        for external_id, title, category, body in SEED_DOCS:
            _, was_changed = self._upsert(
                source_id="jarvis_foundation",
                external_id=external_id,
                title=title,
                body=body,
                category=category,
                publisher="JARVIS",
                trust="curated",
                provenance="curated-seed",
                metadata={"source_class": "internal-curated"},
            )
            changed += int(was_changed)
        return {
            "ok": True,
            "seed_documents": len(SEED_DOCS),
            "changed": changed,
        }

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("CYBER_SOURCE_HTTPS_REQUIRED")
        host = (parsed.hostname or "").lower()
        if host not in ALLOWED_WEB_HOSTS:
            raise ValueError(f"CYBER_SOURCE_HOST_NOT_ALLOWED:{host}")

    def _download(self, source: dict[str, Any]) -> bytes:
        url = str(source.get("url") or "")
        self._validate_url(url)
        max_bytes = max(
            100_000,
            min(int(source.get("max_bytes") or 5_000_000), 80_000_000),
        )
        req = Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/html,*/*;q=0.8",
            },
        )
        with urlopen(req, timeout=35) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ValueError(f"CYBER_SOURCE_TOO_LARGE:{length}>{max_bytes}")
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError(
                    f"CYBER_SOURCE_TOO_LARGE:{len(raw)}>{max_bytes}"
                )
            return raw

    def _sync_html(
        self,
        source: dict[str, Any],
        raw: bytes,
    ) -> dict[str, Any]:
        parser = _TextExtractor()
        parser.feed(raw.decode("utf-8", errors="replace"))
        page_title, body = parser.result()
        if len(body) < 100:
            raise ValueError("CYBER_SOURCE_EMPTY_TEXT")
        _, changed = self._upsert(
            source_id=source["id"],
            external_id="root",
            title=page_title or str(source.get("name") or source["id"]),
            body=body,
            url=source.get("url", ""),
            category=source.get("category", ""),
            publisher=source.get("publisher", ""),
            trust=source.get("trust", "official"),
            provenance="official-web-import",
            metadata={"kind": "html"},
        )
        return {"documents": 1, "changed": int(changed)}

    def _sync_cisa_kev(
        self,
        source: dict[str, Any],
        raw: bytes,
    ) -> dict[str, Any]:
        data = json.loads(raw.decode("utf-8"))
        changed = 0
        inserted = 0
        for item in data.get("vulnerabilities") or []:
            cve = str(item.get("cveID") or "").strip()
            if not cve:
                continue
            title = (
                f"{cve} — {item.get('vendorProject','')} "
                f"{item.get('product','')}"
            ).strip()
            body = " ".join(x for x in [
                item.get("vulnerabilityName") or "",
                item.get("shortDescription") or "",
                (
                    "Required action: " + str(item.get("requiredAction"))
                    if item.get("requiredAction") else ""
                ),
                (
                    "Known ransomware use: "
                    + str(item.get("knownRansomwareCampaignUse"))
                    if item.get("knownRansomwareCampaignUse") else ""
                ),
                (
                    "Due date: " + str(item.get("dueDate"))
                    if item.get("dueDate") else ""
                ),
                (
                    "Notes: " + str(item.get("notes"))
                    if item.get("notes") else ""
                ),
            ] if x)
            _, was_changed = self._upsert(
                source_id=source["id"],
                external_id=cve,
                title=title,
                body=body,
                url=source.get("url", ""),
                category=source.get("category", ""),
                publisher=source.get("publisher", ""),
                trust=source.get("trust", "official"),
                provenance="official-machine-readable",
                published=str(item.get("dateAdded") or ""),
                metadata={
                    "cve": cve,
                    "vendor": item.get("vendorProject"),
                    "product": item.get("product"),
                    "date_added": item.get("dateAdded"),
                    "due_date": item.get("dueDate"),
                    "known_ransomware": item.get(
                        "knownRansomwareCampaignUse"
                    ),
                    "cwes": item.get("cwes"),
                },
            )
            inserted += 1
            changed += int(was_changed)
        return {
            "documents": inserted,
            "changed": changed,
            "catalog_version": data.get("catalogVersion"),
            "date_released": data.get("dateReleased"),
        }

    def _sync_mitre_attack(
        self,
        source: dict[str, Any],
        raw: bytes,
    ) -> dict[str, Any]:
        data = json.loads(raw.decode("utf-8"))
        changed = 0
        inserted = 0
        type_counts: Counter[str] = Counter()

        for item in data.get("objects") or []:
            obj_type = str(item.get("type") or "")
            if obj_type not in MITRE_OBJECT_TYPES:
                continue
            if item.get("revoked") is True or item.get("x_mitre_deprecated") is True:
                continue

            ext_id = _attack_external_id(item) or str(item.get("id") or "")
            if not ext_id:
                continue

            phases = [
                str(x.get("phase_name"))
                for x in item.get("kill_chain_phases") or []
                if x.get("phase_name")
            ]
            platforms = [str(x) for x in item.get("x_mitre_platforms") or []]
            aliases = [str(x) for x in item.get("aliases") or []]
            refs = [
                str(x.get("url"))
                for x in item.get("external_references") or []
                if x.get("url")
            ]

            body = " ".join(x for x in [
                f"ATT&CK ID: {ext_id}",
                item.get("description") or "",
                "Tactics/phases: " + ", ".join(phases) if phases else "",
                "Platforms: " + ", ".join(platforms) if platforms else "",
                "Aliases: " + ", ".join(aliases) if aliases else "",
            ] if x)

            _, was_changed = self._upsert(
                source_id=source["id"],
                external_id=ext_id,
                title=str(item.get("name") or ext_id),
                body=body,
                url=refs[0] if refs else source.get("url", ""),
                category=f"{source.get('category','')}/{obj_type}",
                publisher=source.get("publisher", ""),
                trust=source.get("trust", "official-repository"),
                provenance="official-machine-readable",
                published=str(item.get("created") or ""),
                source_updated=str(item.get("modified") or ""),
                metadata={
                    "stix_id": item.get("id"),
                    "stix_type": obj_type,
                    "attack_id": _attack_external_id(item),
                    "platforms": platforms,
                    "phases": phases,
                    "aliases": aliases,
                    "external_references": refs[:12],
                },
            )
            inserted += 1
            changed += int(was_changed)
            type_counts[obj_type] += 1

        return {
            "documents": inserted,
            "changed": changed,
            "types": dict(type_counts),
        }

    def sync_source(self, source_id: str) -> dict[str, Any]:
        source = next(
            (x for x in self.sources() if x.get("id") == source_id),
            None,
        )
        if not source:
            return {
                "ok": False,
                "error": "CYBER_SOURCE_NOT_FOUND",
                "source_id": source_id,
            }

        started = time.monotonic()
        try:
            raw = self._download(source)
            kind = str(source.get("kind") or "html")
            if kind == "html":
                result = self._sync_html(source, raw)
            elif kind == "cisa_kev":
                result = self._sync_cisa_kev(source, raw)
            elif kind == "mitre_attack_stix":
                result = self._sync_mitre_attack(source, raw)
            else:
                raise ValueError(f"CYBER_SOURCE_KIND_UNSUPPORTED:{kind}")

            output = {
                "ok": True,
                "source_id": source_id,
                "source_name": source.get("name"),
                "kind": kind,
                "bytes": len(raw),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                **result,
            }
            self._record_sync(source_id, output)
            return output
        except Exception as exc:
            output = {
                "ok": False,
                "source_id": source_id,
                "source_name": source.get("name"),
                "error": type(exc).__name__,
                "message": str(exc),
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            }
            self._record_sync(source_id, output)
            return output

    def sync(
        self,
        *,
        full: bool = False,
        source_id: str = "",
    ) -> dict[str, Any]:
        if source_id:
            results = [self.sync_source(source_id)]
        else:
            selected = [
                source
                for source in self.sources()
                if full or source.get("auto_sync") is True
            ]
            results = [
                self.sync_source(str(source["id"]))
                for source in selected
            ]

        ok_count = sum(1 for x in results if x.get("ok"))
        failed = len(results) - ok_count
        return {
            "ok": failed == 0,
            "mode": "full" if full else "standard",
            "sources_attempted": len(results),
            "sources_ok": ok_count,
            "sources_failed": failed,
            "results": results,
            "stats": self.stats(),
        }

    def _load_state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _record_sync(
        self,
        source_id: str,
        result: dict[str, Any],
    ) -> None:
        state = self._load_state()
        state.setdefault("sources", {})
        state["sources"][source_id] = {
            "last_attempt": _now(),
            "ok": bool(result.get("ok")),
            "documents": result.get("documents"),
            "changed": result.get("changed"),
            "error": result.get("error"),
            "message": result.get("message"),
        }
        state["last_sync_attempt"] = _now()
        if result.get("ok"):
            state["last_successful_sync"] = _now()
        self.state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def stale(self, hours: int = 24) -> bool:
        last = self._load_state().get("last_successful_sync")
        if not last:
            return True
        try:
            dt = datetime.fromisoformat(last)
            return datetime.now().astimezone() - dt > timedelta(hours=hours)
        except Exception:
            return True

    def search(
        self,
        query: str,
        limit: int = 8,
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "EMPTY_QUERY"}

        limit = max(1, min(int(limit), 20))
        rows = []
        with self._db() as conn:
            if self._fts:
                tokens = re.findall(r"[\w.-]+", query, flags=re.UNICODE)
                if tokens:
                    match = " AND ".join(
                        '"' + token.replace('"', '""') + '"'
                        for token in tokens[:12]
                    )
                    try:
                        rows = conn.execute("""
                            SELECT d.*, bm25(documents_fts) AS rank
                            FROM documents_fts
                            JOIN documents d ON d.id = documents_fts.doc_id
                            WHERE documents_fts MATCH ?
                            ORDER BY rank
                            LIMIT ?
                        """, (match, limit)).fetchall()
                    except sqlite3.OperationalError:
                        rows = []

            if not rows:
                tokens = re.findall(r"[\w.-]+", query, flags=re.UNICODE)[:8]
                pattern = "%" + "%".join(tokens) + "%"
                rows = conn.execute("""
                    SELECT *, 0.0 AS rank
                    FROM documents
                    WHERE lower(title || ' ' || body) LIKE lower(?)
                    ORDER BY
                        CASE trust
                            WHEN 'official' THEN 0
                            WHEN 'official-repository' THEN 1
                            WHEN 'curated' THEN 2
                            ELSE 3
                        END,
                        retrieved_at DESC
                    LIMIT ?
                """, (pattern, limit)).fetchall()

        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "title": row["title"],
                "snippet": self._snippet(str(row["body"] or ""), query),
                "source_id": row["source_id"],
                "external_id": row["external_id"],
                "publisher": row["publisher"],
                "category": row["category"],
                "trust": row["trust"],
                "provenance": row["provenance"],
                "url": row["url"],
                "published": row["published"],
                "source_updated": row["source_updated"],
                "retrieved_at": row["retrieved_at"],
            })
        return {
            "ok": True,
            "query": query,
            "count": len(results),
            "results": results,
            "knowledge_scope": "local-cyber-vault",
        }

    @staticmethod
    def _snippet(body: str, query: str, max_chars: int = 650) -> str:
        terms = [
            x.lower()
            for x in re.findall(r"[\w.-]+", query, flags=re.UNICODE)
            if len(x) >= 3
        ]
        low = body.lower()
        positions = [
            low.find(term)
            for term in terms
            if low.find(term) >= 0
        ]
        center = min(positions) if positions else 0
        start = max(0, center - 180)
        end = min(len(body), start + max_chars)
        text = body[start:end].strip()
        if start:
            text = "…" + text
        if end < len(body):
            text += "…"
        return text

    def ingest_local_file(
        self,
        path: str,
        *,
        category: str = "user-library",
    ) -> dict[str, Any]:
        p = Path(path).expanduser()
        if not p.exists() or not p.is_file():
            return {"ok": False, "error": "FILE_NOT_FOUND", "path": str(p)}

        ext = p.suffix.lower()
        try:
            if ext in {".txt",".md",".csv",".json",".log",".py"}:
                body = p.read_text(encoding="utf-8", errors="replace")
            elif ext == ".pdf":
                try:
                    from pypdf import PdfReader
                except Exception:
                    return {"ok": False, "error": "PYPDF_NOT_INSTALLED"}
                reader = PdfReader(str(p))
                body = "\n".join(
                    page.extract_text() or ""
                    for page in reader.pages
                )
            else:
                return {
                    "ok": False,
                    "error": "UNSUPPORTED_FILE_TYPE",
                    "extension": ext,
                }
        except Exception as exc:
            return {
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc),
            }

        digest = sha256(p.read_bytes()).hexdigest()
        _, changed = self._upsert(
            source_id="local_user_library",
            external_id=digest,
            title=p.name,
            body=body,
            category=category,
            publisher="Local user file",
            trust="user-provided",
            provenance="local-file-import",
            metadata={
                "filename": p.name,
                "path": str(p),
                "file_sha256": digest,
            },
        )
        return {
            "ok": True,
            "file": str(p),
            "changed": changed,
            "sha256": digest,
        }

    def stats(self) -> dict[str, Any]:
        with self._db() as conn:
            total = int(conn.execute(
                "SELECT count(*) AS n FROM documents"
            ).fetchone()["n"])
            rows = conn.execute("""
                SELECT source_id,publisher,trust,count(*) AS n,
                       max(retrieved_at) AS latest
                FROM documents
                GROUP BY source_id,publisher,trust
                ORDER BY n DESC
            """).fetchall()

        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {
            "ok": True,
            "schema_version": SCHEMA_VERSION,
            "database": str(self.db_path),
            "documents": total,
            "database_mb": round(size / 1024**2, 2),
            "fts5": self._fts,
            "sources": [
                {
                    "source_id": row["source_id"],
                    "publisher": row["publisher"],
                    "trust": row["trust"],
                    "documents": int(row["n"]),
                    "latest": row["latest"],
                }
                for row in rows
            ],
            "sync_state": self._load_state(),
        }

    def knowledge_context(
        self,
        query: str,
        limit: int = 6,
    ) -> str:
        result = self.search(query, limit=limit)
        rows = result.get("results") or []
        if not rows:
            return ""

        parts = [
            "LOCAL CYBER KNOWLEDGE VAULT — retrieved evidence. "
            "Prefer official sources over curated seed notes. "
            "Distinguish stored evidence from general model knowledge."
        ]
        for i, row in enumerate(rows, start=1):
            source = row.get("publisher") or row.get("source_id") or "source"
            parts.append(
                f"[K{i}] {row.get('title')} | {source} | "
                f"trust={row.get('trust')} | provenance={row.get('provenance')}\n"
                f"{row.get('snippet')}\n"
                f"Source: {row.get('url') or 'local'}"
            )
        return "\n\n".join(parts)


_VAULT: CyberKnowledgeVault | None = None


def cyber_vault() -> CyberKnowledgeVault:
    global _VAULT
    if _VAULT is None:
        _VAULT = CyberKnowledgeVault()
    return _VAULT


def get_cyber_knowledge_status() -> dict[str, Any]:
    return cyber_vault().stats()


def search_cyber_knowledge(
    query: str,
    limit: int = 8,
) -> dict[str, Any]:
    return cyber_vault().search(query, limit=limit)


def sync_cyber_knowledge(
    full: bool = False,
    source_id: str = "",
) -> dict[str, Any]:
    return cyber_vault().sync(full=full, source_id=source_id)


def ingest_cyber_document(
    path: str,
    category: str = "user-library",
) -> dict[str, Any]:
    return cyber_vault().ingest_local_file(path, category=category)


class CyberKnowledgeService:
    """
    Refreshes standard official sources in the background.

    Bulk MITRE ATT&CK STIX is intentionally excluded from automatic first-run
    sync and is added with `/cyber knowledge sync full`.
    """

    def __init__(
        self,
        events,
        *,
        enabled: bool = True,
        startup_delay_seconds: float = 120.0,
        interval_hours: float = 24.0,
        resource_guard=None,
    ):
        self.events = events
        self.enabled = bool(enabled)
        self.startup_delay_seconds = max(10.0, float(startup_delay_seconds))
        self.interval_seconds = max(3600.0, float(interval_hours) * 3600.0)
        self._stop = Event()
        self._thread: Thread | None = None
        self.resource_guard = resource_guard

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._loop,
            name="jarvis-cyber-knowledge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        if self._stop.wait(self.startup_delay_seconds):
            return

        while not self._stop.is_set():
            try:
                if (
                    self.resource_guard is not None
                    and self.resource_guard("cyber_knowledge")
                ):
                    self.events.emit(
                        "BACKGROUND_WORK_DEFERRED",
                        workload="cyber_knowledge",
                    )
                    if self._stop.wait(
                        min(300.0, self.interval_seconds)
                    ):
                        return
                    continue

                vault = cyber_vault()
                hours = max(1, int(self.interval_seconds / 3600))
                if vault.stale(hours=hours):
                    self.events.emit(
                        "CYBER_KNOWLEDGE_SYNC_STARTED",
                        mode="standard",
                    )
                    result = vault.sync(full=False)
                    self.events.emit(
                        "CYBER_KNOWLEDGE_SYNC_FINISHED",
                        ok=result.get("ok"),
                        sources_ok=result.get("sources_ok"),
                        sources_failed=result.get("sources_failed"),
                        documents=(result.get("stats") or {}).get("documents"),
                    )
            except Exception as exc:
                self.events.emit(
                    "CYBER_KNOWLEDGE_SYNC_ERROR",
                    error=f"{type(exc).__name__}: {exc}",
                )

            if self._stop.wait(self.interval_seconds):
                return
