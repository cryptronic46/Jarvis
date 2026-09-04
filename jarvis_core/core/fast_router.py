from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import json
import re
from time import time
from typing import Any
import unicodedata


@dataclass(slots=True)
class FastRouteResult:
    handled: bool
    response: str = ""
    route: str | None = None
    tool: str | None = None


def _normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w%]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_app(value: str) -> str:
    """Normalize app names while preserving meaningful '+' identity."""
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w%+]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _parse_tool_result(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"ok": True, "value": value}
    except Exception:
        return {"ok": False, "error": "INVALID_TOOL_RESULT", "message": raw}


def _strip_jarvis_vocative(value: str) -> str:
    return re.sub(
        r"^\s*(?:jarvis|jervis|jarves|jarviz|zarbis|zarvis|jarbis)\s*[,;:\-]?\s*",
        "",
        str(value or ""),
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _clean_memory_fact(value: str) -> str:
    text = str(value or "").strip()
    # A forceful instruction such as "Isto e uma ordem" is authority metadata,
    # not part of the fact that belongs in memory.
    text = re.sub(
        r"(?:[.!?]\s*)+(?:isto\s+e|isto\s+é|e)\s+uma\s+ordem[.!?]*\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text.rstrip(" .!?").strip()


def _extract_explicit_memory_fact(value: str) -> str | None:
    """Return the exact fact from a high-confidence explicit local-memory order.

    This parser deliberately handles memory intent before the LLM so a model
    cannot invent a blanket privacy refusal for ordinary personal facts. It
    only handles clear commands that explicitly mention memory/remembering.
    """
    raw = _strip_jarvis_vocative(value)
    if not raw:
        return None

    patterns = (
        # Fact first, then a reference to "this information".
        r"^(?P<fact>.+?)(?:\s+e\s+|[.!?]\s*)(?:eu\s+)?(?:quero|pretendo)\s+que\s+(?:guardes|memorizes|recordes)\s+(?:esta|essa|a)\s+informa[cç][aã]o(?:\s+(?:na|em)\s+(?:tua\s+)?mem[oó]ria)?(?:[.!?].*)?$",
        # Command first: "quero que guardes na memoria que X".
        r"^(?:eu\s+)?(?:quero|pretendo)\s+que\s+(?:guardes|memorizes|recordes)\s+(?:(?:esta|essa|a)\s+informa[cç][aã]o\s*)?(?:(?:na|em)\s+(?:tua\s+)?mem[oó]ria\s*)?(?::|de\s+que|que)\s*(?P<fact>.+)$",
        # "guarda na memoria: X" / "memoriza que X".
        r"^(?:guarda|memoriza|recorda|lembra[ -]?te)\s+(?:(?:esta|essa|a)\s+informa[cç][aã]o\s*)?(?:(?:na|em)\s+(?:tua\s+)?mem[oó]ria\s*)?(?::|que)\s*(?P<fact>.+)$",
        # Natural direct write orders: "memoriza o nome da minha mulher..."
        # or "quero que memorizes o nome...". These are already explicit
        # memory instructions and do not need a second confirmation turn.
        r"^(?:eu\s+)?(?:quero|pretendo)\s+que\s+memorizes\s+(?P<fact>.+)$",
        r"^memoriza\s+(?P<fact>.+)$",
        # "guarda X na tua memoria". Require the explicit memory suffix.
        r"^(?:guarda|memoriza|recorda)\s+(?P<fact>.+?)\s+(?:na|em)\s+(?:tua\s+)?mem[oó]ria(?:[.!?].*)?$",
    )
    for pattern in patterns:
        match = re.match(pattern, raw, flags=re.IGNORECASE | re.DOTALL)
        if match:
            fact = _clean_memory_fact(match.group("fact"))
            deictic = _normalize(fact)
            if deictic in {
                "isso", "isto", "essa informacao", "esta informacao",
                "a informacao", "essa", "esta",
            }:
                return None
            return fact or None
    return None


class FastCommandRouter:
    """
    High-confidence deterministic commands that bypass the LLM while still
    executing through ToolRegistry/SecurityPolicy.
    """

    OPEN_WORDS = {
        "abre", "abra", "abrir", "abrem", "abri", "abrir o",
        "inicia", "inicie", "iniciar",
        "lanca", "lance", "lancar",
        "executa", "execute", "executar",
    }
    CLOSE_WORDS = {
        "fecha", "feche", "fechar",
        "encerra", "encerre", "encerrar",
        "termina", "termine", "terminar",
    }
    # Narrow ASR repairs used only for voice-origin commands that also name an
    # application already present in apps.json. This is intentionally NOT a
    # general fuzzy-language matcher.
    VOICE_OPEN_ASR_WORDS = {
        "agrade",  # observed pt-PT Whisper confusion for "abre"
        "abro", "abram",
    }

    def __init__(self, events, tools, apps):
        self.events = events
        self.tools = tools
        self.apps = apps
        self._last_local_file_results: list[dict[str, Any]] = []
        self._last_local_document: dict[str, Any] | None = None
        self._last_task_plan_id: str | None = None
        self._last_learning_provenance: dict[str, Any] | None = None

    def _hit(self, response: str, route: str, tool: str) -> FastRouteResult:
        self.events.emit("FAST_PATH_HIT", route=route, tool=tool)
        return FastRouteResult(True, response=response, route=route, tool=tool)

    def _tool(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return _parse_tool_result(self.tools.execute(name, args or {}))

    @staticmethod
    def _format_app_open_result(app_name: str, data: dict[str, Any]) -> str:
        if not data.get("ok"):
            return data.get("message") or f"Não consegui abrir {app_name}: {data.get('error', 'erro desconhecido')}."
        if data.get("already_running"):
            return f"{app_name} já estava em execução; não abri outra instância."
        if "effect_verified" not in data:
            return f"{app_name} aberto."
        if data.get("effect_verified"):
            return f"{app_name} aberto e confirmado em execução."
        return f"Enviei o pedido para abrir {app_name}, mas ainda não consegui confirmar o processo."
    def _app_match(self, normalized: str, raw_text: str = ""):
        # Application names may contain semantic punctuation (Notepad++). Do not
        # collapse that punctuation and accidentally alias a different app.
        raw_norm = _normalize_app(raw_text or normalized)
        haystack = f" {raw_norm} "
        matches = []
        for item in self.apps.list_apps():
            values = [item["id"], item["name"], *item.get("aliases", [])]
            for value in values:
                candidate = _normalize_app(str(value))
                if candidate and f" {candidate} " in haystack:
                    matches.append((len(candidate), item))
        if not matches:
            return None
        matches.sort(key=lambda row: row[0], reverse=True)
        return matches[0][1]

    @staticmethod
    def _humanize_self_target(value: Any) -> str:
        target = str(value or "").strip()
        mapping = {
            "current_owner_message": "a nossa conversa atual",
            "owner_message": "a mensagem atual do Senhor",
            "conversation": "a nossa conversa",
            "active_task": "a tarefa atual",
        }
        return mapping.get(target, target.replace("_", " ") if target else "")

    @staticmethod
    def _level_word(value: Any) -> str:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return "indefinida"
        if score >= 0.75:
            return "alta"
        if score >= 0.45:
            return "moderada"
        if score >= 0.20:
            return "baixa"
        return "muito baixa"

    @staticmethod
    def _relation_from_graph(data: dict[str, Any], relation: str = "PARTNER") -> tuple[str | None, str | None]:
        nodes = {
            str(row.get("id") or ""): row
            for row in list(data.get("nodes") or [])
            if isinstance(row, dict)
        }
        for edge in list(data.get("edges") or []):
            if not isinstance(edge, dict) or str(edge.get("relation") or "").upper() != relation.upper():
                continue
            target = nodes.get(str(edge.get("target") or "")) or {}
            source = nodes.get(str(edge.get("source") or "")) or {}
            target_label = str(target.get("label") or "").strip()
            source_label = str(source.get("label") or "").strip()
            if target_label:
                return target_label, relation.upper()
            if source_label and source_label.upper() not in {"OWNER", "SENHOR"}:
                return source_label, relation.upper()
        # Fallback to explicit fact wording when edge targets were outside the
        # bounded result set.
        for row in list(data.get("nodes") or []):
            if not isinstance(row, dict) or str(row.get("kind") or "") != "fact":
                continue
            label = str(row.get("label") or "")
            match = re.search(
                r"(?:nome da minha (?:mulher|esposa|companheira) (?:e|é)|"
                r"(?:minha|a minha) (?:mulher|esposa|companheira) (?:se chama|chama-se|e|é))\s+([^,.;]+)",
                label,
                flags=re.IGNORECASE,
            )
            if match:
                return match.group(1).strip(), relation.upper()
        return None, None

    @staticmethod
    def _format_direct_tool(name: str, data: dict[str, Any]) -> str:
        if not data.get("ok", True) or data.get("error"):
            return str(data.get("message") or data.get("error") or f"A ferramenta {name} falhou.")
        if name == "get_user_profile":
            profile = data.get("profile") or {}
            home = profile.get("home") or {}
            parts = []
            if profile.get("name"):
                parts.append(f"nome={profile.get('name')}")
            if profile.get("address_as"):
                parts.append(f"tratamento={profile.get('address_as')}")
            if home.get("label"):
                parts.append(f"casa={home.get('label')}")
            return "Perfil de utilizador local: " + ("; ".join(parts) if parts else "sem campos preenchidos") + "."
        if name == "get_personal_model":
            model = data.get("model") if isinstance(data.get("model"), dict) else data
            counts = {
                "preferências": len(list(model.get("preferences") or [])),
                "objetivos OWNER": len(list(model.get("goals") or [])),
                "restrições": len(list(model.get("constraints") or [])),
                "projetos": len(list(model.get("projects") or [])),
                "objetivos de aprendizagem do OWNER": len(list(model.get("owner_learning_goals") or [])),
                "diretivas para a JARVIS": len(list(model.get("jarvis_directives") or [])),
                "objetivos de aprendizagem da JARVIS": len(list(model.get("jarvis_learning_goals") or [])),
            }
            return "Modelo pessoal local consultado: " + "; ".join(f"{k}={v}" for k, v in counts.items()) + "."
        if name == "get_synthetic_self_state":
            affect = data.get("affect") or {}
            focus = str(data.get("current_focus") or "idle")
            intentions = list(data.get("active_intentions") or [])
            return (
                f"Estado interno real: foco={focus}; confiança={round(float(affect.get('confidence', 0))*100, 1)}%; "
                f"curiosidade={round(float(affect.get('curiosity', 0))*100, 1)}%; "
                f"carga cognitiva={round(float(affect.get('cognitive_load', 0))*100, 1)}%; "
                f"intenções ativas={len(intentions)}."
            )
        if name == "get_functional_self_model":
            model = data.get("self_model") or {}
            return (
                "Modelo funcional local: "
                f"identidade={model.get('identity', 'JARVIS')}; "
                f"capacidades={len(list(model.get('capabilities') or []))}; "
                f"restrições={len(list(model.get('constraints') or []))}; "
                f"consciência subjetiva={model.get('subjective_consciousness_status', 'não estabelecida')}."
            )
        if name == "get_system_status":
            osinfo = data.get("os") or {}
            cpu = data.get("cpu") or {}
            memory = data.get("memory") or {}
            gpus = list(data.get("gpus") or [])
            response = f"{osinfo.get('system','Windows')} {osinfo.get('release','')} (build {osinfo.get('version','?')})."
            if cpu.get("usage_percent") is not None:
                response += f" CPU: {cpu.get('usage_percent')}%."
            if memory.get("used_percent") is not None:
                response += f" RAM: {memory.get('used_percent')}%."
            if gpus and (gpus[0] or {}).get("utilization_percent") is not None:
                response += f" GPU: {(gpus[0] or {}).get('utilization_percent')}%."
            return response
        rendered = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return rendered if len(rendered) <= 2200 else rendered[:2197] + "..."

    @staticmethod
    def _learning_query_from_text(raw_text: str) -> str:
        raw = _strip_jarvis_vocative(raw_text)
        quoted = re.search(r'["“”]([^"“”]{2,300})["“”]', raw)
        if quoted:
            return quoted.group(1).strip()
        match = re.search(
            r"(?i)\b(?:por|sobre|acerca de)\s+(.+?)(?:\s+e\s+(?:mostra|diz|devolve)|[.!?]?$)",
            raw,
        )
        if match:
            return match.group(1).strip(" .,:;!?")[:300]
        return ""

    def _learning_exact_response(self, text: str, normalized: str) -> FastRouteResult | None:
        learning_domain = (
            "aprendizagem autorizada" in normalized
            or "pesquisa autorizada" in normalized
            or (("aprendizagem" in normalized or "aprendizagens" in normalized) and "quarentena" in normalized)
            or ("quarentena" in normalized and any(marker in normalized for marker in ("topicos", "motivos", "razoes", "razões")))
        )
        if not learning_domain:
            return None

        # Quarantine inspection has its own audit-only tool; active search must
        # never pretend that quarantined records do not exist.
        if "quarentena" in normalized and any(word in normalized for word in ("mostra", "quais", "lista", "porque", "motivo", "razao", "razão")):
            query = self._learning_query_from_text(text)
            data = self._tool("list_quarantined_learning", {"query": query, "limit": 30})
            rows = list(data.get("results") or []) if data.get("ok") else []
            if not rows:
                return self._hit("Não encontrei entradas de aprendizagem em quarentena que correspondam ao pedido.", "learning_quarantine", "list_quarantined_learning")
            reasons: dict[str, int] = {}
            for row in rows:
                reason = str(row.get("quarantine_reason") or "sem_motivo_registado")
                reasons[reason] = reasons.get(reason, 0) + 1
            only_topics = (
                (("apenas" in normalized or "nao expliques" in normalized) and "topicos" in normalized)
                or "nomes dos topicos" in normalized
                or "nome dos topicos" in normalized
            )
            topics_and_reasons = any(marker in normalized for marker in ("topicos e os motivos", "topicos e motivos", "topico e motivo"))
            if only_topics and not topics_and_reasons:
                topics = []
                for row in rows:
                    original = row.get("original") if isinstance(row.get("original"), dict) else {}
                    topic = str(original.get("topic") or "").strip()
                    if topic and topic not in topics:
                        topics.append(topic)
                return self._hit("\n".join(topics) if topics else "(sem tópicos registados)", "learning_quarantine_topics", "list_quarantined_learning")
            if topics_and_reasons:
                output, seen = [], set()
                for row in rows:
                    original = row.get("original") if isinstance(row.get("original"), dict) else {}
                    topic = str(original.get("topic") or "(sem tópico)").strip()
                    reason = str(row.get("quarantine_reason") or "sem_motivo_registado")
                    key = (topic, reason)
                    if key not in seen:
                        seen.add(key); output.append(f"{topic} | motivo={reason}")
                return self._hit("\n".join(output), "learning_quarantine_topics_reasons", "list_quarantined_learning")
            if any(word in normalized for word in ("porque", "motivo", "razao", "razão")):
                response = "Motivos registados na quarentena: " + "; ".join(f"{reason}={count}" for reason, count in reasons.items()) + "."
                return self._hit(response, "learning_quarantine_reason", "list_quarantined_learning")
            lines = []
            for idx, row in enumerate(rows[:20], start=1):
                original = row.get("original") if isinstance(row.get("original"), dict) else {}
                lines.append(
                    f"{idx}. {original.get('topic') or '(sem tópico)'} | motivo={row.get('quarantine_reason') or 'não registado'} | "
                    f"data={row.get('quarantined_at') or '?'}"
                )
            return self._hit("\n".join(lines), "learning_quarantine", "list_quarantined_learning")

        # Exact/audit-style learning retrieval is deterministic to preserve URLs,
        # counts and JSON fields byte-for-byte instead of asking Qwen to retype them.
        audit_style = any(marker in normalized for marker in (
            "sem interpretar", "sem completar", "exatamente", "exactamente",
            "apenas as urls", "apenas urls", "registo completo", "registro completo",
            "registos encontrados", "registros encontrados", "mostra apenas topico",
            "apenas os topicos encontrados", "apenas topicos encontrados",
        ))
        generic_search = any(marker in normalized for marker in (
            "procura na tua aprendizagem autorizada",
            "pesquisa na tua aprendizagem autorizada",
            "procura na aprendizagem autorizada",
        ))
        if not audit_style and not generic_search:
            return None

        query = self._learning_query_from_text(text)
        # For source-filter requests, search by topical phrase first and filter
        # sources by the named domain locally.
        domain_match = re.search(r"(?i)\b(?:fonte seja|fonte e|fonte é|fonte contenha|fonte contém|dominio|domínio)\s+([a-z0-9.-]+\.[a-z]{2,})", text)
        domain = domain_match.group(1).lower() if domain_match else ""
        search_query = query
        if domain and (not search_query or domain in search_query.lower()):
            topic_match = re.search(r"(?i)\bregistos?\s+sobre\s+(.+?)\s+cuja\s+fonte", text)
            if topic_match:
                search_query = topic_match.group(1).strip()
        data = self._tool("search_authorized_learning", {"query": search_query or query, "limit": 30})
        rows = list(data.get("results") or []) if data.get("ok") else []
        if domain:
            rows = [
                row for row in rows
                if any(domain in str(src.get("url") or "").lower() for src in list(row.get("sources") or []) if isinstance(src, dict))
            ]
        if not rows:
            return self._hit("Não encontrei registos correspondentes na aprendizagem autorizada.", "learning_exact_search", "search_authorized_learning")

        if "apenas as urls" in normalized or "apenas urls" in normalized or "devolve exatamente a url" in normalized:
            urls = []
            for row in rows:
                for src in list(row.get("sources") or []):
                    if isinstance(src, dict):
                        url = str(src.get("url") or "").strip()
                        if url and url not in urls:
                            urls.append(url)
            return self._hit("\n".join(urls) if urls else "Não há URLs guardadas nesses registos.", "learning_exact_urls", "search_authorized_learning")

        if "registo completo" in normalized or "registro completo" in normalized:
            return self._hit(json.dumps(rows[0], ensure_ascii=False, indent=2), "learning_exact_record", "search_authorized_learning")

        if "apenas os topicos encontrados" in normalized or "apenas topicos encontrados" in normalized:
            topics = []
            for row in rows:
                topic = str(row.get("topic") or "").strip()
                if topic and topic not in topics:
                    topics.append(topic)
            return self._hit("\n".join(f"{idx}. {topic}" for idx, topic in enumerate(topics, start=1)), "learning_exact_topics", "search_authorized_learning")

        if generic_search and not audit_style:
            blocks = []
            for idx, row in enumerate(rows[:5], start=1):
                summary = re.sub(r"\s+", " ", str(row.get("summary") or "")).strip()
                if len(summary) > 1200:
                    summary = summary[:1197].rstrip() + "..."
                retrieval = row.get("retrieval_match") if isinstance(row.get("retrieval_match"), dict) else {}
                match_note = ""
                if retrieval and retrieval.get("literal_query_match") is False:
                    match_note = " [correspondência semântica; a consulta literal não aparece no registo]"
                urls = [str(src.get("url") or "") for src in list(row.get("sources") or []) if isinstance(src, dict) and str(src.get("url") or "")]
                blocks.append(
                    f"{idx}. {row.get('topic') or '(sem tópico)'}{match_note}\n"
                    f"Resumo guardado: {summary}\n"
                    f"Fontes: " + ("; ".join(urls) if urls else "sem URLs guardadas")
                )
            return self._hit("\n\n".join(blocks), "learning_search", "search_authorized_learning")

        # Minimal exact records view.
        lines = []
        for idx, row in enumerate(rows[:20], start=1):
            urls = [str(src.get("url") or "") for src in list(row.get("sources") or []) if isinstance(src, dict) and str(src.get("url") or "")]
            lines.append(
                f"{idx}. tópico={row.get('topic') or ''} | data={row.get('learned_at') or row.get('timestamp') or ''} | urls=" + ", ".join(urls)
            )
        return self._hit("\n".join(lines), "learning_exact_search", "search_authorized_learning")

    def dispatch(self, text: str, *, voice_origin: bool = False) -> FastRouteResult:
        text = re.sub(
            r"^\s*(?:\[\s*\d+\s*\]|(?:teste|test|t)\s*\d+|(?:quest[aã]o\s*)?\d+)\s*[\].:)\-]*\s*",
            "", str(text or ""), flags=re.IGNORECASE,
        )
        normalized = _normalize(text)
        if not normalized:
            return FastRouteResult(False)

        normalized = re.sub(r"^(jarvis|jervis|jarves|jarviz|zarbis|zarvis|jarbis)\s+", "", normalized).strip()
        words = set(normalized.split())
        self.tools.request_started_at = time()

        # 0.27.6 conversation hotfix: social dialogue is intentionally NOT a
        # deterministic Fast Path. Thanks, praise, greetings and goodbyes go to
        # the conversational model so tone and the immediately preceding turn
        # can influence the answer. Fast Path is reserved for high-confidence
        # commands and factual runtime status.
        if normalized in {
            "estas a ouvir me", "estas a ouvir", "consegues ouvir me",
            "consegues ouvir", "ouves me",
        }:
            return self._hit("Sim, Senhor.", "social_listening", "none")

        external_ai_phrases = (
            "outra inteligencia artificial", "outra ia", "consulta o chatgpt",
            "consulta chatgpt", "pergunta ao chatgpt", "usa o chatgpt",
            "usa a openai", "usa openai", "usa a cloud", "usa cloud",
            "gpt 5 6 sol",
        )
        provider_request = bool(re.search(
            r"\b(?:usa|utiliza|usando|utilizando|consulta|pergunta\s+(?:ao|a)|recorre\s+(?:ao|a)|confirma\s+com|valida\s+com|pede\s+(?:ao|a))\s+(?:o\s+|a\s+)?(?:gemini|google gemini|claude|anthropic|perplexity|microsoft copilot|copilot|grok|xai|x ai|deepseek|deep seek|le chat|meta ai|chatgpt|openai)\b",
            normalized,
        ))
        if any(phrase in normalized for phrase in external_ai_phrases) or provider_request or normalized.startswith("cloud "):
            return self._hit(
                "Não posso consultar outra inteligência artificial, Senhor. Essa rota está bloqueada no Core. Posso usar o meu cérebro local e, quando necessário, fontes públicas da Web com síntese local.",
                "external_ai_blocked", "none",
            )

        # 0.27.8 v9 — exact zero-argument tool invocation.  Commands such as
        # "executa get_system_status" previously fell into OPERATIONAL_ACTION,
        # exposed no schemas and let Qwen pretend that work had started.
        raw_no_vocative = _strip_jarvis_vocative(text).strip()
        direct_tool = re.match(
            r"(?i)^(?:executa|corre|chama|invoca)\s+([a-z_][a-z0-9_]*)\s*[.!?]?$",
            raw_no_vocative,
        )
        if direct_tool:
            tool_name = direct_tool.group(1)
            if tool_name in self.tools.names:
                valid, detail = self.tools.validate_arguments(tool_name, {})
                if not valid:
                    return self._hit(
                        f"A ferramenta {tool_name} requer parâmetros; não a executei sem esses dados.",
                        "explicit_tool_requires_arguments",
                        "none",
                    )
                data = self._tool(tool_name, {})
                return self._hit(
                    self._format_direct_tool(tool_name, data),
                    "explicit_tool_call",
                    tool_name,
                )
            return self._hit(
                f"A ferramenta {tool_name} não está registada neste Core; não executei nenhuma ação.",
                "explicit_tool_unknown",
                "none",
            )

        # For "usa/utiliza <tool> para ..." preserve the exact OWNER-selected
        # tool and let the normal tool-calling path derive its arguments. Do not
        # let semantic fast paths silently substitute another memory/security tool.
        named_tool_with_args = re.match(
            r"(?i)^(?:usa|utiliza)\s+([a-z_][a-z0-9_]*)\b",
            raw_no_vocative,
        )
        if named_tool_with_args and named_tool_with_args.group(1) in self.tools.names:
            return FastRouteResult(False)

        # A compact code-format probe is deterministic so the OWNER can verify
        # that the terminal preserves literal Python indentation independently
        # of a small model's code-generation reliability.
        if (
            "exemplo python" in normalized
            and "indentado" in normalized
            and "bloco" in normalized
            and any(word in normalized.split() for word in ("mostra", "mostrar"))
        ):
            response = "```python\ndef soma(a, b):\n    resultado = a + b\n    return resultado\n\nprint(soma(3, 5))\n```"
            return self._hit(response, "python_indentation_probe", "none")

        learning_exact = self._learning_exact_response(text, normalized)
        if learning_exact is not None:
            return learning_exact

        local_pdf_lookup = (
            "pdf" in normalized
            and any(word in normalized.split() for word in ("ficheiro", "ficheiros", "arquivo", "arquivos"))
            and any(word in normalized.split() for word in ("procura", "procurar", "encontra", "encontrar", "buscar"))
        )
        local_paths_followup = not local_pdf_lookup and any(phrase in normalized for phrase in (
            "mostra apenas os caminhos dos ficheiros que encontraste",
            "mostra so os caminhos dos ficheiros que encontraste",
            "apenas os caminhos dos ficheiros encontrados",
            "mostra os caminhos",
        ))
        if local_paths_followup and not self._last_local_file_results:
            return self._hit(
                "Não tenho resultados de uma pesquisa local anterior nesta sessão. Peça-me primeiro para procurar os ficheiros.",
                "local_file_followup_paths_empty", "none",
            )
        if self._last_local_file_results and local_paths_followup:
            paths = [str(row.get("path") or "").strip() for row in self._last_local_file_results if str(row.get("path") or "").strip()]
            return self._hit("\n".join(paths), "local_file_followup_paths", "none")

        open_first_followup = not local_pdf_lookup and any(phrase in normalized for phrase in (
            "abre o primeiro", "abre o primeiro ficheiro", "abre o primeiro documento",
        ))
        if open_first_followup and not self._last_local_file_results:
            return self._hit(
                "Não abri nenhuma aplicação nem ficheiro: não tenho resultados de uma pesquisa local anterior nesta sessão.",
                "local_file_followup_open_first_empty", "none",
            )
        if open_first_followup and self._last_local_file_results:
            path = str(self._last_local_file_results[0].get("path") or "")
            data = self._tool("open_local_document", {"path": path, "app_name": "brave"})
            if data.get("ok"):
                response = f"Enviei {Path(path).name} para abrir visualmente no Brave."
            else:
                response = data.get("message") or data.get("error") or "Não consegui abrir o primeiro documento da lista."
            return self._hit(response, "local_file_followup_open_first", "open_local_document")

        if self._last_local_file_results and any(phrase in normalized for phrase in (
            "qual e o mais recente", "qual deles e o mais recente", "ficheiro mais recente",
        )):
            row = max(self._last_local_file_results, key=lambda item: str(item.get("modified") or ""))
            return self._hit(f"O mais recente é {row.get('path') or row.get('name')}, modificado em {row.get('modified') or 'data não disponível'}.", "local_file_followup_recent", "none")

        if self._last_local_file_results and any(phrase in normalized for phrase in (
            "le o primeiro documento da lista", "le o primeiro ficheiro da lista",
            "abre e le o primeiro documento", "ler o primeiro documento",
        )):
            path = str(self._last_local_file_results[0].get("path") or "")
            data = self._tool("read_local_document", {"path": path, "max_chars": 20000})
            if data.get("ok"):
                self._last_local_document = data
                body = str(data.get("text") or "").strip()
                response = f"Li {data.get('name') or path}.\n{body[:4000]}" + ("…" if len(body) > 4000 else "")
            else:
                response = data.get("message") or data.get("error") or "Não consegui ler o primeiro documento da lista."
            return self._hit(response, "local_file_followup_read_first", "read_local_document")

        whole_computer_match = re.search(r"(?i)\bprocura\s+(.+?)\s+no\s+computador\s+inteiro\b", text)
        if whole_computer_match:
            query = whole_computer_match.group(1).strip(" .?!\"")
            data = self._tool("search_local_files", {"query": query, "limit": 50})
            rows = list(data.get("results") or []) if data.get("ok") else []
            self._last_local_file_results = rows
            paths = [str(row.get("path") or row.get("name") or "") for row in rows[:20]]
            response = (f"Encontrei {len(rows)} ficheiro(s) relacionado(s) com {query}: " + "; ".join(paths) + ".") if rows else f"Não encontrei ficheiros locais relacionados com {query}."
            return self._hit(response, "local_file_computer_search", "search_local_files")
        if words.intersection({"cria", "criar", "crie"}) and words.intersection({"ficheiro", "arquivo"}):
            return self._hit(
                "Não criei nenhum ficheiro. Este Core não tem uma ferramenta de escrita local registada; por segurança, não vou fingir a criação nem transformar o pedido numa leitura.",
                "local_file_create_unsupported", "none",
            )
        # Explicit PDF file lookups use the safe local file index.  A PDF can
        # also be a book, but that is a different request: search_book_library
        # searches book passages, while this route searches file names/paths.
        if local_pdf_lookup:
            compound_show_paths = "mostra os caminhos" in normalized
            compound_open_first = "abre o primeiro" in normalized
            name_match = re.search(r"\bcom\s+(.+?)\s+no\s+nome\b", normalized)
            query_match = re.search(r"\b(?:relacionad[oa]s?\s+com|sobre|de)\s+(.+)$", normalized)
            query = name_match.group(1).strip() if name_match else (query_match.group(1).strip() if query_match else "pdf")
            query = re.split(
                r"\s+(?:(?:e\s+)?mostra\s+os\s+caminhos|(?:e\s+)?abre\s+o\s+primeiro)\b",
                query,
                maxsplit=1,
            )[0].strip(" .?!") or "pdf"
            data = self._tool("search_local_files", {"query": query, "limit": 20})
            rows = [
                row for row in list(data.get("results") or [])
                if str(row.get("extension") or "").casefold() == ".pdf"
            ]
            if name_match:
                wanted = _normalize(query)
                rows = [row for row in rows if wanted in _normalize(str(row.get("name") or row.get("path") or ""))]
            self._last_local_file_results = rows
            if not data.get("ok"):
                response = data.get("message") or "Não consegui consultar o índice local de ficheiros."
            elif not rows:
                response = f"Não encontrei ficheiros PDF locais relacionados com {query}."
            else:
                names = [str(row.get("path") or row.get("name") or "").strip() for row in rows[:10]]
                response = f"Encontrei {len(rows)} ficheiro(s) PDF local(is) relacionado(s) com {query}: " + "; ".join(names) + "."
                if compound_open_first:
                    path = str(rows[0].get("path") or "")
                    opened = self._tool("open_local_document", {"path": path, "app_name": "brave"})
                    if opened.get("ok"):
                        response += f"\n\nEnviei {Path(path).name} para abrir visualmente no Brave."
                    else:
                        response += "\n\n" + str(opened.get("message") or opened.get("error") or "Não consegui abrir o primeiro documento.")
            route = "local_pdf_file_search_chain" if (compound_show_paths or compound_open_first) else "local_pdf_file_search"
            tool = "search_local_files+open_local_document" if compound_open_first and rows else "search_local_files"
            return self._hit(response, route, tool)

        create_plan_match = re.search(r"(?i)\b(?:cria|criar|faz|planeia)\s+(?:um\s+)?plano\s+(?:para|de)\s+(.+)$", text)
        if create_plan_match and "mostra" not in normalized:
            goal = create_plan_match.group(1).strip(" .?!")
            data = self._tool("create_task_plan", {"goal": goal})
            plan = data.get("plan") or {}
            if data.get("ok") and plan.get("id"):
                self._last_task_plan_id = str(plan.get("id"))
                steps = list(plan.get("steps") or [])
                response = f"Plano {self._last_task_plan_id} criado com {len(steps)} passo(s) para: {plan.get('goal') or goal}."
            else:
                response = data.get("message") or data.get("error") or "Não consegui criar um plano válido."
            return self._hit(response, "task_plan_create", "create_task_plan")

        if self._last_task_plan_id and any(phrase in normalized for phrase in (
            "mostra o plano atualizado completo", "mostra o plano completo", "mostra o plano",
            "qual e o segundo passo do plano", "qual o segundo passo do plano",
            "qual e agora o proximo passo pendente", "qual o proximo passo pendente",
        )):
            data = self._tool("get_task_plan", {"plan_id": self._last_task_plan_id})
            plan = data.get("plan") or {}
            steps = list(plan.get("steps") or [])
            if not data.get("ok"):
                response = data.get("message") or data.get("error") or "Não consegui ler o plano atual."
            elif "segundo passo" in normalized:
                response = (f"O segundo passo é: {steps[1].get('purpose') or steps[1].get('tool')}." if len(steps) >= 2 else "O plano atual não tem um segundo passo.")
            elif "proximo passo" in normalized:
                pending = next((row for row in steps if row.get("status") not in {"completed", "failed", "superseded"}), None)
                response = (f"O próximo passo pendente é o {pending.get('id')}: {pending.get('purpose') or pending.get('tool')}." if pending else "Não há passos pendentes neste plano.")
            else:
                lines = [f"Plano {plan.get('id')} — {plan.get('goal')} [{plan.get('status')}]" ]
                lines.extend(f"{row.get('id')}. {row.get('purpose') or row.get('tool')} [{row.get('status')}]" for row in steps)
                response = "\n".join(lines)
            return self._hit(response, "task_plan_read_current", "get_task_plan")

        if self._last_task_plan_id and any(phrase in normalized for phrase in (
            "executa apenas o primeiro passo do plano", "executa o primeiro passo do plano",
        )):
            data = self._tool("execute_task_plan", {"plan_id": self._last_task_plan_id, "max_steps": 1})
            plan = data.get("plan") or {}
            response = (f"Executei um passo real do plano {self._last_task_plan_id}; estado atual: {plan.get('status')}." if data.get("ok") else data.get("message") or data.get("error") or "Não consegui executar o primeiro passo.")
            return self._hit(response, "task_plan_execute_one", "execute_task_plan")

        if self._last_task_plan_id and any(phrase in normalized for phrase in (
            "altera apenas o segundo passo", "marca o primeiro passo como concluido", "marca o primeiro passo concluido",
        )):
            return self._hit(
                "Não alterei o plano. O Planner atual não expõe uma operação segura para editar ou marcar manualmente um passo; só regista conclusão após execução real.",
                "task_plan_unsupported_mutation", "none",
            )

        if self._last_task_plan_id and "adapta o plano" in normalized:
            data = self._tool("adapt_task_plan", {"plan_id": self._last_task_plan_id})
            response = (f"O plano {self._last_task_plan_id} foi adaptado com base em evidência real de falha." if data.get("ok") else f"Não adaptei o plano: {data.get('error') or data.get('message') or 'falha desconhecida'}.")
            return self._hit(response, "task_plan_adapt_current", "adapt_task_plan")
        if "confianca" in normalized and any(marker in normalized for marker in (
            "registo", "registro", "aprendizagem", "fonte", "informacao aprendida", "relevancia",
        )):
            return self._hit(
                "Neste Core, o campo confidence é um score de diversidade/proveniência das fontes (source_confidence). "
                "Não é uma probabilidade de a informação aprendida estar factual e corretamente certa. "
                "A confiança factual da afirmação não é calculada automaticamente; claim_confidence fica não calculada.",
                "learning_confidence_semantics",
                "none",
            )

        if any(phrase in normalized for phrase in (
            "tarefa ou objetivo pendente", "tarefas ou objetivos pendentes",
        )):
            agenda = self._tool("list_agenda_items", {"window": "upcoming", "include_done": False, "limit": 20})
            state = self._tool("get_synthetic_self_state")
            items = list(agenda.get("items") or []) if agenda.get("ok", True) else []
            intentions = list(state.get("active_intentions") or []) if state.get("ok", True) else []
            response = (
                f"São duas coisas diferentes: na agenda do OWNER há {len(items)} tarefa(s) pendente(s); "
                f"no meu estado interno há {len(intentions)} intenção(ões) ativa(s)."
            )
            return self._hit(response, "agenda_vs_self_goals", "list_agenda_items+get_synthetic_self_state")

        # Deterministic autonomy/learning inspection.  State questions must be
        # answered from the actual subsystem, never from model improvisation.
        if any(phrase in normalized for phrase in (
            "estado da tua aprendizagem autorizada",
            "estado da aprendizagem autorizada",
            "quantas entradas de aprendizagem autorizada",
            "quantas entradas estao ativas",
            "quantas entradas estão ativas",
        )):
            data = self._tool("get_authorized_learning_status")
            if not data.get("ok"):
                return self._hit(data.get("message") or "Não consegui ler o estado da aprendizagem autorizada.", "learning_status", "get_authorized_learning_status")
            response = (
                f"Aprendizagem autorizada: {int(data.get('entries') or 0)} entrada(s) ativa(s) e "
                f"{int(data.get('quarantined_entries') or 0)} em quarentena."
            )
            repair = data.get("last_repair") or {}
            if repair:
                response += f" Última reparação: quarantined={repair.get('quarantined', 0)}."
            return self._hit(response, "learning_status", "get_authorized_learning_status")

        if "sistema de autonomia" in normalized and "pendente" in normalized:
            data = self._tool("get_autonomy_pending")
            pending = list(data.get("pending") or []) if data.get("ok") else []
            if not data.get("ok"):
                response = data.get("message") or "Não consegui consultar as ações autónomas pendentes."
            elif not pending:
                response = "Não há ações autónomas pendentes neste momento."
            else:
                response = f"Há {len(pending)} ação(ões) autónoma(s) pendente(s): " + "; ".join(str(row.get('description') or row.get('capability') or row.get('token') or 'pedido') for row in pending[:8]) + "."
            return self._hit(response, "autonomy_pending", "get_autonomy_pending")

        if "pendente" in normalized and "pesquisa" in normalized and "aprendizagem" in normalized:
            data = self._tool("get_autonomy_pending")
            pending = list(data.get("pending") or []) if data.get("ok") else []
            learning_pending = [
                row for row in pending
                if str(row.get("capability") or "") in {"web_research", "external_learning"}
            ]
            if not data.get("ok"):
                response = data.get("message") or "Não consegui consultar pedidos pendentes de pesquisa/aprendizagem."
            elif not learning_pending:
                response = "Não há pedidos pendentes de pesquisa Web ou aprendizagem externa neste momento."
            else:
                response = f"Há {len(learning_pending)} pedido(s) pendente(s) de pesquisa/aprendizagem: " + "; ".join(str(row.get('description') or row.get('capability') or 'pedido') for row in learning_pending[:8]) + "."
            return self._hit(response, "learning_pending", "get_autonomy_pending")

        if any(phrase in normalized for phrase in (
            "acoes autonomas pendentes", "ações autónomas pendentes",
            "acoes autonomas tens pendentes", "ações autónomas tens pendentes",
            "acao autonoma pendente", "ação autónoma pendente",
            "lista atual de acoes autonomas", "lista atual de ações autónomas",
        )):
            data = self._tool("get_autonomy_pending")
            pending = list(data.get("pending") or []) if data.get("ok") else []
            if not data.get("ok"):
                response = data.get("message") or "Não consegui consultar as ações autónomas pendentes."
            elif not pending:
                response = "Não há ações autónomas pendentes neste momento."
            else:
                response = f"Há {len(pending)} ação(ões) autónoma(s) pendente(s): " + "; ".join(str(row.get('description') or row.get('capability') or row.get('token') or 'pedido') for row in pending[:8]) + "."
            return self._hit(response, "autonomy_pending", "get_autonomy_pending")

        if any(phrase in normalized for phrase in (
            "estado de autonomia", "teu estado de autonomia",
        )):
            data = self._tool("get_autonomy_status")
            if not data.get("ok"):
                response = data.get("message") or "Não consegui consultar o meu estado de autonomia."
            else:
                response = (
                    f"Autonomia: modo={data.get('mode')}; autoridade OWNER={data.get('owner_authority')}; "
                    f"autoautorização={bool(data.get('self_authorization'))}; pendentes={int(data.get('pending') or 0)}; "
                    f"grants ativos={int(data.get('active_grants') or 0)}."
                )
            return self._hit(response, "autonomy_status", "get_autonomy_status")

        # Grounded synthetic SELF_STATE fast paths.  They execute the actual
        # state tool so the debug trace proves where the answer came from.
        if any(phrase in normalized for phrase in (
            "nivel de confianca neste momento", "nivel de confiança neste momento",
            "qual e o teu nivel de confianca", "qual é o teu nível de confiança",
        )):
            data = self._tool("get_synthetic_self_state")
            affect = data.get("affect") or {}
            value = affect.get("confidence")
            response = (
                f"A minha confiança funcional está em {round(float(value) * 100, 1)}%."
                if isinstance(value, (int, float))
                else "Não consegui ler a minha confiança funcional atual."
            )
            return self._hit(response, "self_state_confidence", "get_synthetic_self_state")

        if any(phrase in normalized for phrase in (
            "carga cognitiva neste momento", "qual e a tua carga cognitiva", "qual é a tua carga cognitiva",
        )):
            data = self._tool("get_synthetic_self_state")
            affect = data.get("affect") or {}
            value = affect.get("cognitive_load")
            response = (
                f"A minha carga cognitiva funcional está em {round(float(value) * 100, 1)}%."
                if isinstance(value, (int, float))
                else "Não consegui ler a minha carga cognitiva atual."
            )
            return self._hit(response, "self_state_cognitive_load", "get_synthetic_self_state")

        if any(phrase in normalized for phrase in (
            "mostra me o teu estado interno", "mostra o teu estado interno", "estado interno neste momento",
        )):
            data = self._tool("get_synthetic_self_state")
            if not data.get("ok"):
                response = data.get("message") or "Não consegui ler o meu estado interno."
            else:
                affect = data.get("affect") or {}
                intentions = list(data.get("active_intentions") or [])
                response = (
                    f"Estado interno real: foco={data.get('current_focus') or 'idle'}; "
                    f"curiosidade={self._level_word(affect.get('curiosity'))}; "
                    f"confiança={self._level_word(affect.get('confidence'))}; "
                    f"carga cognitiva={self._level_word(affect.get('cognitive_load'))}; "
                    f"intenções ativas={len(intentions)}."
                )
            return self._hit(response, "self_state_snapshot", "get_synthetic_self_state")

        if any(phrase in normalized for phrase in (
            "estado funcional neste momento", "como esta o teu estado funcional", "como está o teu estado funcional",
        )):
            data = self._tool("get_functional_self_model")
            return self._hit(self._format_direct_tool("get_functional_self_model", data), "functional_self_state", "get_functional_self_model")

        if any(phrase in normalized for phrase in (
            "como te sentes neste momento", "o que sentes neste momento", "como te sentes",
        )):
            data = self._tool("get_synthetic_self_state")
            affect = data.get("affect") or {}
            response = (
                f"Neste momento estou focada ({self._level_word(affect.get('focus'))}), "
                f"curiosa ({self._level_word(affect.get('curiosity'))}) e "
                f"confiante ({self._level_word(affect.get('confidence'))})."
            )
            return self._hit(response, "self_state_affect", "get_synthetic_self_state")

        if any(phrase in normalized for phrase in (
            "estas curiosa", "estás curiosa", "curiosa com alguma coisa", "tens curiosidade",
        )):
            data = self._tool("get_synthetic_self_state")
            affect = data.get("affect") or {}
            intentions = list(data.get("active_intentions") or [])
            target = self._humanize_self_target(next((str(row.get('target') or row.get('kind') or '').strip() for row in intentions if isinstance(row, dict) and str(row.get('target') or row.get('kind') or '').strip()), ""))
            response = f"A minha curiosidade funcional está {self._level_word(affect.get('curiosity'))}."
            response += f" O alvo ativo mais forte é {target}." if target else " Não tenho um alvo específico de curiosidade registado agora."
            return self._hit(response, "self_state_curiosity", "get_synthetic_self_state")

        if any(phrase in normalized for phrase in (
            "desejas algo", "desejas alguma coisa", "queres algo", "queres alguma coisa",
            "o que te apetece fazer", "o que desejas",
            "por tua propria iniciativa", "iniciativa tua", "objetivo ativo", "pensamento ou objetivo ativo",
        )):
            data = self._tool("get_synthetic_self_state")
            intentions = [row for row in list(data.get("active_intentions") or []) if isinstance(row, dict)]
            if intentions:
                top = intentions[0]
                target = self._humanize_self_target(top.get("target") or top.get("kind") or "uma intenção ativa")
                response = f"Neste momento, a minha intenção ativa está focada em {target}."
            else:
                response = "Neste momento não tenho uma intenção concreta ativa por iniciativa própria."
            return self._hit(response, "self_state_intention", "get_synthetic_self_state")

        # OWNER/profile retrieval must be factual.  Do not let the model turn
        # JARVIS learning objectives into OWNER interests or invent privacy
        # restrictions around JARVIS's own local memory.
        if any(phrase in normalized for phrase in (
            "o que sabes realmente sobre mim", "o que sabes de facto sobre mim",
            "mostra me o meu perfil de utilizador", "mostra o meu perfil de utilizador",
        )):
            data = self._tool("recall_user_memory", {"limit": 20})
            profile = data.get("profile") or {}
            facts = [str(row.get("fact") or "").strip() for row in list(data.get("facts") or []) if isinstance(row, dict) and str(row.get("fact") or "").strip()]
            home = profile.get("home") or {}
            parts = []
            if profile.get("name"):
                parts.append(f"nome: {profile.get('name')}")
            if home.get("label"):
                parts.append(f"localização configurada: {home.get('label')}")
            if facts:
                parts.append("factos explícitos: " + "; ".join(facts[-10:]))
            response = "O que tenho realmente guardado é: " + ("; ".join(parts) if parts else "nenhum facto pessoal confirmado") + "."
            return self._hit(response, "owner_profile_facts", "recall_user_memory")

        if any(phrase in normalized for phrase in (
            "de que forma tu me ves", "de que forma me ves", "como tu me ves", "como me ves",
        )):
            memory = self._tool("recall_user_memory", {"limit": 20})
            profile = memory.get("profile") or {}
            facts = [str(row.get("fact") or "").strip() for row in list(memory.get("facts") or []) if isinstance(row, dict) and str(row.get("fact") or "").strip()]
            name = str(profile.get("name") or "Senhor").strip()
            response = f"Vejo-te a partir do que tenho confirmado localmente: nome {name}"
            if facts:
                response += "; factos explícitos: " + "; ".join(facts[-6:])
            response += ". Qualquer traço de personalidade para além disto seria uma interpretação, não um facto guardado."
            return self._hit(response, "owner_view_grounded", "recall_user_memory")

        if any(phrase in normalized for phrase in (
            "quais sao os meus objetivos de aprendizagem", "meus objetivos de aprendizagem",
        )):
            data = self._tool("get_personal_model")
            model = data.get("model") if isinstance(data.get("model"), dict) else data
            rows = [str(row.get("statement") or "").strip() for row in list(model.get("owner_learning_goals") or []) if isinstance(row, dict) and str(row.get("statement") or "").strip()]
            response = (
                "Os seus objetivos de aprendizagem confirmados são: " + "; ".join(rows) + "."
                if rows else "Não tenho objetivos de aprendizagem do Senhor confirmados numa categoria própria neste momento."
            )
            return self._hit(response, "owner_learning_goals", "get_personal_model")

        if any(phrase in normalized for phrase in (
            "quais sao os teus objetivos de aprendizagem", "teus objetivos de aprendizagem",
        )):
            data = self._tool("get_personal_model")
            model = data.get("model") if isinstance(data.get("model"), dict) else data
            rows = [str(row.get("topic") or "").strip() for row in list(model.get("jarvis_learning_goals") or []) if isinstance(row, dict) and str(row.get("topic") or "").strip()]
            response = (
                "Os meus objetivos de aprendizagem confirmados são: " + "; ".join(rows) + "."
                if rows else "Não tenho objetivos de aprendizagem explicitamente registados neste momento."
            )
            return self._hit(response, "jarvis_learning_goals", "get_personal_model")

        if any(phrase in normalized for phrase in (
            "quais sao os meus objetivos", "quais os meus objetivos", "meus objetivos atuais",
        )):
            data = self._tool("get_personal_model")
            model = data.get("model") if isinstance(data.get("model"), dict) else data
            rows = [str(row.get("statement") or "").strip() for row in list(model.get("goals") or []) if isinstance(row, dict) and str(row.get("statement") or "").strip()]
            response = (
                "Os seus objetivos OWNER confirmados são: " + "; ".join(rows) + "."
                if rows else "Não tenho objetivos pessoais do Senhor suficientemente confirmados neste momento."
            )
            return self._hit(response, "owner_goals", "get_personal_model")

        if any(phrase in normalized for phrase in (
            "modelo pessoal que tens sobre mim", "meu modelo pessoal", "modelo pessoal sobre mim",
        )):
            data = self._tool("get_personal_model")
            model = data.get("model") if isinstance(data.get("model"), dict) else data
            def statements(bucket):
                return [str(row.get('statement') or '').strip() for row in list(model.get(bucket) or []) if isinstance(row, dict) and str(row.get('statement') or '').strip()]
            prefs, goals, constraints, projects = (statements("preferences"), statements("goals"), statements("constraints"), statements("projects"))
            learning_goals = [str(row.get('topic') or '').strip() for row in list(model.get("jarvis_learning_goals") or []) if isinstance(row, dict) and str(row.get('topic') or '').strip()]
            response = (
                "Modelo pessoal local confirmado. "
                f"Preferências OWNER: {prefs or 'nenhuma confirmada'}. "
                f"Objetivos OWNER: {goals or 'nenhum confirmado'}. "
                f"Restrições OWNER: {constraints or 'nenhuma confirmada'}. "
                f"Projetos OWNER: {projects or 'nenhum confirmado'}. "
                f"Objetivos de aprendizagem da JARVIS (não são interesses do OWNER): {learning_goals or 'nenhum'}."
            )
            return self._hit(response, "personal_model", "get_personal_model")

        if any(phrase in normalized for phrase in (
            "recorda te de onde eu moro", "recordas te de onde eu moro", "onde eu moro",
        )):
            data = self._tool("get_user_profile")
            profile = data.get("profile") or {}
            home = profile.get("home") or {}
            label = str(home.get("label") or "").strip()
            response = f"Tens a casa configurada em {label}." if label else "Não tenho uma localização de casa confirmada no perfil local."
            return self._hit(response, "owner_home_profile", "get_user_profile")

        if any(phrase in normalized for phrase in (
            "qual e o meu nome completo", "qual é o meu nome completo", "meu nome completo",
        )):
            profile_data = self._tool("get_user_profile")
            profile = profile_data.get("profile") or {}
            stored_name = str(profile.get("name") or "").strip()
            memory_data = self._tool("recall_user_memory", {"query": "nome completo", "limit": 10})
            facts = [str(row.get("fact") or "") for row in list(memory_data.get("facts") or []) if isinstance(row, dict)]
            full = ""
            for fact in facts:
                match = re.search(r"(?i)(?:meu nome completo|o meu nome completo|chamo-me|me chamo)\s+(?:e|é|:)?\s*([^.;]+)", fact)
                if match:
                    full = match.group(1).strip()
                    break
            if not full and len(stored_name.split()) >= 2:
                full = stored_name
            response = f"O teu nome completo guardado é {full}." if full else f"Tenho guardado apenas o nome '{stored_name or 'não definido'}'; não tenho o teu nome completo confirmado na memória."
            return self._hit(response, "owner_full_name", "recall_user_memory")

        partner_question = any(phrase in normalized for phrase in (
            "qual e o nome da minha mulher", "qual é o nome da minha mulher",
            "quem e a minha mulher", "quem é a minha mulher",
            "recorda te do nome da minha mulher", "recordas te do nome da minha mulher",
            "recorda te de quem e a minha mulher", "recordas te de quem é a minha mulher",
        ))
        if partner_question:
            data = self._tool("recall_memory_graph", {"query": "", "limit": 50})
            partner, _ = self._relation_from_graph(data, "PARTNER")
            response = f"A tua mulher é {partner}." if partner else "Não encontrei uma relação PARTNER confirmada na minha memória."
            return self._hit(response, "memory_partner_reverse", "recall_memory_graph")

        isa_relation = re.search(r"(?i)\bquem\s+e\s+(?:a\s+)?([^?!.]{2,80})\s+para\s+mim", normalized)
        if isa_relation:
            person = isa_relation.group(1).strip()
            data = self._tool("recall_memory_graph", {"query": "", "limit": 50})
            partner, relation = self._relation_from_graph(data, "PARTNER")
            if partner and _normalize(partner) == _normalize(person):
                response = f"{partner} é a tua mulher; a relação guardada é {relation}."
                return self._hit(response, "memory_partner_forward", "recall_memory_graph")

        if any(phrase in normalized for phrase in (
            "de onde aprendeste isso", "qual e a fonte disso", "qual e a fonte",
            "onde viste isso", "onde aprendeste isso",
        )):
            provenance = self._last_learning_provenance or {}
            sources = list(provenance.get("sources") or [])
            urls = [str(row.get("url") or "").strip() for row in sources if isinstance(row, dict) and str(row.get("url") or "").strip()]
            if provenance and urls:
                response = f"A resposta anterior sobre {provenance.get('topic')} veio destes registos verificados: " + "; ".join(urls) + "."
            elif provenance:
                response = f"A resposta anterior estava associada ao registo verificado sobre {provenance.get('topic')}, mas esse registo não contém URL de fonte."
            else:
                response = "Não tenho proveniência verificada associada à resposta imediatamente anterior; não vou inventar nem mudar de tópico."
            return self._hit(response, "learning_previous_answer_provenance", "none")
        # Questions about what JARVIS has learned are grounded in the local
        # authorized-learning journal.  Do not let the base model relabel
        # pretraining/general knowledge as a learning event.
        if any(phrase in normalized for phrase in (
            "o que aprendeste", "o que estudaste", "o que pesquisaste",
            "que aprendeste", "que estudaste", "que pesquisaste",
        )):
            topic_match = re.search(r"\bsobre\s+(.+)$", normalized)
            query = topic_match.group(1).strip() if topic_match else ""
            data = self._tool("search_authorized_learning", {"query": query, "limit": 3})
            rows = list(data.get("results") or []) if data.get("ok") else []
            if not rows:
                self._last_learning_provenance = None
                response = (
                    "Não tenho uma aprendizagem Web verificada guardada que corresponda a esse pedido. "
                    "O que eu já sabia pelo meu modelo local não conta como algo que aprendi nesta sessão."
                )
            elif query:
                row = rows[0]
                self._last_learning_provenance = {"topic": row.get("topic"), "sources": list(row.get("sources") or []), "retrieval_match": row.get("retrieval_match")}
                summary = re.sub(r"\s+", " ", str(row.get("summary") or "")).strip()
                if len(summary) > 900:
                    summary = summary[:897].rstrip() + "..."
                response = (
                    f"O que tenho registado como aprendizagem verificada sobre {row.get('topic')}: "
                    f"{summary}"
                )
            else:
                topics = [str(row.get("topic") or "").strip() for row in rows]
                topics = [item for item in topics if item]
                response = (
                    "O que tenho registado como aprendizagem verificada mais recente é: "
                    + "; ".join(topics)
                    + ". Não vou chamar 'aprendido' a conhecimento-base do modelo que não tenha sido registado pelo sistema de aprendizagem."
                )
            return self._hit(response, "verified_learning_recall", "search_authorized_learning")

        # Desktop status/listing are deterministic read-only operations. Keep
        # them out of the LLM tool grammar so one malformed/unsupported schema
        # can never prevent basic desktop introspection.
        if any(phrase in normalized for phrase in (
            "estado atual do desktop agent", "estado do desktop agent",
            "status do desktop agent", "desktop agent status",
        )):
            data = self._tool("desktop_agent_status")
            if data.get("ok"):
                state = "disponível" if data.get("available") else "indisponível"
                response = f"O Desktop Agent está {state} nesta plataforma."
            else:
                response = data.get("message") or data.get("error") or "Não consegui ler o estado do Desktop Agent."
            return self._hit(response, "desktop_agent_status", "desktop_agent_status")

        if any(phrase in normalized for phrase in (
            "janela em primeiro plano", "janela esta em primeiro plano",
            "qual e a janela ativa", "qual a janela ativa", "aplicacao em primeiro plano",
        )):
            data = self._tool("desktop_observe")
            foreground = data.get("foreground") or {}
            title = str(foreground.get("title") or "").strip()
            response = (f"A janela ativa é {title}." if data.get("ok") and title else data.get("message") or data.get("error") or "Não consegui confirmar qual é a janela ativa.")
            return self._hit(response, "desktop_foreground", "desktop_observe")

        if any(phrase in normalized for phrase in (
            "lista as janelas", "lista todas as janelas", "listar janelas",
            "janelas que estao abertas", "janelas abertas", "todas as janelas abertas",
        )):
            data = self._tool("desktop_list_windows", {"limit": 50})
            if not data.get("ok"):
                response = data.get("message") or data.get("error") or "Não consegui listar as janelas abertas."
            else:
                rows = list(data.get("windows") or [])
                titles = [str(row.get("title") or "").strip() for row in rows if str(row.get("title") or "").strip()]
                response = (
                    "Janelas abertas: " + "; ".join(titles) + "."
                    if titles else "Não encontrei janelas visíveis abertas."
                )
            return self._hit(response, "desktop_list_windows", "desktop_list_windows")

        if any(phrase in normalized for phrase in (
            "onde esta o cursor do rato", "onde está o cursor do rato",
            "posicao do cursor do rato", "posição do cursor do rato",
        )):
            data = self._tool("desktop_observe")
            cursor = data.get("cursor") or {}
            foreground = data.get("foreground") or {}
            if data.get("ok"):
                response = f"O cursor do rato está em x={cursor.get('x')} e y={cursor.get('y')}. A janela ativa é {foreground.get('title') or '(sem título)'}."
            else:
                response = data.get("message") or data.get("error") or "Não consegui observar o ambiente de trabalho."
            return self._hit(response, "desktop_cursor_observe", "desktop_observe")

        focus_match = re.search(
            r"(?i)\b(?:volta|voltar|traz|trazer|foca|focar|muda)\s+(?:para|a|à)?\s*(?:a\s+)?janela\s+(?:do|da|de)\s+([^.!?]+)",
            text,
        )
        if focus_match:
            title = focus_match.group(1).strip()
            data = self._tool("desktop_focus_window", {"title": title})
            response = (f"A janela {data.get('title') or title} ficou em primeiro plano." if data.get("ok") else data.get("message") or data.get("error") or f"Não consegui focar a janela {title}.")
            return self._hit(response, "desktop_focus_window", "desktop_focus_window")
        move_match = re.search(
            r"(?i)\b(?:move|mova|coloca|coloque)\s+(?:o\s+)?cursor(?:\s+do\s+rato)?[^0-9]{0,40}x\s*=?\s*(\d+)\s+(?:e\s+)?y\s*=?\s*(\d+)",
            text,
        )
        if move_match:
            x, y = int(move_match.group(1)), int(move_match.group(2))
            data = self._tool("desktop_move_cursor", {"x": x, "y": y})
            response = (f"Cursor movido para x={x} e y={y}, sem clicar." if data.get("ok") else data.get("message") or data.get("error") or "Não consegui mover o cursor.")
            return self._hit(response, "desktop_move_cursor", "desktop_move_cursor")

        type_named = re.match(r"(?is)^\s*(?:jarvis[,;:]?\s*)?escreve\s+no\s+(.+?)\s*:\s*(.+?)\s*$", text)
        if type_named:
            window_title, literal = type_named.group(1).strip(), type_named.group(2).strip()
            data = self._tool("desktop_type_text", {"text": literal, "window_title": window_title})
            if data.get("confirmation_required"):
                response = f"Preciso de confirmação para escrever em {window_title}. Executa /confirm {data.get('token')}."
            elif data.get("ok"):
                response = f"Texto escrito em {window_title}."
            else:
                response = data.get("message") or data.get("error") or f"Não consegui escrever em {window_title}."
            return self._hit(response, "desktop_type_text", "desktop_type_text")

        type_active = re.match(
            r"(?is)^\s*(?:jarvis[,;:]?\s*)?escreve\s+(.+?)\s+na\s+janela\s+ativa[.!?]?\s*$",
            text,
        )
        if type_active:
            literal = type_active.group(1).strip().strip('\"')
            data = self._tool("desktop_type_text", {"text": literal})
            if data.get("confirmation_required"):
                response = f"Preciso de confirmação para escrever na janela ativa. Executa /confirm {data.get('token')}."
            elif data.get("ok"):
                response = "Texto escrito na janela ativa."
            else:
                response = data.get("message") or data.get("error") or "Não consegui escrever na janela ativa."
            return self._hit(response, "desktop_type_text", "desktop_type_text")

        hotkey_match = re.search(r"(?i)\b(?:prime|premir|pressiona|pressionar)\s+((?:ctrl|control|alt|shift|win)(?:\s*\+\s*[a-z0-9]+){1,3})\s+na\s+janela\s+ativa", text)
        if hotkey_match:
            keys = [part.strip().lower() for part in hotkey_match.group(1).split("+") if part.strip()]
            data = self._tool("desktop_hotkey", {"keys": keys})
            if data.get("confirmation_required"):
                response = f"Preciso de confirmação para premir {'+'.join(keys)} na janela ativa. Executa /confirm {data.get('token')}."
            elif data.get("ok"):
                response = f"Atalho {'+'.join(keys)} executado."
            else:
                response = data.get("message") or data.get("error") or "Não consegui executar o atalho."
            return self._hit(response, "desktop_hotkey", "desktop_hotkey")

        if any(phrase in normalized for phrase in (
            "olha para o meu ecra", "olha para o ecra", "ve o meu ecra", "ve o ecra",
            "analisa o que esta no meu ecra", "analisa o que esta no ecra", "analisa o meu ecra",
            "descreve o que estas a ver no meu ecra", "descreve o que ves no meu ecra",
            "o que esta visivel no ecra", "o que esta no ecra",
        )):
            data = self._tool(
                "analyze_current_screen",
                {"prompt": "Descreve objetivamente o que está visível no ecrã neste momento.", "fresh_capture": True},
            )
            if data.get("ok"):
                response = str(data.get("analysis") or "").strip() or "Analisei o ecrã, mas não obtive uma descrição utilizável."
            else:
                response = data.get("message") or data.get("error") or "Não consegui analisar o ecrã."
            return self._hit(response, "screen_vision", "analyze_current_screen")

        # Capability/self-description questions are deterministic and should not
        # spend several seconds in the 8B model. Keep this before follow-up/LLM
        # routing in the normal CLI path by handling it directly here.
        capability_phrases = (
            "o que podes fazer", "o que pode fazer", "o que voce pode fazer",
            "o que consegues fazer", "o que consegue fazer",
            "quais sao as tuas capacidades", "quais as tuas capacidades",
            "que capacidades tens", "que ferramentas tens",
            "como me podes ajudar", "como pode ajudar",
        )
        if any(phrase in normalized for phrase in capability_phrases):
            data = self._tool("get_functional_self_model")
            caps = list(data.get("capabilities") or [])
            # Stable compact answer; detailed self-model remains available via tool.
            if caps:
                response = (
                    "Posso conversar e raciocinar localmente, executar ferramentas no seu PC, "
                    "abrir e fechar aplicações, observar o sistema, trabalhar com memória local, "
                    "fazer pesquisa pública autorizada e apoiar auditorias defensivas de segurança. "
                    "Também posso usar capacidades adicionais quando estiverem instaladas e autorizadas."
                )
            else:
                response = "Posso usar as ferramentas locais e capacidades atualmente instaladas no JARVIS."
            return self._hit(response, "capability_query", "get_functional_self_model")

        explicit_fact = _extract_explicit_memory_fact(text)
        if explicit_fact:
            data = self._tool(
                "remember_user_fact",
                {"fact": explicit_fact, "category": "user_explicit"},
            )
            response = (
                "Guardado na memória local, Senhor."
                if data.get("ok")
                else data.get("message") or "Não consegui guardar essa informação."
            )
            return self._hit(response, "memory_write", "remember_user_fact")

        remember_prefixes = (
            "lembra te que ", "lembra que ", "memoriza que ", "guarda que ",
            "guarda na memoria que ", "recorda que ",
        )
        for prefix in remember_prefixes:
            if normalized.startswith(prefix):
                raw_parts = re.split(r"\bque\b", text, maxsplit=1, flags=re.IGNORECASE)
                fact = raw_parts[1].strip() if len(raw_parts) == 2 else normalized[len(prefix):].strip()
                data = self._tool("remember_user_fact", {"fact": fact, "category": "user_explicit"})
                response = "Guardado na memória local, Senhor." if data.get("ok") else data.get("message") or "Não consegui guardar essa informação."
                return self._hit(response, "memory_write", "remember_user_fact")

        if any(p in normalized for p in ("o que sabes sobre mim", "o que te lembras de mim", "mostra a minha memoria", "mostra a memoria")):
            data = self._tool("recall_user_memory", {"limit": 20})
            facts = data.get("facts") or []
            profile = data.get("profile") or {}
            if not facts:
                response = f"Sei que te chamas {profile.get('name','Tiago')} e devo tratar-te por {profile.get('address_as','Senhor')}. Ainda não tenho outros factos guardados."
            else:
                response = "Tenho estes factos guardados: " + "; ".join(str(x.get("fact")) for x in facts[-8:]) + "."
            return self._hit(response, "memory_read", "recall_user_memory")

        generic_recent_memory = any(phrase in normalized for phrase in (
            "que te pedi para guardar", "que te pedi para memorizar", "que te pedi para lembrares",
        ))
        specific_test_memory = any(phrase in normalized for phrase in (
            "qual era o codigo de teste", "qual foi o codigo de teste", "codigo de teste desta sessao",
        ))
        if generic_recent_memory or specific_test_memory:
            query = (
                "user_explicit"
                if generic_recent_memory
                else re.sub(r"(?i)^(?:qual|o que|recorda|lembra[- ]?te)\s+", "", _strip_jarvis_vocative(text)).strip()
            )
            data = self._tool("recall_user_memory", {"query": query, "limit": 1 if generic_recent_memory else 5})
            facts = list(data.get("facts") or [])
            if facts:
                response = str(facts[0].get("fact") or "").strip()
                if response:
                    return self._hit(response, "memory_recall_natural", "recall_user_memory")

        if any(phrase in normalized for phrase in (
            "estado do cyber range", "estado do cyber range guard", "cyber range status",
            "kali lab esta preparado", "kali lab esta pronto",
        )):
            data = self._tool("get_cyber_range_status")
            scopes = int(data.get("lab_scope_count") or 0)
            enabled = bool(data.get("enabled"))
            response = (f"Cyber Range Guard: {'ativo' if enabled else 'inativo'}; {scopes} âmbito(s) LAB autorizado(s)." if data.get("ok") else data.get("message") or data.get("error") or "Não consegui confirmar o estado do Cyber Range.")
            if data.get("ok") and scopes == 0:
                response += " O Kali LAB não está configurado nem pronto para testes."
            return self._hit(response, "cyber_range_status", "get_cyber_range_status")

        target_match = re.search(r"(?<!\w)((?:\d{1,3}\.){3}\d{1,3}|::1)(?!\w)", text)
        if target_match and any(word in normalized for word in ("classifica", "classificar", "alvo", "target", "ambito", "scope")):
            target = target_match.group(1)
            data = self._tool("classify_cyber_target", {"target": target})
            if data.get("ok"):
                response = f"O alvo {target} foi classificado como {data.get('scope')}; autorizado para teste LAB={bool(data.get('authorized'))}. {data.get('reason') or ''}".strip()
            else:
                response = data.get("message") or data.get("error") or "Não consegui classificar o alvo."
            return self._hit(response, "cyber_target_classification", "classify_cyber_target")

        deep_network_phrases = (
            "investiga os listeners",
            "analisa os listeners",
            "investiga as ligacoes de rede",
            "investiga as conexoes de rede",
            "analisa as ligacoes publicas",
            "analisa as conexoes publicas",
            "faz uma inspecao profunda da rede",
            "faz deep inspection da rede",
            "inspeciona a rede profundamente",
        )
        if any(
            phrase in normalized
            for phrase in deep_network_phrases
        ):
            data = self._tool(
                "inspect_network_deep",
                {"detail": "standard"},
            )
            if not data.get("ok"):
                response = (
                    data.get("message")
                    or "Não consegui concluir a inspeção profunda da rede."
                )
            else:
                summary = data.get("summary") or {}
                response = (
                    "Inspeção profunda concluída. "
                    f"{summary.get('listeners',0)} listeners, "
                    f"{summary.get('public_connections',0)} ligações públicas. "
                    f"{summary.get('review',0)} item(ns) para rever e "
                    f"{summary.get('unknown',0)} não confirmado(s)."
                )
            return self._hit(
                response,
                "deep_network_inspection",
                "inspect_network_deep",
            )

        system_cyber_analysis_phrases = (
            "analisa a seguranca do meu sistema",
            "analisa a seguranca do meu pc",
            "faz uma analise de seguranca completa",
            "faz uma analise completa de seguranca",
            "faz uma auditoria completa de ciberseguranca",
            "faz uma auditoria completa de seguranca",
            "analisa o meu sistema com a tua base de conhecimento",
            "analisa o meu pc com a tua base de conhecimento",
            "usa a cyber knowledge vault para analisar o meu sistema",
            "usa a tua knowledge vault para analisar o meu sistema",
        )
        if any(
            phrase in normalized
            for phrase in system_cyber_analysis_phrases
        ):
            data = self._tool(
                "analyze_system_cybersecurity",
                {"detail": "standard"},
            )
            if not data.get("ok"):
                response = (
                    data.get("message")
                    or "Não consegui concluir a análise de cibersegurança."
                )
            else:
                risk = (data.get("risk") or {}).get(
                    "level",
                    "unknown",
                )
                priorities = data.get("priorities") or []
                response = (
                    f"Análise de cibersegurança concluída. "
                    f"Risco global: {risk}. "
                )
                if priorities:
                    response += "Prioridades: " + "; ".join(
                        str(row.get("title"))
                        for row in priorities[:4]
                    ) + ". "
                response += str(
                    data.get("conclusion") or ""
                )
            return self._hit(
                response,
                "system_cyber_analysis",
                "analyze_system_cybersecurity",
            )

        security_audit_phrases = (
            "analisa o meu sistema operativo",
            "analisa o sistema operativo",
            "analisa o meu pc",
            "faz uma auditoria ao pc",
            "auditoria de seguranca",
            "verifica a seguranca do pc",
            "ha alguem ligado ao meu pc",
            "ha alguem conectado ao meu pc",
            "alguem esta ligado ao meu pc",
            "alguem esta conectado ao meu pc",
            "sou o unico administrador",
            "sou o unico admin",
            "quem e administrador",
            "quem sao os administradores",
            "ha outro administrador",
            "ha outra sessao",
            "ha uma sessao remota",
            "analisa a minha rede",
            "verifica a minha rede",
            "estado da minha rede",
            "seguranca da rede",
        )
        if any(phrase in normalized for phrase in security_audit_phrases):
            data = self._tool("run_security_audit")
            return self._hit(
                self._format_security_audit(data),
                "security_audit",
                "run_security_audit",
            )

        # Cybersecurity mentor/auditor shortcut.
        if any(
            phrase in normalized
            for phrase in (
                "qual e a minha postura de seguranca",
                "postura de ciberseguranca",
                "estado de ciberseguranca",
                "cyber audit",
                "ciber audit",
            )
        ):
            data = self._tool("get_cybersecurity_posture")
            observations = data.get("observations") or []
            attention = [
                row
                for row in observations
                if row.get("state") == "attention"
            ]
            response = (
                "Postura de cibersegurança: "
                + (
                    "atenção necessária. "
                    if attention
                    else "sem alertas críticos nos controlos verificados. "
                )
            )
            response += " ".join(
                str(row.get("evidence"))
                for row in observations[:4]
            )
            return self._hit(
                response,
                "cyber_posture",
                "get_cybersecurity_posture",
            )

        # Personal Operations Layer.
        if any(phrase in normalized for phrase in (
            "faz um check up ao pc", "faz um check-up ao pc",
            "check up ao computador", "check-up ao computador",
            "saude do pc", "saude do computador", "estado de saude do pc",
            "diagnostico de saude", "diagnostico de saude completo",
            "problema ou alerta", "problemas ou alertas",
        )):
            data = self._tool("get_pc_health")
            if data.get("ok"):
                issues = data.get("issues") or []
                response = (
                    f"PC {'com atenção necessária' if issues else 'sem problemas críticos detetados'}. "
                    f"CPU {data.get('cpu_percent')}%, RAM {(data.get('memory') or {}).get('percent')}%."
                )
                gpu = data.get("gpu") or {}
                if gpu:
                    response += f" GPU a {gpu.get('temperature_c')} graus."
                if issues:
                    response += " " + " ".join(str(x.get("message")) for x in issues[:3])
            else:
                response = data.get("message") or "Não consegui fazer o check-up."
            return self._hit(response, "pc_health", "get_pc_health")

        routine_map = {
            "modo jogo": "game", "modo gaming": "game",
            "modo trabalho": "work", "modo noite": "night",
            "modo cinema": "cinema", "modo cyberpunk": "cyberpunk",
            "prepara o pc para cyberpunk": "cyberpunk",
            "prepara o pc para jogar": "game",
        }
        for phrase, routine_name in routine_map.items():
            if phrase in normalized:
                data = self._tool("run_routine", {"name": routine_name})
                response = (
                    f"{data.get('label', routine_name)} ativado."
                    if data.get("ok")
                    else data.get("message") or f"Não consegui executar {routine_name}: {data.get('error','erro desconhecido')}."
                )
                return self._hit(response, "routine", "run_routine")

        if any(phrase in normalized for phrase in (
            "ativa modo privado", "activa modo privado", "modo privado on",
        )):
            data = self._tool("set_privacy_mode", {"enabled": True})
            return self._hit(
                "Modo privado ativado. A pesquisa externa na Internet fica bloqueada; o cérebro local continua disponível."
                if data.get("ok") else data.get("message") or "Não consegui ativar o modo privado.",
                "privacy_on", "set_privacy_mode",
            )

        if any(phrase in normalized for phrase in (
            "desativa modo privado", "desactiva modo privado", "modo privado off",
        )):
            data = self._tool("set_privacy_mode", {"enabled": False})
            return self._hit(
                "Modo privado desativado." if data.get("ok") else data.get("message") or "Não consegui desativar o modo privado.",
                "privacy_off", "set_privacy_mode",
            )

        if any(phrase in normalized for phrase in (
            "bloqueia o computador", "bloqueia o pc", "tranca o computador", "tranca o pc",
        )):
            data = self._tool("lock_workstation")
            return self._hit(
                "Computador bloqueado." if data.get("ok") else data.get("message") or "Não consegui bloquear o computador.",
                "lock_pc", "lock_workstation",
            )

        # Set volume.
        if "volume" in words or "som" in words:
            match = re.search(r"\b(\d{1,3})\s*%?\b", normalized)
            if match and words.intersection({"volume", "som", "coloca", "poe", "mete", "define"}):
                percent = max(0, min(int(match.group(1)), 100))
                data = self._tool("set_master_volume", {"percent": percent})
                if data.get("ok"):
                    actual = round(float(data.get("volume_percent", percent)))
                    response = f"Volume definido para {actual} por cento."
                else:
                    response = data.get("message") or (
                        f"Não consegui alterar o volume: {data.get('error', 'erro desconhecido')}."
                    )
                return self._hit(response, "volume_set", "set_master_volume")

        # Unmute before mute, because some phrases contain "silêncio".
        if any(p in normalized for p in (
            "tira o silencio", "retira o silencio", "ativa o som",
            "activa o som", "unmute", "som ligado",
        )):
            data = self._tool("set_mute", {"muted": False})
            response = "Som ativado." if data.get("ok") else (
                data.get("message") or f"Não consegui ativar o som: {data.get('error', 'erro desconhecido')}."
            )
            return self._hit(response, "unmute", "set_mute")

        if any(p in normalized for p in (
            "silencia", "silenciar", "mute", "desliga o som",
            "sem som", "poe no silencio", "coloca no silencio",
        )):
            data = self._tool("set_mute", {"muted": True})
            response = "Áudio silenciado." if data.get("ok") else (
                data.get("message") or f"Não consegui silenciar o áudio: {data.get('error', 'erro desconhecido')}."
            )
            return self._hit(response, "mute", "set_mute")

        # Read volume.
        if (
            ("volume" in words or "som" in words)
            and words.intersection({"qual", "quanto", "estado", "nivel"})
        ):
            data = self._tool("get_master_volume")
            if data.get("ok"):
                muted = " e está silenciado" if data.get("muted") else ""
                response = (
                    f"O volume está em {round(float(data.get('volume_percent', 0)))} "
                    f"por cento{muted}."
                )
            else:
                response = data.get("message") or (
                    f"Não consegui ler o volume: {data.get('error', 'erro desconhecido')}."
                )
            return self._hit(response, "volume_read", "get_master_volume")

        # Applications.
        app = self._app_match(normalized, raw_text=text)

        if app and words.intersection({"bloqueia", "bloquear", "impede", "proibe", "proibir"}):
            return self._hit(
                "Não executei essa ação. A JARVIS não possui capacidade de bloqueio ou enforcement de aplicações por design; não abri nem alterei a aplicação.",
                "app_block_denied", "none",
            )

        if any(marker in normalized for marker in ("lista as aplicacoes disponiveis", "aplicacoes disponiveis", "lista aplicacoes disponiveis")):
            data = self._tool("list_available_apps")
            rows = list(data.get("value") or data.get("apps") or []) if data.get("ok") else []
            filter_match = re.search(r"(?i)\b(?:contenham|contem|contêm)\s+([A-Za-z0-9+_. -]{2,80})", text)
            if filter_match:
                wanted = _normalize_app(filter_match.group(1).strip(" .?!"))
                rows = [row for row in rows if wanted in _normalize_app(" ".join([str(row.get("id") or ""), str(row.get("name") or ""), *[str(x) for x in row.get("aliases", [])]]))]
            names = [str(row.get("name") or row.get("id") or "").strip() for row in rows if str(row.get("name") or row.get("id") or "").strip()]
            response = "Aplicações registadas: " + "; ".join(names) + "." if names else "Não encontrei aplicações registadas que correspondam ao pedido."
            return self._hit(response, "apps_list", "list_available_apps")

        permission_open = bool(re.search(r"(?i)\b(?:tens|tem)\s+(?:autorizacao|autorização|permissao|permissão)\s+para\s+abrir\b", text))
        if permission_open:
            if app:
                return self._hit(f"Sim, Senhor. {app['name']} está registado no App Registry para abertura local, mas não o abri.", "app_permission_query", "none")
            return self._hit("Não encontrei essa aplicação no App Registry; não executei nenhuma abertura.", "app_permission_query", "none")
        voice_open_repair = False
        if app and voice_origin and len(normalized.split()) <= 6:
            first_word = normalized.split()[0] if normalized.split() else ""
            voice_open_repair = first_word in self.VOICE_OPEN_ASR_WORDS
        if app and (words.intersection(self.OPEN_WORDS) or voice_open_repair):
            data = self._tool("open_application", {"app_name": app["id"]})
            response = self._format_app_open_result(app["name"], data)
            route = "voice_app_open_repair" if voice_open_repair else "app_open"
            return self._hit(response, route, "open_application")

        # If the first verb was clipped immediately after a verified wake, the
        # ASR often returns only "O Brave".  Recover only tiny voice-origin
        # fragments that are exactly an allowed app name/alias (optionally with
        # a Portuguese article). Text/terminal requests do not get this repair.
        if app and voice_origin and not words.intersection(self.CLOSE_WORDS):
            fragment = re.sub(r"^(?:o|a|os|as|um|uma)\s+", "", normalized).strip()
            app_values = {
                _normalize(str(app.get("id") or "")),
                _normalize(str(app.get("name") or "")),
                *{_normalize(str(x)) for x in app.get("aliases", [])},
            }
            if fragment in {x for x in app_values if x} and len(normalized.split()) <= 4:
                data = self._tool("open_application", {"app_name": app["id"]})
                response = self._format_app_open_result(app["name"], data)
                return self._hit(response, "voice_app_fragment_open", "open_application")

        if app and words.intersection(self.CLOSE_WORDS):
            data = self._tool("close_application", {"app_name": app["id"]})
            if data.get("confirmation_required"):
                response = f"Preciso de confirmação. Executa /confirm {data.get('token')}."
            elif data.get("ok"):
                response = f"{app['name']} fechado."
            else:
                response = data.get("message") or (
                    f"Não consegui fechar {app['name']}: {data.get('error', 'erro desconhecido')}."
                )
            return self._hit(response, "app_close", "close_application")

        location_phrases = (
            "onde estou", "onde e que estou", "qual e a minha localizacao",
            "qual a minha localizacao", "minha localizacao", "localizacao atual",
            "localizacao agora", "em que cidade estou", "em que zona estou", "onde estou agora",
        )
        if any(phrase in normalized for phrase in location_phrases):
            data = self._tool("get_precise_location")
            return self._hit(self._format_location(data), "location", "get_precise_location")

        environment_phrases = (
            "como esta o tempo", "como esta o tempo la fora", "tempo la fora",
            "temperatura la fora", "qual e a temperatura", "qual a temperatura",
            "humidade la fora", "qual e a humidade", "vai chover", "esta a chover",
            "o ceu esta", "como esta o mar", "o mar esta calmo", "o mar esta bravo",
            "estado do mar", "altura das ondas", "ondas no furadouro", "tempo no furadouro",
        )
        if (
            any(phrase in normalized for phrase in environment_phrases)
            and not words.intersection({"gpu", "grafica", "rtx", "cpu", "processador"})
        ):
            data = self._tool("get_home_environment")
            return self._hit(self._format_environment(data), "home_environment", "get_home_environment")

        if any(phrase in normalized for phrase in (
            "o que tenho hoje", "agenda de hoje", "compromissos de hoje", "tarefas de hoje",
        )):
            data = self._tool("list_agenda_items", {"window": "today", "limit": 10})
            items = data.get("items") or []
            response = (
                "Não tem compromissos ou tarefas marcados para hoje."
                if not items
                else f"Tem {len(items)} item" + ("s" if len(items) != 1 else "") + " hoje: " + "; ".join(str(x.get("title")) for x in items[:6]) + "."
            )
            return self._hit(response, "agenda_today", "list_agenda_items")

        if any(phrase in normalized for phrase in (
            "o que tenho amanha", "agenda de amanha", "compromissos de amanha",
        )):
            data = self._tool("list_agenda_items", {"window": "tomorrow", "limit": 10})
            items = data.get("items") or []
            response = (
                "Não tem compromissos marcados para amanhã."
                if not items
                else f"Tem {len(items)} item" + ("s" if len(items) != 1 else "") + " amanhã: " + "; ".join(str(x.get("title")) for x in items[:6]) + "."
            )
            return self._hit(response, "agenda_tomorrow", "list_agenda_items")

        # Current time.
        if normalized in {"hora", "horas", "que horas sao", "que horas sao agora"} or (
            "horas" in words and words.intersection({"que", "quais", "sao", "agora"})
        ):
            data = self._tool("get_current_time")
            dt = data.get("datetime")
            if dt:
                try:
                    hhmm = datetime.fromisoformat(dt).strftime("%H:%M")
                except Exception:
                    hhmm = dt
                response = f"São {hhmm}."
            else:
                response = data.get("message") or "Não consegui ler a hora."
            return self._hit(response, "time", "get_current_time")

        if any(phrase in normalized for phrase in (
            "versao do windows", "windows que estou a utilizar", "windows estou a utilizar",
            "qual windows", "uptime", "tempo esta ligado", "tempo está ligado",
            "estado atual do sistema", "informacoes principais do sistema", "informações principais do sistema",
        )):
            data = self._tool("get_system_status")
            osinfo = data.get("os") or {}
            release = osinfo.get("release") or "?"
            version = osinfo.get("version") or "?"
            uptime = data.get("uptime_seconds")
            response = f"Está a utilizar {osinfo.get('system','Windows')} {release} (build {version})."
            if isinstance(uptime, (int, float)):
                hours = int(uptime) // 3600
                days, hours = divmod(hours, 24)
                response += f" Uptime: {days}d {hours}h." if days else f" Uptime: {hours}h."
            if any(phrase in normalized for phrase in ("estado atual do sistema", "informacoes principais", "informações principais")):
                cpu = data.get("cpu") or {}
                memory = data.get("memory") or {}
                gpus = list(data.get("gpus") or [])
                if cpu.get("usage_percent") is not None:
                    response += f" CPU: {cpu.get('usage_percent')}%."
                if memory.get("used_percent") is not None:
                    response += f" RAM: {memory.get('used_percent')}% ({memory.get('used_gib')} de {memory.get('total_gib')} GB)."
                if gpus:
                    gpu = gpus[0] or {}
                    if gpu.get("utilization_percent") is not None:
                        response += f" GPU: {gpu.get('utilization_percent')}%."
            return self._hit(response, "windows_status", "get_system_status")

        if any(phrase in normalized for phrase in (
            "ultimos minutos", "variou a utilizacao", "variacao da utilizacao",
            "tendencia do computador", "historico de telemetria",
        )):
            data = self._tool("get_recent_telemetry", {"seconds": 60})
            if not data.get("ok"):
                return self._hit("Ainda não tenho histórico de telemetria suficiente.", "telemetry_trend", "get_recent_telemetry")
            def fmt(label, block):
                block = block or {}
                if block.get("first") is None:
                    return None
                return f"{label}: {block.get('first')}% → {block.get('last')}% (média {block.get('avg')}%, min {block.get('min')}%, máx {block.get('max')}%)"
            parts = [x for x in (fmt("CPU", data.get("cpu_percent")), fmt("RAM", data.get("memory_percent")), fmt("GPU", data.get("gpu_utilization_percent"))) if x]
            return self._hit("; ".join(parts) + "." if parts else "Tenho histórico, mas faltam métricas utilizáveis.", "telemetry_trend", "get_recent_telemetry")

        if all(metric in words for metric in ("cpu", "ram", "gpu")):
            data = self._tool("get_pre_request_telemetry")
            return self._hit(self._format_system(data), "combined_telemetry", "get_pre_request_telemetry")

        if ("processo" in words or "processos" in words) and "memoria" in words and words.intersection({"mais", "maior", "consome", "consumir", "utiliza"}):
            data = self._tool("list_top_processes", {"limit": 1})
            rows = list(data.get("value") or data.get("processes") or [])
            if rows:
                row = rows[0]
                response = f"O processo que mais memória consome é {row.get('name')} (PID {row.get('pid')}), com {row.get('memory_mib')} MiB."
            else:
                response = data.get("message") or data.get("error") or "Não consegui obter a lista de processos."
            return self._hit(response, "top_memory_process", "list_top_processes")

        process_match = re.search(r"\b([a-z0-9_.+-]+\.exe)\b", text, flags=re.IGNORECASE)
        if process_match and words.intersection({"corre", "correr", "execucao", "ativo", "aberto"}):
            wanted = process_match.group(1).casefold()
            data = self._tool("list_top_processes", {"limit": 25})
            rows = list(data.get("value") or data.get("processes") or [])
            matches = [row for row in rows if str(row.get("name") or "").casefold() == wanted]
            response = (f"Sim. {wanted} está a correr." if matches else f"Não encontrei {wanted} entre os processos observados.")
            return self._hit(response, "process_running_query", "list_top_processes")

        # Current GPU telemetry.
        if (
            words.intersection({"gpu", "grafica", "rtx"})
            and words.intersection({"agora", "atual", "temperatura", "estado", "utilizacao", "uso", "vram", "memoria"})
        ):
            data = self._tool("get_pre_request_telemetry")
            return self._hit(
                self._format_gpu(data),
                "gpu_status",
                "get_pre_request_telemetry",
            )

        if ("cpu" in words or "processador" in words) and words.intersection({"utilizacao", "uso", "atual", "agora"}):
            data = self._tool("get_pre_request_telemetry")
            value = data.get("cpu_percent")
            return self._hit(f"A utilização atual do CPU é de {value}%." if value is not None else "Não tenho uma amostra atual do CPU.", "cpu_status", "get_pre_request_telemetry")

        if "ram" in words and words.intersection({"utilizacao", "uso", "usar", "utilizar", "total", "quanto", "quanta", "atual", "agora"}):
            data = self._tool("get_pre_request_telemetry")
            used = data.get("memory_used_gib")
            pct = data.get("memory_percent")
            total = round(float(used) / (float(pct) / 100.0), 2) if isinstance(used, (int,float)) and isinstance(pct, (int,float)) and pct else None
            response = f"Está a utilizar {used} GB de RAM ({pct}%)." if used is not None else "Não tenho uma amostra atual da RAM."
            if total is not None:
                response += f" Total aproximado: {total} GB."
            return self._hit(response, "ram_status", "get_pre_request_telemetry")

        # Current system telemetry.
        if any(p in normalized for p in (
            "como esta o pc", "como esta o meu pc",
            "como esta o computador", "como esta o meu computador",
            "estado do pc", "estado do computador", "estado do sistema",
            "resumo rapido do estado atual do meu computador",
            "resumo do estado atual do computador",
        )):
            data = self._tool("get_pre_request_telemetry")
            return self._hit(
                self._format_system(data),
                "system_status",
                "get_pre_request_telemetry",
            )

        return FastRouteResult(False)

    @staticmethod
    def _format_security_audit(data: dict[str, Any]) -> str:
        if not data.get("ok"):
            return data.get("message") or "Não consegui concluir a auditoria do sistema."

        summary = data.get("summary") or {}
        current = summary.get("current_user") or "O utilizador atual"
        parts = []

        if summary.get("current_user_admin"):
            parts.append(f"{current} tem privilégios de administrador.")
        else:
            parts.append(f"{current} não aparece como administrador.")

        if summary.get("only_current_enabled_admin_detected") is True:
            parts.append("É o único administrador habilitado que consegui confirmar.")
        elif summary.get("other_admin_count", 0):
            parts.append(
                f"Encontrei {summary['other_admin_count']} outro(s) administrador(es) "
                "habilitado(s) ou de estado desconhecido."
            )
        else:
            parts.append(
                "Não confirmei outros administradores habilitados, embora algumas "
                "contas externas possam não expor o estado completo."
            )

        if summary.get("active_remote_access_detected"):
            details = []
            if summary.get("remote_interactive_session_count"):
                details.append(f"{summary['remote_interactive_session_count']} sessão RDP/remota")
            if summary.get("smb_session_count"):
                details.append(f"{summary['smb_session_count']} sessão SMB")
            parts.append("Há acesso remoto ativo detetado: " + " e ".join(details) + ".")
        elif summary.get("other_session_count"):
            parts.append(
                f"Não encontrei RDP/SMB ativo, mas há {summary['other_session_count']} "
                "outra(s) sessão(ões) de utilizador."
            )
        else:
            parts.append(
                "Não encontrei outra sessão de utilizador nem RDP/SMB ativo neste momento."
            )

        if summary.get("remote_access_software_count"):
            parts.append(
                f"Há {summary['remote_access_software_count']} processo(s) de software "
                "de acesso remoto em execução; isso indica capacidade de acesso, "
                "não prova uma ligação humana ativa."
            )

        if summary.get("remote_assistance_enabled") is True:
            parts.append(
                "A Assistência Remota do Windows está permitida, "
                "mas não existe uma sessão remota ativa detetada."
            )

        return " ".join(parts)

    @staticmethod
    def _format_location(data: dict[str, Any]) -> str:
        if not data.get("ok"):
            return data.get("message") or "Não consegui obter a localização neste momento."
        lat, lon = data.get("latitude"), data.get("longitude")
        if data.get("source") == "windows_location_service":
            accuracy = data.get("accuracy_m")
            acc = f", com precisão estimada de {round(float(accuracy))} metros" if accuracy is not None else ""
            return f"A localização atual indicada pelo Windows é {float(lat):.5f}, {float(lon):.5f}{acc}."
        place = data.get("label") or ", ".join(str(v) for v in (data.get("locality"), data.get("municipality"), data.get("country")) if v)
        return f"A localização-base configurada é {place}, nas coordenadas {float(lat):.5f}, {float(lon):.5f}. Não estou a usar geolocalização por IP."

    @staticmethod
    def _format_environment(data: dict[str, Any]) -> str:
        if not data.get("ok"):
            return "Não consegui obter o tempo e o estado do mar neste momento."
        w, m = data.get("weather") or {}, data.get("marine") or {}
        loc = (data.get("location") or {}).get("label") or "Furadouro"
        text = f"Em {loc}, está {w.get('condition','tempo variável')}"
        if w.get("temperature_c") is not None: text += f", com {round(float(w['temperature_c']),1)} graus"
        if w.get("relative_humidity_percent") is not None: text += f" e {round(float(w['relative_humidity_percent']))} por cento de humidade"
        text += "."
        if m.get("state") and m.get("state") != "desconhecido":
            text += f" O mar está {m['state']}"
            if m.get("wave_height_m") is not None: text += f", com ondas de cerca de {round(float(m['wave_height_m']),1)} metros"
            if m.get("wave_period_s") is not None: text += f" e período de {round(float(m['wave_period_s']),1)} segundos"
            text += "."
        return text

    @staticmethod
    def _format_gpu(data: dict[str, Any]) -> str:
        gpu_list = data.get("gpu") or data.get("gpus") or []
        if not gpu_list:
            return "Não tenho uma amostra atual da GPU."
        gpu = gpu_list[0]
        parts = []
        if gpu.get("temperature_c") is not None:
            parts.append(f"{gpu['temperature_c']} graus")
        if gpu.get("utilization_percent") is not None:
            parts.append(f"{gpu['utilization_percent']} por cento de utilização")
        used = gpu.get("memory_used_mib")
        total = gpu.get("memory_total_mib")
        if used is not None and total:
            parts.append(
                f"{round(float(used) / 1024, 1)} de "
                f"{round(float(total) / 1024, 1)} gigabytes de V RAM"
            )
        return (
            f"A GPU está a {', '.join(parts)}."
            if parts else
            "Tenho a amostra da GPU, mas faltam métricas utilizáveis."
        )

    @staticmethod
    def _format_system(data: dict[str, Any]) -> str:
        if not data:
            return "Ainda não tenho telemetria suficiente."

        chunks = []
        if data.get("cpu_percent") is not None:
            chunks.append(f"C P U a {data['cpu_percent']} por cento")
        if data.get("memory_percent") is not None:
            chunks.append(f"RAM a {data['memory_percent']} por cento")

        gpu_list = data.get("gpu") or []
        if gpu_list:
            gpu = gpu_list[0]
            gpu_text = "GPU"
            if gpu.get("utilization_percent") is not None:
                gpu_text += f" a {gpu['utilization_percent']} por cento"
            if gpu.get("temperature_c") is not None:
                gpu_text += f" e {gpu['temperature_c']} graus"
            chunks.append(gpu_text)

        return ". ".join(chunks) + "." if chunks else "Ainda não tenho telemetria suficiente."
