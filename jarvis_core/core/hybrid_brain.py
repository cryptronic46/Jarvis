from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
import re
import unicodedata

from jarvis_core.services.autonomy import authorized_learning, build_external_learning_query
from jarvis_core.services.semantic_request import StructuredRequest
from jarvis_core.services.learning_gap import (
    assess_learning_gap,
    contains_secret_hints,
    freshness_days_for_topic,
)


@dataclass(slots=True)
class HybridDecision:
    route: str
    reason: str
    use_web: bool = False
    deep: bool = False
    text: str = ""
    complexity_score: int = 0


@dataclass(slots=True)
class HybridAnswer:
    text: str
    route: str
    model: str | None
    elapsed_ms: int
    reason: str
    used_web: bool = False
    cloud_estimated_usd: float = 0.0


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip()


class HybridRoutePolicy:
    """
    0.27.8 JARVIS-native learning-first routing policy.

    Fast/local work stays on this PC. Public web retrieval is direct HTTPS and
    synthesized locally. External AI is structurally blocked.
    """

    EXPLICIT_WEB = (
        "pesquisa na internet", "pesquisa na web", "pesquisa online",
        "procura na internet", "procura na web", "procura online",
        "vai a internet", "vai à internet", "usa a internet", "usa a web",
        "faz uma pesquisa online", "consulta a internet", "consulta a web",
    )

    WEB_MARKERS = (
        "noticias", "notícia", "noticias de hoje", "hoje na internet",
        "esta semana", "agora na internet", "mais recente", "últimas notícias",
        "preco atual", "preço atual", "oferta de emprego", "site oficial",
        "link oficial", "cotacao", "cotação", "mercado hoje",
        "resultados de hoje",
    )

    DEEP_MARKERS = (
        "pesquisa profunda", "analise profunda", "análise profunda",
        "muito detalhado", "investiga a fundo", "arquitetura complexa",
        "debug complexo", "problema complexo",
    )

    EXTERNAL_AI_MARKERS = (
        "usa a cloud", "usa cloud", "pergunta ao chatgpt", "usa o chatgpt",
        "escala para a cloud", "usa o sol", "gpt 5.6 sol",
        "outra inteligencia artificial", "outra ia", "outra ai",
        "consulta outra inteligencia artificial", "consulta outra ia",
        "recorre a outra inteligencia artificial",
    )

    EXTERNAL_AI_PROVIDER_RE = re.compile(
        r"\b(?:usa|utiliza|usando|utilizando|consulta|pergunta\s+(?:ao|a)|recorre\s+(?:ao|a)|confirma\s+com|valida\s+com|pede\s+(?:ao|a))\s+(?:o\s+|a\s+)?(?:chatgpt|openai|gemini|google gemini|claude|anthropic|perplexity|microsoft copilot|copilot|grok|xai|x ai|deepseek|deep seek|le chat|meta ai)\b",
        re.IGNORECASE,
    )

    @staticmethod
    def research_subject(value: str) -> str:
        """Extract the actual topic from a natural web-search instruction."""
        raw = str(value or "").strip()
        raw = re.sub(r"(?i)https?://[^\s<>\"']+", " ", raw)
        raw = re.sub(
            r"(?i)^\s*(?:jarvis[,;:]?\s*)?(?:pesquisa|procura|consulta|investiga|estuda)"
            r"(?:\s+(?:na|pela|via|a|à))?\s+(?:internet|web|online)?\s*",
            "", raw, count=1,
        )
        raw = re.sub(r"(?i)^\s*(?:e\s+)?(?:diz[- ]?me|explica[- ]?me)\s+", "", raw, count=1)
        raw = re.sub(r"(?i)\s+(?:e\s+)?(?:explica[- ]?me|resume|resumidamente|em duas frases).*$", "", raw)
        raw = re.sub(r"(?i)^\s*qual\s+(?:e|é)\s+", "", raw)
        raw = re.sub(r"\s+", " ", raw).strip(" .,:;!?-")
        return raw[:300] or str(value or "").strip()[:300]

    @staticmethod
    def research_search_query(subject: str, original: str = "") -> str:
        """Build a retrieval-oriented query without changing the user's topic."""
        clean = str(subject or "").strip()
        norm = _norm(f"{original} {clean}")
        if "site oficial" in norm or "link oficial" in norm:
            entity = re.sub(r"(?i)\b(?:site|link)\s+oficial(?:\s+do|\s+da|\s+de)?\b", " ", clean)
            entity = re.sub(r"\s+", " ", entity).strip(" .,:;!?-")
            return f"{entity or clean} official site"[:300]
        if any(marker in norm for marker in ("versao atual", "versão atual", "versao mais recente", "versão mais recente", "mais recente disponivel", "mais recente disponível")):
            entity = re.sub(r"(?i)\b(?:a\s+)?(?:vers[aã]o\s+)?(?:atual|mais recente)(?:\s+dispon[ií]vel)?(?:\s+do|\s+da|\s+de)?\b", " ", clean)
            entity = re.sub(r"\s+", " ", entity).strip(" .,:;!?-")
            return f"{entity or clean} latest stable release official"[:300]
        return clean[:300]

    def __init__(self, settings):
        self.settings = settings

    def complexity_score(self, user_text: str) -> int:
        """Estimate local task complexity for the JARVIS performance profile.

        External AI is structurally blocked. This score may select a deeper
        local profile, but it can never enable or justify an external LLM.
        """
        raw = str(user_text or "")
        text = _norm(raw)
        score = 0
        if any(_norm(marker) in text for marker in self.DEEP_MARKERS):
            score += 3
        if len(raw) >= 700:
            score += 3
        elif len(raw) >= 350:
            score += 2
        elif len(raw) >= 180:
            score += 1
        if "```" in raw or raw.count("\n") >= 12:
            score += 2
        complex_markers = (
            "arquitetura", "architecture", "refator", "refactor",
            "debug", "traceback", "stack trace", "analisa profundamente",
            "compara varias", "compara várias", "trade-off", "tradeoff",
            "plano detalhado", "multi-etapa", "multi etapa", "otimiza tudo",
            "auditoria completa", "investigacao completa", "investigação completa",
        )
        if any(marker in text for marker in complex_markers):
            score += 1
        if raw.count("?") >= 4 or raw.count(";") >= 8:
            score += 1
        return min(score, 10)

    def decide(self, user_text: str, cloud_available: bool = False) -> HybridDecision:
        del cloud_available  # compatibility argument; policy routing is complexity/local-first driven.
        text = user_text.strip()
        normalized = _norm(text)
        complexity = self.complexity_score(text)

        if normalized.startswith("/local "):
            return HybridDecision("local", "forced_local", text=text.split(" ", 1)[1], complexity_score=complexity)
        if normalized.startswith("/web "):
            return HybridDecision(
                "research", "forced_web", use_web=True, deep=False,
                text=text.split(" ", 1)[1], complexity_score=complexity,
            )
        if normalized.startswith("/research "):
            return HybridDecision(
                "research", "forced_research", use_web=True, deep=False,
                text=text.split(" ", 1)[1], complexity_score=complexity,
            )
        if normalized.startswith("/cloud ") or normalized.startswith("/sol "):
            return HybridDecision(
                "external_ai_blocked", "external_ai_hard_block", deep=False,
                text=text.split(" ", 1)[1] if " " in text else text, complexity_score=complexity,
            )

        explicit_web = any(marker in normalized for marker in self.EXPLICIT_WEB)
        explicit_url = bool(re.search(r"https?://[^\s<>\"']+", text, flags=re.IGNORECASE))
        use_web = explicit_web or explicit_url or any(marker in normalized for marker in self.WEB_MARKERS)
        deep = any(marker in normalized for marker in self.DEEP_MARKERS)
        external_ai_request = (
            any(marker in normalized for marker in self.EXTERNAL_AI_MARKERS)
            or bool(self.EXTERNAL_AI_PROVIDER_RE.search(normalized))
        )

        # Security invariant: named external-AI providers are blocked before any
        # web/research routing. A model refusal is not the security boundary.
        if external_ai_request:
            return HybridDecision(
                "external_ai_blocked", "external_ai_hard_block",
                text=text, deep=False, complexity_score=complexity,
            )

        if use_web:
            reason = "explicit_url" if explicit_url else ("explicit_web" if explicit_web else "web_required")
            return HybridDecision(
                "research", reason, use_web=True, deep=deep,
                text=text, complexity_score=complexity,
            )

        threshold = max(1, int(getattr(self.settings, "external_ai_complexity_threshold", 4)))
        deep = deep or complexity >= threshold
        return HybridDecision("local", "local_first", text=text, deep=deep, complexity_score=complexity)


class HybridBrain:
    """
    Compatibility facade for the 0.27.8 learning-first architecture.

    - Local reasoning: JARVIS-owned llama.cpp/Qwen runtime.
    - Knowledge gaps: ask the OWNER before bounded public-web study, then store
      validated learning locally and retry with request-scoped RAG.
    - External AI: structurally blocked. Web sources are synthesized only by
      the local JARVIS/Qwen runtime.
    """

    def __init__(
        self,
        settings,
        events,
        local_brain,
        cloud_brain=None,
        performance=None,
        autonomy=None,
        research_engine=None,
    ):
        self.settings = settings
        self.events = events
        self.local = local_brain
        self.cloud = cloud_brain  # retained only for legacy diagnostics/migration
        self.performance = performance
        self.autonomy = autonomy
        self.research = research_engine
        self.policy = HybridRoutePolicy(settings)

    def clear_history(self) -> None:
        self.local.clear_history()
        if self.cloud is not None:
            try:
                self.cloud.clear_history()
            except Exception:
                pass

    def _autonomy_gate(
        self,
        *,
        decision: HybridDecision,
        reason: str,
        description: str,
    ) -> HybridAnswer | None:
        if (
            self.autonomy is None
            or not bool(getattr(self.settings, "autonomy_enabled", True))
        ):
            return None
        try:
            if self.autonomy.has_standing_public_web_research():
                return None
        except Exception:
            pass

        payload = {
            "query": decision.text,
            "use_web": True,
            "deep": bool(decision.deep),
            "route_reason": reason,
        }
        gate = self.autonomy.request(
            capability="web_research",
            payload=payload,
            reason=reason,
            description=description,
            action="resume_query",
            source="local_research_router",
        )
        if gate.get("allowed"):
            return None

        return HybridAnswer(
            text=str(
                gate.get("message")
                or "Senhor, preciso da sua autorização antes de pesquisar na Internet."
            ),
            route="AUTH/PENDING",
            model=None,
            elapsed_ms=0,
            reason="owner_authorization_required",
            used_web=False,
        )

    def _cloud_gate(self, decision: HybridDecision, reason: str) -> HybridAnswer | None:
        if self.cloud is None or not self.cloud.available():
            return HybridAnswer(
                text="A camada externa não está configurada/disponível; vou manter o processamento local.",
                route="CLOUD/UNAVAILABLE", model=None, elapsed_ms=0, reason="cloud_unavailable",
            )
        if self.autonomy is None or not bool(getattr(self.settings, "autonomy_enabled", True)):
            return HybridAnswer(
                text="A consulta a IA externa exige o Autonomy Guardian ativo e autorização explícita do Senhor.",
                route="CLOUD/BLOCKED", model=None, elapsed_ms=0, reason="owner_guardian_required",
            )
        gate = self.autonomy.request(
            capability="cloud_reasoning",
            payload={
                "query": decision.text,
                "deep": bool(decision.deep),
                "reason": reason,
                "isolated": True,
            },
            reason=reason,
            description=(
                "consultar uma IA externa enviando apenas o texto deste pedido, "
                "sem memória pessoal, histórico, telemetria ou ferramentas locais: "
                f"{decision.text[:180]}"
            ),
            action="cloud_reasoning", source="learning_first_expert_escalation",
        )
        if gate.get("allowed"):
            return None
        return HybridAnswer(
            text=str(gate.get("message") or "Senhor, preciso da sua autorização para usar recursos externos neste pedido."),
            route="AUTH/PENDING", model=None, elapsed_ms=0, reason="owner_authorization_required",
        )

    def _learning_gap_offer(
        self,
        decision: HybridDecision,
        local_text: str,
    ) -> tuple[HybridAnswer | None, object | None]:
        if not bool(getattr(self.settings, "epistemic_learning_enabled", True)):
            return None, None
        if not bool(getattr(self.settings, "autonomy_proactive_learning_enabled", True)):
            return None, None
        try:
            stale_days = freshness_days_for_topic(
                decision.text,
                int(getattr(self.settings, "epistemic_learning_stale_days", 120)),
            )
            assessment = assess_learning_gap(
                decision.text,
                local_text,
                authorized_learning(),
                stale_days=stale_days,
            )
        except Exception as exc:
            self.events.emit(
                "EPISTEMIC_GAP_ASSESSMENT_ERROR",
                error=f"{type(exc).__name__}: {exc}",
            )
            return None, None

        self.events.emit(
            "EPISTEMIC_GAP_ASSESSED",
            needs_learning=bool(getattr(assessment, "needs_learning", False)),
            topic=str(getattr(assessment, "topic", ""))[:220],
            reason=str(getattr(assessment, "reason", "")),
            studied=bool(getattr(assessment, "studied", False)),
            stale=bool(getattr(assessment, "stale", False)),
            match_score=float(getattr(assessment, "match_score", 0.0)),
        )

        if not bool(getattr(assessment, "needs_learning", False)):
            return None, assessment
        if self.research is None or not self.research.available():
            return None, assessment
        if self.autonomy is None or not bool(getattr(self.settings, "autonomy_enabled", True)):
            return None, assessment

        topic = str(getattr(assessment, "topic", "") or "").strip()
        if not topic:
            return None, assessment
        payload = {
            "topic": topic,
            "query": build_external_learning_query(topic),
            "original_query": decision.text,
            "deep": True,
            "scope": "single_research_session",
            "trigger": "epistemic_gap",
        }
        gate = self.autonomy.request(
            capability="external_learning",
            payload=payload,
            reason=str(getattr(assessment, "reason", "epistemic_gap")),
            description=(
                "consultar a web pública em modo de leitura, comparar fontes e estudar "
                f"{topic[:200]} antes de voltar a responder"
            ),
            action="external_learning_resume_query",
            source="epistemic_learning_gap",
        )
        if gate.get("allowed"):
            # Normal execution of a pre-approved one-shot grant occurs through the
            # CLI authorization executor. Do not perform network learning here.
            return None, assessment
        if not gate.get("pending"):
            return None, assessment
        return HybridAnswer(
            text=str(gate.get("message") or "Senhor, preciso da sua autorização para estudar este tema na web."),
            route="AUTH/LEARNING",
            model=None,
            elapsed_ms=0,
            reason="epistemic_learning_authorization_required",
            used_web=False,
        ), assessment

    def _expert_offer(
        self,
        decision: HybridDecision,
        *,
        assessment: object | None,
    ) -> HybridAnswer | None:
        if not bool(getattr(self.settings, "expert_escalation_enabled", True)):
            return None
        if self.cloud is None or not self.cloud.available():
            return None
        if contains_secret_hints(decision.text):
            self.events.emit("EXPERT_ESCALATION_SKIPPED", reason="possible_secret_in_query")
            return None
        # Learning-first invariant: if the gap has not yet been studied, do not
        # jump directly to another AI. The web-study authorization comes first.
        if assessment is not None and bool(getattr(assessment, "needs_learning", False)):
            return None
        return self._cloud_gate(decision, "studied_knowledge_still_insufficient")

    @staticmethod
    def _local_result_insufficient(text: str, *, complex_request: bool = False) -> bool:
        """Conservative proof that local reasoning did not actually solve the request.

        Cloud is not a quality preference. It is an escalation path used only
        when the local result is empty or explicitly reports inability/insufficient
        information. Short but valid answers are not escalated automatically.
        """
        value = str(text or "").strip()
        if not value:
            return True
        normalized = _norm(value)
        inability_markers = (
            "nao sei", "não sei", "nao conheco", "não conheço", "desconheco", "desconheço",
            "nao tenho conhecimento suficiente", "não tenho conhecimento suficiente",
            "nao consigo concluir", "nao consegui concluir", "nao tenho informacao suficiente",
            "não tenho informação suficiente", "informacao insuficiente", "informação insuficiente",
            "dados insuficientes", "nao disponho de informacao", "não disponho de informação",
            "nao posso determinar", "nao consigo determinar", "não consigo determinar",
            "unable to determine", "insufficient information", "i cannot determine",
            "i can't determine", "i don't know", "i do not know",
        )
        if any(marker in normalized for marker in inability_markers):
            return True
        # For a complex task, an answer that is effectively just a refusal/error
        # marker counts as insufficient; substantive local prose does not.
        if complex_request and len(value) < 40 and normalized in {
            "erro", "error", "nao sei", "não sei", "indisponivel", "indisponível"
        }:
            return True
        return False

    def ask(
        self,
        user_text: str,
        *,
        request: StructuredRequest | None = None,
    ) -> HybridAnswer:
        started = monotonic()
        decision = self.policy.decide(user_text, cloud_available=False)

        self.events.emit(
            "HYBRID_ROUTE",
            route=decision.route,
            reason=decision.reason,
            web=decision.use_web,
            deep=decision.deep,
            external_ai=False,
            complexity_score=decision.complexity_score,
        )

        if decision.route == "external_ai_blocked":
            return HybridAnswer(
                text=(
                    "Não posso consultar outra inteligência artificial, Senhor. "
                    "Essa rota está bloqueada no Core. Posso responder com o meu cérebro local "
                    "ou, quando fizer sentido, pesquisar fontes públicas na Web e sintetizá-las localmente."
                ),
                route="LOCAL/EXTERNAL_AI_BLOCKED", model=self.settings.model,
                elapsed_ms=round((monotonic() - started) * 1000),
                reason="external_ai_hard_block", used_web=False,
            )

        if decision.route == "research":
            direct_authority = decision.reason in {
                "forced_web",
                "forced_research",
                "explicit_web",
                "explicit_url",
            }
            if not direct_authority:
                gated = self._autonomy_gate(
                    decision=decision,
                    reason=decision.reason,
                    description=f"pesquisar diretamente na Internet sobre: {decision.text[:220]}",
                )
                if gated is not None:
                    gated.elapsed_ms = round((monotonic() - started) * 1000)
                    return gated

            if self.research is None or not self.research.available():
                return HybridAnswer(
                    text=(
                        "A pesquisa direta na Internet está indisponível ou bloqueada pelo modo de privacidade. "
                        "O cérebro local continua disponível."
                    ),
                    route="RESEARCH/UNAVAILABLE",
                    model=self.settings.model,
                    elapsed_ms=round((monotonic() - started) * 1000),
                    reason="research_unavailable",
                )

            subject = self.policy.research_subject(decision.text)
            url_match = re.search(r"https?://[^\s<>\"']+", decision.text, flags=re.IGNORECASE)
            if url_match:
                url = url_match.group(0).rstrip(".,;!?)\"]}")
                result = self.research.research_url(
                    url, query=decision.text, topic=subject, deep=decision.deep,
                )
            else:
                search_query = self.policy.research_search_query(subject, decision.text)
                result = self.research.research(
                    decision.text, topic=subject, search_query=search_query, deep=decision.deep,
                )
            if result.ok:
                return HybridAnswer(
                    text=result.text,
                    route="RESEARCH/LOCAL",
                    model=result.model or self.settings.model,
                    elapsed_ms=result.elapsed_ms,
                    reason=decision.reason,
                    used_web=True,
                )
            return HybridAnswer(
                text=result.text,
                route="RESEARCH/ERROR",
                model=self.settings.model,
                elapsed_ms=result.elapsed_ms,
                reason=result.error or "research_error",
                used_web=False,
            )

        if decision.route == "cloud":
            return HybridAnswer(
                text="Outra inteligência artificial está bloqueada no Core JARVIS.",
                route="LOCAL/EXTERNAL_AI_BLOCKED", model=self.settings.model,
                elapsed_ms=round((monotonic() - started) * 1000), reason="external_ai_hard_block",
            )

        # Local-first: always attempt the local model first. External compute is
        # considered only for explicit OWNER routing or genuine complexity after
        # that local attempt, never merely because cloud exists or the PC is busy.
        try:
            if request is None:
                local_text = self.local.ask(decision.text)
            else:
                local_text = self.local.ask(
                    decision.text,
                    request=request,
                )
            local_failed = not str(local_text or "").strip()
        except Exception as exc:
            local_text = ""
            local_failed = True
            self.events.emit("LOCAL_REASONING_ERROR", error=type(exc).__name__)

        threshold = max(1, int(getattr(self.settings, "external_ai_complexity_threshold", 4)))
        complex_request = decision.complexity_score >= threshold
        local_insufficient = self._local_result_insufficient(
            local_text, complex_request=complex_request
        )
        self.events.emit(
            "LOCAL_SUFFICIENCY",
            complex_request=complex_request,
            complexity_score=decision.complexity_score,
            insufficient=local_insufficient,
            local_failed=local_failed,
            external_ai_enabled=bool(self.cloud is not None and self.cloud.available()),
        )

        if local_insufficient:
            learning_offer, assessment = self._learning_gap_offer(decision, local_text)
            if learning_offer is not None:
                learning_offer.elapsed_ms = round((monotonic() - started) * 1000)
                return learning_offer
            # External AI is intentionally not an escalation path.

        elapsed_ms = round((monotonic() - started) * 1000)
        return HybridAnswer(
            text=local_text or "Não consegui concluir localmente este pedido.",
            route="LOCAL", model=self.settings.model, elapsed_ms=elapsed_ms,
            reason=decision.reason,
        )
