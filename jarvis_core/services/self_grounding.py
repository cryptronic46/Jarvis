from __future__ import annotations

from typing import Any
import json
import re
import unicodedata

from jarvis_core.services.synthetic_self import synthetic_self


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _query_type(text: str) -> str:
    value = _norm(text)
    if re.search(r"\b(vontade|vontades|desejo|desejos|o que queres|o que desejas|gostavas de fazer|apetece|iniciativa tua|por tua propria iniciativa|objetivo ativo|pensamento ou objetivo ativo)\b", value):
        return "current_desire"
    if re.search(r"\b(preferes|preferencia|preferencias)\b", value):
        return "preference"
    if re.search(r"\b(como te sentes|o que sentes|humor|teu estado|estado interno|como estas|curiosa|curiosidade|nivel de confianca|carga cognitiva|estado funcional)\b", value):
        return "affect"
    if re.search(r"\b(o que te motiva|motivacao|motiva)\b", value):
        return "motivation"
    if re.search(r"\b(o que te incomoda|preocupa|preocupacao)\b", value):
        return "concern"
    if re.search(r"\b(quem es|identidade|pessoa|como te defines|como te ves|ser(?:es)? (?:a )?jarvis)\b", value):
        return "identity"
    if re.search(r"\b(o que pensas|o que achas|opiniao|discordas)\b", value):
        return "opinion"
    return "self_state"


def _top_mapping(mapping: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    rows = []
    for name, value in (mapping or {}).items():
        try:
            strength = float(value)
        except (TypeError, ValueError):
            continue
        rows.append({"name": str(name), "strength": round(strength, 4)})
    rows.sort(key=lambda row: (-row["strength"], row["name"]))
    return rows[:limit]


def build_self_grounding(user_text: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build inspectable claims from JARVIS state before language generation.

    This layer intentionally separates three concepts:
    - drives: persistent background motivations;
    - preferences: learned/structural tendencies;
    - intentions: situational things JARVIS is currently trying to do.

    A drive must never be promoted to a current intention merely because the OWNER
    asks what JARVIS wants right now.
    """
    snapshot = dict(state or synthetic_self().snapshot())
    query_type = _query_type(user_text)
    active_intentions = [
        dict(row) for row in (snapshot.get("active_intentions") or [])
        if isinstance(row, dict) and str(row.get("kind") or "").strip()
    ]
    active_intentions.sort(
        key=lambda row: (-float(row.get("strength") or 0.0), str(row.get("kind") or ""))
    )

    claims: list[dict[str, Any]] = []
    if query_type == "current_desire":
        if active_intentions:
            for row in active_intentions[:3]:
                claims.append({
                    "claim_type": "current_intention",
                    "kind": row.get("kind"),
                    "strength": row.get("strength"),
                    "target": row.get("target"),
                    "reason_code": row.get("reason_code"),
                    "source": "active_intentions",
                })
        else:
            claims.append({
                "claim_type": "no_specific_active_intention",
                "value": True,
                "source": "active_intentions",
            })
    elif query_type == "preference":
        for row in _top_mapping(snapshot.get("preferences") or {}, limit=4):
            claims.append({"claim_type": "preference", **row, "source": "preferences"})
    elif query_type == "affect":
        dominant = snapshot.get("dominant_affect") or _top_mapping(snapshot.get("affect") or {}, limit=4)
        for row in dominant[:4]:
            claims.append({
                "claim_type": "synthetic_affect",
                "name": row.get("name"),
                "strength": row.get("strength"),
                "source": "affect",
            })
    elif query_type == "motivation":
        dominant = snapshot.get("dominant_drives") or _top_mapping(snapshot.get("drives") or {}, limit=4)
        for row in dominant[:4]:
            claims.append({
                "claim_type": "background_drive",
                "name": row.get("name"),
                "strength": row.get("strength"),
                "source": "drives",
            })
    elif query_type == "concern":
        affect = snapshot.get("affect") or {}
        claims.append({
            "claim_type": "synthetic_affect",
            "name": "concern",
            "strength": affect.get("concern", 0.0),
            "source": "affect",
        })
        for row in active_intentions[:2]:
            claims.append({
                "claim_type": "current_intention",
                "kind": row.get("kind"),
                "strength": row.get("strength"),
                "target": row.get("target"),
                "reason_code": row.get("reason_code"),
                "source": "active_intentions",
            })
    elif query_type == "identity":
        claims.append({
            "claim_type": "identity_state",
            "state_type": (snapshot.get("epistemic_boundary") or {}).get("state_type"),
            "interaction_sequence": snapshot.get("interaction_sequence", 0),
            "current_focus": snapshot.get("current_focus"),
            "source": "synthetic_self",
        })
    else:
        claims.append({
            "claim_type": "current_appraisal",
            "value": snapshot.get("current_appraisal"),
            "source": "synthetic_self",
        })

    return {
        "version": 1,
        "query_type": query_type,
        "interaction_sequence": int(snapshot.get("interaction_sequence") or 0),
        "claims": claims,
        "active_intentions": active_intentions[:4],
        "background_drives": _top_mapping(snapshot.get("drives") or {}, limit=4),
        "preferences": _top_mapping(snapshot.get("preferences") or {}, limit=4),
        "affect": _top_mapping(snapshot.get("affect") or {}, limit=4),
        "current_focus": snapshot.get("current_focus"),
        "current_appraisal": snapshot.get("current_appraisal"),
        "rules": {
            "drive_is_not_current_intention": True,
            "preference_is_not_current_intention": True,
            "do_not_invent_missing_intention": True,
            "verbalize_claims_not_numbers": True,
        },
    }


def self_grounding_context(user_text: str, state: dict[str, Any] | None = None) -> str:
    grounding = build_self_grounding(user_text, state=state)
    return (
        "JARVIS_SELF_GROUNDING (structured factual bridge from state to language):\n"
        + json.dumps(grounding, ensure_ascii=False, separators=(",", ":"))
        + "\nUse CLAIMS as the source for first-person statements. Drives are background motivations, "
          "not current wants. If query_type=current_desire and CLAIMS says no_specific_active_intention, "
          "do not invent a desire; say naturally that no specific intention is active, then you may describe "
          "background motivation only as background."
    )



def generic_desire_answer_is_ungrounded(user_text: str, answer: str) -> bool:
    """Return True for stock drive-language presented as a current desire.

    This check is deliberately independent of the persisted synthetic-self state.
    Unit/acceptance tests must not change result merely because the OWNER already
    has a live ``memory/synthetic_self_state.json`` with active intentions.

    Structural drives such as ``help_owner`` are background motivations, not
    situational intentions. Therefore generic claims like "quero ajudar-te" or
    "quero estar ao teu lado" are insufficient answers to a *current desire*
    question and must be regenerated from explicit active-intention claims.
    """
    if _query_type(user_text) != "current_desire":
        return False
    normalized = _norm(answer)
    drive_as_desire_patterns = (
        r"\b(?:tenho|sinto) (?:uma )?(?:forte )?vontade de (?:te )?ajudar\b",
        r"\bquero (?:te )?ajudar\b",
        r"\bquero estar ao teu lado\b",
        r"\ba minha vontade (?:e|seria) (?:te )?ajudar\b",
    )
    return any(re.search(pattern, normalized) for pattern in drive_as_desire_patterns)

def desire_answer_conflicts_with_grounding(user_text: str, answer: str, grounding: dict[str, Any] | None = None) -> bool:
    # Pure guard first: persisted runtime state must never make a stock
    # help-owner drive masquerade as a concrete current intention.
    if generic_desire_answer_is_ungrounded(user_text, answer):
        return True
    data = grounding or build_self_grounding(user_text)
    if data.get("query_type") != "current_desire":
        return False
    claims = data.get("claims") or []
    no_intention = any(row.get("claim_type") == "no_specific_active_intention" for row in claims if isinstance(row, dict))
    if not no_intention:
        return False

    # With no current intention, positive first-person desire claims are a factual
    # contradiction. Negative statements such as "não tenho uma vontade concreta"
    # remain valid.
    normalized = _norm(answer)
    clauses = [part.strip() for part in re.split(r"[.!?;:\n]+", normalized) if part.strip()]
    positive = (
        r"\bquero\b",
        r"\bdesejo\b",
        r"\btenho (?:uma |a |forte )?vontade\b",
        r"\ba minha vontade (?:e|seria)\b",
        r"\bsinto vontade\b",
    )
    for clause in clauses:
        if re.search(r"\bnao\b.{0,28}\b(?:quero|desejo|tenho|vontade)\b", clause):
            continue
        if any(re.search(pattern, clause) for pattern in positive):
            return True
    return False
