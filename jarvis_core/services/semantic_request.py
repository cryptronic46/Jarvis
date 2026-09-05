from __future__ import annotations

from dataclasses import dataclass


INTENTS = frozenset({
    "GENERAL_CONVERSATION",
    "SOCIAL_INTERACTION",
    "SELF_STATE",
    "IDENTITY_DIALOGUE",
    "CONVERSATION_RECALL",
    "KNOWLEDGE_CAPABILITY",
    "OPERATIONAL_ACTION",
    "RESEARCH",
    "CLARIFICATION",
    "UNKNOWN",
})

DOMAINS = frozenset({
    "conversation",
    "owner_memory",
    "jarvis_self",
    "knowledge",
    "system",
    "desktop",
    "local_files",
    "vision",
    "cyber",
    "planner",
    "web",
    "unknown",
})

SUBJECTS = frozenset({
    "OWNER",
    "JARVIS",
    "SYSTEM",
    "EXTERNAL",
    "UNKNOWN",
})


@dataclass(frozen=True, slots=True)
class StructuredRequest:
    """
    Single semantic contract for one OWNER request.

    This object carries meaning downstream. It does not authorize actions,
    execute tools, or decide security policy.
    """

    raw_text: str
    effective_text: str
    intent: str
    domain: str
    subject: str

    action: str | None = None
    target: str | None = None
    referent: str | None = None

    requires_tool: bool = False
    preferred_tool: str | None = None

    epistemic_learning_eligible: bool = False
    confidence: float = 0.0

    def __post_init__(self) -> None:
        raw_text = str(self.raw_text or "").strip()
        effective_text = str(self.effective_text or "").strip()

        if not raw_text:
            raise ValueError("raw_text must not be empty")

        if not effective_text:
            raise ValueError("effective_text must not be empty")

        if self.intent not in INTENTS:
            raise ValueError(f"invalid intent: {self.intent}")

        if self.domain not in DOMAINS:
            raise ValueError(f"invalid domain: {self.domain}")

        if self.subject not in SUBJECTS:
            raise ValueError(f"invalid subject: {self.subject}")

        confidence = float(self.confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        if self.requires_tool and not self.preferred_tool:
            # Tool choice may legitimately remain unresolved at this stage.
            # preferred_tool is therefore optional even when execution is needed.
            pass

        object.__setattr__(self, "raw_text", raw_text)
        object.__setattr__(self, "effective_text", effective_text)
        object.__setattr__(self, "confidence", confidence)

    @property
    def conversational(self) -> bool:
        return self.intent in {
            "GENERAL_CONVERSATION",
            "SOCIAL_INTERACTION",
            "SELF_STATE",
            "IDENTITY_DIALOGUE",
        }

    @property
    def operational(self) -> bool:
        return self.intent == "OPERATIONAL_ACTION"

    @property
    def research_requested(self) -> bool:
        return self.intent == "RESEARCH"

    def as_dict(self) -> dict:
        return {
            "raw_text": self.raw_text,
            "effective_text": self.effective_text,
            "intent": self.intent,
            "domain": self.domain,
            "subject": self.subject,
            "action": self.action,
            "target": self.target,
            "referent": self.referent,
            "requires_tool": self.requires_tool,
            "preferred_tool": self.preferred_tool,
            "epistemic_learning_eligible": self.epistemic_learning_eligible,
            "confidence": self.confidence,
        }


def semantic_request_contract(
    request: StructuredRequest,
) -> str:
    """Build deterministic model guidance from resolved semantics."""

    contracts = {
        "GENERAL_CONVERSATION": (
            "[SEMANTIC REQUEST]\n"
            "Intent: GENERAL_CONVERSATION.\n"
            "This is ordinary conversation with the OWNER. "
            "Answer naturally and directly. "
            "Do not reinterpret the turn as an action, research request, "
            "or knowledge-learning gap."
        ),
        "SOCIAL_INTERACTION": (
            "[SEMANTIC REQUEST]\n"
            "Intent: SOCIAL_INTERACTION.\n"
            "This is a social or companion interaction with the OWNER. "
            "Respond conversationally according to the active companion "
            "and style settings. "
            "Do not reinterpret the turn as research, learning, or an "
            "operational command."
        ),
        "SELF_STATE": (
            "[SEMANTIC REQUEST]\n"
            "Intent: SELF_STATE.\n"
            "The OWNER is asking about JARVIS synthetic/internal state. "
            "Use only grounded synthetic-self evidence. "
            "Do not claim biological feelings or unsupported state."
        ),
        "IDENTITY_DIALOGUE": (
            "[SEMANTIC REQUEST]\n"
            "Intent: IDENTITY_DIALOGUE.\n"
            "The OWNER is talking with JARVIS about JARVIS identity. "
            "Answer as JARVIS while preserving synthetic-self grounding."
        ),
        "CONVERSATION_RECALL": (
            "[SEMANTIC REQUEST]\n"
            "Intent: CONVERSATION_RECALL.\n"
            "Answer only from conversation-memory evidence supplied by "
            "the Core. Do not invent remembered facts."
        ),
        "KNOWLEDGE_CAPABILITY": (
            "[SEMANTIC REQUEST]\n"
            "Intent: KNOWLEDGE_CAPABILITY.\n"
            "Answer the knowledge or capability question directly. "
            "Do not claim tools were executed unless execution evidence "
            "is present."
        ),
        "OPERATIONAL_ACTION": (
            "[SEMANTIC REQUEST]\n"
            "Intent: OPERATIONAL_ACTION.\n"
            "This turn requests an action. "
            "Do not claim the action succeeded without verified tool "
            "execution evidence."
        ),
        "RESEARCH": (
            "[SEMANTIC REQUEST]\n"
            "Intent: RESEARCH.\n"
            "This turn explicitly requests research. "
            "Use only authorized research paths and grounded results."
        ),
        "CLARIFICATION": (
            "[SEMANTIC REQUEST]\n"
            "Intent: CLARIFICATION.\n"
            "Ask the OWNER for the missing information needed to resolve "
            "the request. Do not guess."
        ),
        "UNKNOWN": (
            "[SEMANTIC REQUEST]\n"
            "Intent: UNKNOWN.\n"
            "The semantic intent is not sufficiently certain. "
            "Do not invent an action or research objective. "
            "Ask for clarification when needed."
        ),
    }

    return contracts[request.intent]
