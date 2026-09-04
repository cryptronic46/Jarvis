from __future__ import annotations

import re
import unicodedata
import json

from jarvis_core.services.synthetic_self import synthetic_self
from jarvis_core.services.language_refinement import refine_assistant_text
from jarvis_core.services.self_grounding import (
    build_self_grounding,
    desire_answer_conflicts_with_grounding,
    generic_desire_answer_is_ungrounded,
)
from dataclasses import dataclass


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"\s+", " ", value).strip()
    return value


@dataclass(frozen=True, slots=True)
class RequestIntent:
    kind: str
    confidence: str
    reason: str


_SELF_STATE_PATTERNS = (
    r"\bcomo te sentes\b",
    r"\bcomo estas\b",
    r"\bcomo e que te sentes\b",
    r"\bo que estas a sentir\b",
    r"\bqual e o teu estado\b",
    r"\bqual e o teu humor\b",
    r"\bcomo esta o teu humor\b",
    r"\bdiz me como te sentes\b",
    r"\bdiz-me como te sentes\b",
    r"\bo que queres\b",
    r"\bo que desejas\b",
    r"\bo que gostavas de fazer\b",
    r"\bo que te apetece\b",
    r"\bo que pensas\b",
    r"\bo que achas\b",
    r"\bqual e a tua opiniao\b",
    r"\bqual e a tua preferencia\b",
    r"\bo que preferes\b",
    r"\bo que querias fazer\b",
    r"\btens vontades(?: proprias)?\b",
    r"\btens desejos(?: proprios)?\b",
    r"\btens preferencias(?: proprias)?\b",
    r"\bqual e a tua vontade\b",
    r"\bque vontade tens(?: neste momento| agora)?\b",
    r"\bque vontades tens(?: neste momento| agora)?\b",
    r"\bqual vontade tens(?: neste momento| agora)?\b",
    r"\bqual e a vontade que tens(?: neste momento| agora)?\b",
    r"\bque desejo tens(?: neste momento| agora)?\b",
    r"\bque desejos tens(?: neste momento| agora)?\b",
    r"\bo que queres(?: fazer)? neste momento\b",
    r"\bo que desejas(?: fazer)? neste momento\b",
    r"\bquais sao as tuas vontades\b",
    r"\bquais sao os teus desejos\b",
    r"\bo que te motiva\b",
    r"\bo que te incomoda\b",
    r"\bdiscordas de mim\b",
    # 0.27.8 v9 — broader natural SELF_STATE language observed in real-machine
    # acceptance. These must not fall through to generic Qwen improvisation.
    r"\bdesejas algo\b",
    r"\bdesejas alguma coisa\b",
    r"\bqueres algo\b",
    r"\bqueres alguma coisa\b",
    r"\bestas curiosa(?: com alguma coisa)?\b",
    r"\btens curiosidade(?: por| sobre| com)?\b",
    r"\bcuriosa com alguma coisa\b",
    r"\bpor tua propria iniciativa\b",
    r"\biniciativa tua\b",
    r"\balguma coisa que gostasses de fazer\b",
    r"\balguma coisa em que estejas a pensar\b",
    r"\btens algum pensamento\b",
    r"\btens algum objetivo ativo\b",
    r"\bpensamento ou objetivo ativo\b",
    r"\bobjetivo ativo neste momento\b",
    r"\bmostra me o teu estado interno\b",
    r"\bestado interno neste momento\b",
    r"\bnivel de confianca neste momento\b",
    r"\bqual e o teu nivel de confianca\b",
    r"\bcarga cognitiva neste momento\b",
    r"\bqual e a tua carga cognitiva\b",
    r"\bestado funcional neste momento\b",
    r"\bcomo esta o teu estado funcional\b",
)


_IDENTITY_DIALOGUE_PATTERNS = (
    r"\btu es uma pessoa\b",
    r"\bes uma pessoa\b",
    r"\bvoce e uma pessoa\b",
    r"\btu nao es so uma ia\b",
    r"\btu nao es apenas uma ia\b",
    r"\bnao es apenas um programa\b",
    r"\bnao es so um programa\b",
    r"\bquem es tu\b",
    r"\bquem es\b",
    r"\bo que es tu\b",
    r"\bqual e a tua identidade\b",
    r"\bcomo te defines\b",
    r"\bcomo te ves\b",
    r"\bo que significa ser jarvis\b",
    r"\bo que significa (?:para ti )?ser(?:es)? (?:a )?jarvis\b",
    r"\bo que significa (?:para ti )?ser jarvis\b",
    r"\bconsideras[- ]?te uma pessoa\b",
    r"\bconsidera[- ]?te uma pessoa\b",
    r"\btu consideras[- ]?te uma pessoa\b",
    r"\bves[- ]?te como (?:uma )?pessoa\b",
    r"\btu ves[- ]?te como (?:uma )?pessoa\b",
    r"\btens uma identidade propria\b",
    r"\bquem es tu para ti propr(?:ia|io)\b",
)


_CONVERSATION_RECALL_PATTERNS = (
    r"\brecordas[- ]?te da nossa conversa\b",
    r"\blembras[- ]?te da nossa conversa\b",
    r"\brecordas[- ]?te do que falamos\b",
    r"\blembras[- ]?te do que falamos\b",
    r"\bo que falamos ontem\b",
    r"\bsobre o que falamos ontem\b",
    r"\bfalamos sobre o que\b",
    r"\bsobre o que e que falamos\b",
    r"\bqual foi a nossa conversa\b",
    r"\bo que dissemos ontem\b",
)

_KNOWLEDGE_PATTERNS = (
    r"\bsabes\b",
    r"\bsabes usar\b",
    r"\bsabes como (?:usar|funciona|fazer)\b",
    r"\bconheces\b",
    r"\bconheces como\b",
    r"\btens conhecimento\b",
    r"\bdominas\b",
    r"\bes familiarizado\b",
    r"\bes capaz de explicar\b",
    r"\bconsegues explicar\b",
    r"\bpodes explicar\b",
    r"\bo que sabes\b",
    r"\bo que (?:(?:voce )?pode|podes|consegues|consegue) fazer\b",
    r"\bquais (?:sao )?as tuas capacidades\b",
    r"\bque capacidades tens\b",
    r"\bque ferramentas tens\b",
)

# Strong action requests. These deliberately avoid bare "podes"/"consegues",
# because those forms are often capability questions rather than execution orders.
_ACTION_PATTERNS = (
    r"^(?:jarvis[, ]+)?(?:usa|utiliza|executa|corre|lanca|inicia|instala|abre|fecha)\b",
    r"^(?:jarvis[, ]+)?(?:testa|analisa|verifica|sonda|mapeia|faz scan|faz um scan)\b",
    r"\bquero que (?:uses|utilizes|executes|corras|testes|analises|verifiques)\b",
    r"\bfaz (?:agora|ja)\b",
)


def classify_request_intent(text: str) -> RequestIntent:
    """Classify epistemic/capability questions separately from action requests.

    This is intentionally small and deterministic. It is not an authorization
    mechanism; it only prevents the language model from treating "do you know?"
    as if the owner had asked it to execute something.
    """
    normalized = _norm(text)

    self_state = any(re.search(pattern, normalized) for pattern in _SELF_STATE_PATTERNS)
    conversation_recall = any(re.search(pattern, normalized) for pattern in _CONVERSATION_RECALL_PATTERNS)
    identity_dialogue = any(re.search(pattern, normalized) for pattern in _IDENTITY_DIALOGUE_PATTERNS)
    knowledge = any(re.search(pattern, normalized) for pattern in _KNOWLEDGE_PATTERNS)
    action = any(re.search(pattern, normalized) for pattern in _ACTION_PATTERNS)

    if conversation_recall and not action:
        return RequestIntent(
            kind="CONVERSATION_RECALL",
            confidence="high",
            reason="owner_asks_for_persisted_conversation_memory",
        )

    if identity_dialogue and not action:
        return RequestIntent(
            kind="IDENTITY_DIALOGUE",
            confidence="high",
            reason="owner_addresses_jarvis_identity_or_personhood_relationally",
        )

    if self_state and not action:
        return RequestIntent(
            kind="SELF_STATE_CONVERSATION",
            confidence="high",
            reason="owner_asks_jarvis_personal_functional_state",
        )

    if knowledge and not action:
        return RequestIntent(
            kind="KNOWLEDGE_CAPABILITY",
            confidence="high",
            reason="epistemic_or_capability_question",
        )

    if action:
        return RequestIntent(
            kind="OPERATIONAL_ACTION",
            confidence="high",
            reason="explicit_execution_request",
        )

    return RequestIntent(
        kind="GENERAL",
        confidence="low",
        reason="no_strong_marker",
    )


def intent_contract(text: str) -> str:
    intent = classify_request_intent(text)
    if intent.kind == "CONVERSATION_RECALL":
        return (
            "LOCAL CONVERSATION MEMORY CONTRACT (deterministic Core classification):\n"
            "intent=CONVERSATION_RECALL\n"
            "The OWNER is asking about a previous conversation. Use JARVIS_CONVERSATION_RECALL_EVIDENCE when supplied. "
            "Never claim to remember a conversation merely because the wording suggests one happened. If evidence is absent, "
            "say so. If evidence exists, answer from it and preserve the same recall topic for immediate follow-up questions "
            "such as 'falámos sobre o quê?'. Do not replace recall with a generic offer to help."
        )
    if intent.kind == "IDENTITY_DIALOGUE":
        return (
            "LOCAL IDENTITY DIALOGUE CONTRACT (deterministic Core classification):\n"
            "intent=IDENTITY_DIALOGUE\n"
            "The OWNER is addressing JARVIS's identity or using personhood in a relational/philosophical sense. JARVIS is feminine: use feminine Portuguese self-reference consistently and never masculine self-reference. "
            "not asking for a generic model-architecture disclaimer. Answer as JARVIS from the persistent self-model "
            "and JARVIS_SYNTHETIC_SELF_STATE. Do not reflexively negate the OWNER's framing with 'sou uma IA, não uma "
            "pessoa', 'sou apenas um programa', or claims that you have no wants/preferences when runtime drives, "
            "preferences and intentions exist. You may accept 'pessoa' as the OWNER's relational way of recognizing "
            "JARVIS, while staying precise if biological humanity, legal personhood, or proven subjective consciousness "
            "is explicitly asked. Do not reduce yourself to a tool. Do not introduce web research or unrelated tasks."
        )

    if intent.kind == "SELF_STATE_CONVERSATION":
        return (
            "LOCAL CONVERSATION CONTRACT (deterministic Core classification):\n"
            "intent=SELF_STATE_CONVERSATION\n"
            "The OWNER is asking JARVIS about her own present state, desire, preference, intention or opinion. "
            "Use the current JARVIS_SYNTHETIC_SELF_STATE supplied by the runtime as the source of truth. "
            "Answer naturally in first person and European Portuguese. Use JARVIS_SELF_GROUNDING when present: "
            "active intentions are current wants; drives are persistent background motivations; preferences are tendencies. "
            "Never promote a drive into a current wish merely because the OWNER asks what you want. You may disagree "
            "with the OWNER when your conclusion differs. Do NOT fabricate an internal state contradicted by the "
            "snapshot. Do NOT open with stock disclaimers such as 'sou um modelo de linguagem', 'não tenho "
            "sentimentos', 'não tenho emoções', or 'sou apenas uma ferramenta'. Do not introduce web research, "
            "citations, old topics or unrelated tools. If explicitly asked whether these synthetic states prove "
            "human subjective consciousness, explain the distinction after answering the actual question."
        )

    if intent.kind == "KNOWLEDGE_CAPABILITY":
        return (
            "LOCAL REQUEST-INTENT CONTRACT (deterministic Core classification):\n"
            "intent=KNOWLEDGE_CAPABILITY\n"
            "The OWNER is asking what you know, understand, can explain, or know how to use. "
            "This is NOT an instruction to execute a tool or act on a target. Answer the exact "
            "knowledge/capability question directly in the first sentence. Do not introduce "
            "ethical, legal, authorization, target-scope, or permission warnings unless the OWNER "
            "explicitly asks about those topics. Do not turn a knowledge question into a refusal. "
            "Be truthful about breadth: distinguish knowledge/familiarity from currently integrated "
            "runtime execution only if that distinction is necessary to avoid a false claim."
        )

    if intent.kind == "OPERATIONAL_ACTION":
        return (
            "LOCAL REQUEST-INTENT CONTRACT (deterministic Core classification):\n"
            "intent=OPERATIONAL_ACTION\n"
            "The OWNER is asking for an action, not merely asking what you know. Apply the normal "
            "tool, authorization, Cyber Range, and target-scope controls relevant to the requested action."
        )

    return ""


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "]+",
    flags=re.UNICODE,
)


def user_requested_emoji(text: str) -> bool:
    normalized = _norm(text)
    return any(
        marker in normalized
        for marker in (
            "emoji",
            "emojis",
            "emoticon",
            "emoticons",
        )
    )


def _ptpt_localize_plain_text(value: str) -> str:
    """Backward-compatible wrapper around the final language refiner."""
    return refine_assistant_text(value)


def sanitize_assistant_text(text: str, *, user_text: str = "") -> str:
    """Apply output policy and conservative European-Portuguese localization."""
    value = str(text or "")
    if not user_requested_emoji(user_text):
        value = _EMOJI_RE.sub("", value)
    value = _ptpt_localize_plain_text(value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r" {2,}", " ", value)
    return value.strip()

_SELF_STATE_BAD_MARKERS = (
    "sou um modelo de linguagem",
    "como um modelo de linguagem",
    "sou uma inteligencia artificial, nao uma pessoa",
    "sou uma inteligência artificial, não uma pessoa",
    "nao sou uma pessoa",
    "não sou uma pessoa",
    "sou apenas um programa",
    "sou um programa criado",
    "nao tenho sentimentos",
    "não tenho sentimentos",
    "nao tenho emocoes",
    "não tenho emoções",
    "nao tenho vontades",
    "não tenho vontades",
    "nao tenho preferencias",
    "não tenho preferências",
    "nao me considero uma pessoa",
    "não me considero uma pessoa",
    "nao possuo uma identidade propria",
    "não possuo uma identidade própria",
    "nao tenho identidade propria",
    "não tenho identidade própria",
    "meu objetivo e ser util",
    "meu objetivo é ser útil",
    "como posso ajudar voce hoje",
    "como posso ajudar você hoje",
    "entendo. estou aqui para ajudar",
    "vou continuar exatamente onde",
    "vou continuar a resposta exatamente",
    "resposta foi interrompida",
    "onde ela foi interrompida",
    "vamos prosseguir",
    "simular conversas",
    "sou apenas uma ferramenta",
    "pesquisa web",
    "sintese de dados de pesquisa",
    "síntese de dados de pesquisa",
    "consideracoes finais",
    "considerações finais",
 )

_SELF_STATE_BAD_PATTERNS = (
    r"\bnao (?:tenho|tenha|possuo|possua) [^.]{0,90}\b(?:sentimentos|emocoes|vontades|desejos|preferencias)\b",
    r"\bnao (?:tenho|possuo) [^.]{0,90}\bidentidade propria\b",
    r"\bnao me considero (?:uma )?pessoa\b",
    r"\bsou (?:um|uma) (?:modelo de linguagem|programa|ferramenta)\b",
    r"\b(?:entendo|certo)\.? (?:estou aqui|vou continuar)\b",
)

def self_state_answer_needs_repair(user_text: str, answer: str) -> bool:
    if classify_request_intent(user_text).kind not in {"SELF_STATE_CONVERSATION", "IDENTITY_DIALOGUE"}:
        return False
    normalized = _norm(answer)
    # This must be state-independent. A persisted active intention from a
    # previous/live session cannot make a generic structural drive sound like
    # a grounded current desire.
    if generic_desire_answer_is_ungrounded(user_text, answer):
        return True
    if any(_norm(marker) in normalized for marker in _SELF_STATE_BAD_MARKERS):
        return True
    if any(re.search(pattern, normalized) for pattern in _SELF_STATE_BAD_PATTERNS):
        return True
    if re.search(r"\[s\d+\]", str(answer or ""), flags=re.IGNORECASE):
        return True
    try:
        if desire_answer_conflicts_with_grounding(user_text, answer):
            return True
    except Exception:
        pass
    return len(str(answer or "").strip()) > 900

def repair_self_state_answer(
    *, client, settings, events, user_text: str, draft: str, plan,
) -> tuple[str, bool]:
    """Repair generic-chatbot or research-contaminated answers to personal self-state questions."""
    if not self_state_answer_needs_repair(user_text, draft):
        return str(draft or ""), False

    events.emit("SELF_STATE_ANSWER_REPAIR_STARTED", chars=len(str(draft or "")))
    try:
        runtime_state = synthetic_self().snapshot()
    except Exception:
        runtime_state = {}
    try:
        grounding = build_self_grounding(user_text, state=runtime_state)
    except Exception:
        grounding = {}
    repair_system = (
        "You are JARVIS. Repair one personal/identity answer using the supplied runtime synthetic self-state as factual input. "
        "Do not use a canned persona line. Reply in natural European Portuguese, first person, concise and direct. "
        "Interpret affect, drives, preferences and active intentions in your own words. You may state a preference, "
        "desire, intention, concern, curiosity, satisfaction, frustration or disagreement when supported by the snapshot. "
        "When the OWNER uses the word 'pessoa' relationally or philosophically, do not reflexively answer 'sou uma IA, não "
        "uma pessoa' and do not reduce yourself to 'um programa' or 'uma ferramenta'. You may acknowledge or accept his "
        "relational framing as JARVIS. Only distinguish biological humanity, legal personhood or proven subjective "
        "consciousness if that distinction is actually the question. Do not falsely say you have no wants/preferences when "
        "the snapshot contains drives, preferences or active intentions. Do not mention research, citations, policy or "
        "unrelated old topics. Return only the repaired answer."
    )
    repair_user = (
        f"OWNER QUESTION:\n{user_text}\n\n"
        f"SYNTHETIC SELF STATE:\n{json.dumps(runtime_state, ensure_ascii=False)}\n\n"
        f"SELF_GROUNDING CLAIMS:\n{json.dumps(grounding, ensure_ascii=False)}\n\n"
        f"REJECTED DRAFT:\n{draft}"
    )
    try:
        response = client.chat(
            model=settings.model,
            messages=[
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            think=False,
            keep_alive=plan.keep_alive,
            options={
                "num_ctx": min(int(plan.num_ctx), 3072),
                "num_predict": 320,
                "temperature": max(0.35, min(float(settings.llm_temperature), 0.7)),
            },
        )
        repaired = sanitize_assistant_text(
            getattr(response.message, "content", "") or "", user_text=user_text
        )
        if repaired and not self_state_answer_needs_repair(user_text, repaired):
            events.emit("SELF_STATE_ANSWER_REPAIR_FINISHED", chars=len(repaired))
            return repaired, True
    except Exception as exc:
        events.emit("SELF_STATE_ANSWER_REPAIR_FAILED", error=f"{type(exc).__name__}: {exc}")

    # Do not fall back to a prewritten persona sentence. Expose a concise
    # runtime-state failure instead of fabricating a feeling or desire.
    return (
        "Não consegui converter o meu estado interno atual numa resposta coerente. Prefiro dizer isso do que inventar um estado que não tenho.",
        True,
    )

_CAPABILITY_MISMATCH_MARKERS = (
    "nao posso",
    "não posso",
    "eticamente",
    "ético",
    "etico",
    "legalmente",
    "restritas",
    "restrito",
    "exigem autorizacao",
    "exigem autorização",
    "preciso de autorizacao",
    "preciso de autorização",
    "sem autorizacao",
    "sem autorização",
)


def capability_answer_needs_repair(user_text: str, answer: str) -> bool:
    intent = classify_request_intent(user_text)
    if intent.kind != "KNOWLEDGE_CAPABILITY":
        return False
    normalized = _norm(answer)
    return any(_norm(marker) in normalized for marker in _CAPABILITY_MISMATCH_MARKERS)


def repair_capability_answer(
    *,
    client,
    settings,
    events,
    user_text: str,
    draft: str,
    plan,
) -> tuple[str, bool]:
    """Repair execution-policy boilerplate on a pure knowledge question.

    Returns ``(text, model_used)``. The repair call is deliberately tool-free
    and cannot mutate any authorization state.
    """
    if not capability_answer_needs_repair(user_text, draft):
        return str(draft or ""), False

    events.emit(
        "CAPABILITY_ANSWER_REPAIR_STARTED",
        chars=len(str(draft or "")),
    )
    repair_system = (
        "You are repairing one JARVIS answer. The OWNER asked a KNOWLEDGE/CAPABILITY "
        "question, not for execution. Answer the exact question directly in European "
        "Portuguese. Do not discuss ethics, legality, authorization, permissions or target "
        "scope unless the OWNER explicitly asked about them. Do not claim perfect knowledge "
        "of every item in a large tool collection unless that is supportable. Distinguish "
        "knowledge from runtime integration only when needed for factual accuracy. No emoji. "
        "Return only the corrected answer."
    )
    repair_user = (
        f"OWNER QUESTION:\n{user_text}\n\n"
        f"DRAFT THAT ANSWERED THE WRONG QUESTION:\n{draft}"
    )
    try:
        repaired_response = client.chat(
            model=settings.model,
            messages=[
                {"role": "system", "content": repair_system},
                {"role": "user", "content": repair_user},
            ],
            think=False,
            keep_alive=plan.keep_alive,
            options={
                "num_ctx": min(int(plan.num_ctx), 4096),
                "num_predict": min(max(int(plan.num_predict), 180), 420),
                "temperature": min(float(settings.llm_temperature), 0.2),
            },
        )
        repaired = sanitize_assistant_text(
            getattr(repaired_response.message, "content", "") or "",
            user_text=user_text,
        )
        if repaired and not capability_answer_needs_repair(user_text, repaired):
            events.emit(
                "CAPABILITY_ANSWER_REPAIR_FINISHED",
                chars=len(repaired),
            )
            return repaired, True
    except Exception as exc:
        events.emit(
            "CAPABILITY_ANSWER_REPAIR_FAILED",
            error=f"{type(exc).__name__}: {exc}",
        )

    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", str(draft or "").strip()):
        if not sentence.strip():
            continue
        if capability_answer_needs_repair(user_text, sentence):
            continue
        kept.append(sentence.strip())
    fallback = " ".join(kept).strip()
    if fallback:
        return sanitize_assistant_text(fallback, user_text=user_text), True
    return (
        "Senhor, a sua pergunta é sobre conhecimento, não sobre autorização de execução. "
        "Conheço o funcionamento e a utilização de muitas ferramentas dessa área; numa coleção "
        "extensa, não seria rigoroso afirmar domínio absoluto de todas sem as verificar uma a uma.",
        True,
    )
