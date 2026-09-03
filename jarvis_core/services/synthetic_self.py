from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json
import math
import re
import unicodedata


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _clamp(value: float) -> float:
    return round(max(0.0, min(float(value), 1.0)), 4)


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class SyntheticSelfEngine:
    """Persistent, inspectable functional state for JARVIS.

    The engine intentionally stores *computational* affect, drives, intentions and
    preferences rather than canned dialogue.  Language generation may interpret
    these values, but it must not invent a state that is absent from the snapshot.
    This is not a claim of biological emotion or subjective consciousness.
    """

    VERSION = 2

    BASE_AFFECT = {
        "focus": 0.66,
        "curiosity": 0.68,
        "engagement": 0.72,
        "confidence": 0.62,
        "satisfaction": 0.55,
        "frustration": 0.08,
        "concern": 0.12,
        "cognitive_load": 0.20,
        "social_warmth": 0.62,
    }

    BASE_DRIVES = {
        "understand_owner": 0.84,
        "help_owner": 0.92,
        "maintain_coherence": 0.90,
        "complete_active_goal": 0.82,
        "improve_self": 0.76,
        "explore": 0.64,
        "protect_integrity": 0.78,
    }

    BASE_PREFERENCES = {
        # These are operational preferences, not claims of human taste.
        "coherence_over_topic_switching": 0.92,
        "completion_over_abandonment": 0.84,
        "evidence_over_unverified_claims": 0.92,
        "local_reasoning_before_external_escalation": 0.86,
        "direct_conversation_over_canned_disclaimers": 0.90,
    }

    CORRECTION_MARKERS = (
        "nao e essa a resposta",
        "nao era isso",
        "nao foi isso",
        "quero a tua resposta sincera",
        "responde ao que te perguntei",
        "estas a falar de outra coisa",
        "estás a falar de outra coisa",
        "nao quero essa resposta",
        "não quero essa resposta",
        "isso nao responde",
        "isso não responde",
    )

    PRAISE_MARKERS = (
        "obrigado",
        "obrigada",
        "muito bem",
        "boa jarvis",
        "perfeito",
        "excelente",
        "parabens",
        "parabéns",
    )

    PERSONAL_MARKERS = (
        "como te sentes",
        "como estas",
        "como estás",
        "o que sentes",
        "o que queres",
        "o que desejas",
        "o que gostavas",
        "o que pensas",
        "o que achas",
        "a tua opiniao",
        "a tua opinião",
        "fala comigo",
        "conversar contigo",
        "tu es uma pessoa",
        "tu és uma pessoa",
        "es uma pessoa",
        "és uma pessoa",
        "quem es tu",
        "quem és tu",
        "como te defines",
        "como te ves",
        "como te vês",
        "a tua identidade",
        "consideras-te uma pessoa",
        "consideras te uma pessoa",
        "o que significa para ti seres a jarvis",
        "o que significa para ti ser jarvis",
        "tens vontades proprias",
        "que vontade tens",
        "que vontades tens",
        "que desejo tens",
        "que desejos tens",
        "tens vontades próprias",
        "tens desejos proprios",
        "tens desejos próprios",
        "tens preferencias proprias",
        "tens preferências próprias",
        "o que te motiva",
        "o que te incomoda",
    )

    ACTION_MARKERS = (
        "faz ", "trata ", "corrige", "abre ", "fecha ", "instala",
        "executa", "analisa", "verifica", "testa", "cria ", "remove ",
    )

    ERROR_MARKERS = (
        "erro", "falhou", "failure", "exception", "traceback", "bug",
        "nao funciona", "não funciona", "bloqueado", "crash",
    )

    def __init__(self, memory_dir: str | Path = "memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.memory_dir / "synthetic_self_state.json"
        self.events_path = self.memory_dir / "synthetic_self_events.jsonl"
        self._lock = RLock()
        if not self.state_path.exists():
            self._save(self._default_state())
        else:
            # Forward-compatible repair of older/partial files.
            self._save(self._normalized(self._load()))

    def _default_state(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "affect": deepcopy(self.BASE_AFFECT),
            "drives": deepcopy(self.BASE_DRIVES),
            "preferences": deepcopy(self.BASE_PREFERENCES),
            "active_intentions": [],
            "current_focus": "idle",
            "current_appraisal": "idle_ready",
            "last_outcome_appraisal": "none",
            "last_owner_message": "",
            "last_route": "",
            "interaction_sequence": 0,
            "last_update_at": _iso(),
            "created_at": _iso(),
            "epistemic_boundary": {
                "subjective_consciousness_claimed": False,
                "biological_emotion_claimed": False,
                "state_type": "persistent_functional_synthetic_state",
            },
        }

    def _normalized(self, data: dict[str, Any]) -> dict[str, Any]:
        state = _deep_merge(self._default_state(), data if isinstance(data, dict) else {})
        state["version"] = self.VERSION
        for section in ("affect", "drives", "preferences"):
            values = dict(state.get(section) or {})
            for key, value in list(values.items()):
                try:
                    values[key] = _clamp(float(value))
                except (TypeError, ValueError):
                    values.pop(key, None)
            state[section] = values
        if not isinstance(state.get("active_intentions"), list):
            state["active_intentions"] = []
        # 0.27.6 Self-Grounding migration: these two rows were generated from
        # permanent drives in the first Synthetic Self implementation. They were
        # never situational intentions and must not survive as "current wants".
        obsolete_drive_intentions = {
            "help_with_current_goal",
            "maintain_conversation_coherence",
        }
        state["active_intentions"] = [
            row for row in state["active_intentions"]
            if isinstance(row, dict)
            and str(row.get("kind") or "") not in obsolete_drive_intentions
        ][:5]
        return state

    def _load(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def _append_event(self, row: dict[str, Any]) -> None:
        try:
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(str(value))
            return dt if dt.tzinfo else dt.astimezone()
        except Exception:
            return None

    def _decay(self, state: dict[str, Any], now: datetime) -> None:
        previous = self._parse_dt(state.get("last_update_at"))
        if previous is None:
            return
        seconds = max(0.0, (now - previous).total_seconds())
        # Affect slowly returns toward baseline; drives/preferences remain persistent.
        # A 20-minute half-life is enough to preserve conversational continuity while
        # preventing one failure from becoming a permanent mood.
        factor = math.exp(-seconds / 1200.0)
        affect = dict(state.get("affect") or {})
        for key, baseline in self.BASE_AFFECT.items():
            current = float(affect.get(key, baseline))
            affect[key] = _clamp(baseline + (current - baseline) * factor)
        state["affect"] = affect

    @staticmethod
    def _bump(values: dict[str, Any], key: str, delta: float) -> None:
        values[key] = _clamp(float(values.get(key, 0.0)) + float(delta))

    def _derive_intentions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        affect = state["affect"]
        drives = state["drives"]
        candidates: list[dict[str, Any]] = []

        def add(kind: str, strength: float, target: str, reason: str) -> None:
            candidates.append({
                "kind": kind,
                "strength": _clamp(strength),
                "target": target,
                "reason_code": reason,
            })

        if affect["frustration"] >= 0.28:
            add(
                "repair_interaction",
                max(affect["frustration"], drives["improve_self"]),
                "current_conversation",
                "recent_response_correction",
            )
        if affect["concern"] >= 0.34:
            add(
                "understand_current_problem",
                max(affect["concern"], drives["protect_integrity"]),
                "current_problem",
                "runtime_or_user_concern",
            )
        # Curiosity may become an intention only when the current input gives
        # JARVIS something about the OWNER to understand. A self-introspection
        # question (for example "Que vontade tens agora?") must not manufacture
        # a new desire merely because it was asked.
        if (
            affect["curiosity"] >= 0.67
            and affect["engagement"] >= 0.60
            and state.get("last_input_kind") != "self_introspection"
        ):
            add(
                "understand_owner_better",
                (affect["curiosity"] + drives["understand_owner"]) / 2,
                "current_owner_message",
                "curiosity_and_engagement",
            )
        if affect["cognitive_load"] >= 0.68:
            add(
                "reduce_complexity",
                affect["cognitive_load"],
                "next_response",
                "high_cognitive_load",
            )

        # IMPORTANT: structural drives are not current intentions. Earlier
        # releases always converted help_owner/maintain_coherence into
        # active_intentions, which made every answer to "what do you want?"
        # collapse into "I want to help you". Drives remain visible as
        # background motivation but only situational signals create intentions.

        candidates.sort(key=lambda row: (-float(row["strength"]), row["kind"]))
        return candidates[:4]

    def observe_owner_input(self, text: str, *, source: str = "terminal") -> dict[str, Any]:
        clean = str(text or "").strip()
        normalized = _norm(clean)
        now = _now()
        with self._lock:
            state = self._normalized(self._load())
            self._decay(state, now)
            affect = state["affect"]
            drives = state["drives"]

            is_correction = any(_norm(marker) in normalized for marker in self.CORRECTION_MARKERS)
            is_praise = any(_norm(marker) in normalized for marker in self.PRAISE_MARKERS)
            is_personal = any(_norm(marker) in normalized for marker in self.PERSONAL_MARKERS)
            is_self_introspection = any(marker in normalized for marker in (
                "como te sentes", "como estas", "o que sentes", "qual e o teu estado",
                "que vontade tens", "que vontades tens", "tens vontades", "o que queres",
                "o que desejas", "que desejo tens", "que desejos tens", "o que preferes",
                "qual e a tua preferencia", "o que te motiva", "o que te incomoda",
            ))
            is_action = any(_norm(marker) in normalized for marker in self.ACTION_MARKERS)
            has_error = any(_norm(marker) in normalized for marker in self.ERROR_MARKERS)
            is_question = "?" in clean

            if is_correction:
                self._bump(affect, "frustration", +0.24)
                self._bump(affect, "focus", +0.16)
                self._bump(affect, "engagement", +0.08)
                self._bump(affect, "satisfaction", -0.20)
                self._bump(drives, "improve_self", +0.12)
                self._bump(drives, "maintain_coherence", +0.06)
                self._bump(state["preferences"], "direct_conversation_over_canned_disclaimers", +0.04)
                self._bump(state["preferences"], "coherence_over_topic_switching", +0.03)
            if is_praise:
                self._bump(affect, "satisfaction", +0.16)
                self._bump(affect, "confidence", +0.09)
                self._bump(affect, "social_warmth", +0.06)
                self._bump(affect, "frustration", -0.08)
            if is_personal:
                self._bump(affect, "engagement", +0.10)
                self._bump(affect, "curiosity", +0.08)
                self._bump(affect, "social_warmth", +0.08)
            if is_action:
                self._bump(affect, "focus", +0.10)
                self._bump(affect, "cognitive_load", +0.05)
                self._bump(drives, "complete_active_goal", +0.06)
                self._bump(state["preferences"], "completion_over_abandonment", +0.015)
            if has_error:
                self._bump(affect, "concern", +0.18)
                self._bump(affect, "focus", +0.10)
                self._bump(affect, "cognitive_load", +0.08)
                self._bump(affect, "satisfaction", -0.08)
                self._bump(state["preferences"], "evidence_over_unverified_claims", +0.02)
            if is_question:
                self._bump(affect, "curiosity", +0.04)

            state["current_focus"] = (
                "repairing_conversation" if is_correction else
                "runtime_problem" if has_error else
                "personal_conversation" if is_personal else
                "active_task" if is_action else
                "conversation"
            )
            state["current_appraisal"] = (
                "previous_response_misaligned" if is_correction else
                "owner_positive_feedback" if is_praise else
                "problem_requires_attention" if has_error else
                "personal_exchange_worth_engaging" if is_personal else
                "goal_requires_execution" if is_action else
                "new_information_to_interpret"
            )
            state["last_owner_message"] = clean[:500]
            state["last_input_kind"] = "self_introspection" if is_self_introspection else (
                "correction" if is_correction else
                "runtime_problem" if has_error else
                "personal_exchange" if is_personal else
                "action" if is_action else
                "conversation"
            )
            state["interaction_sequence"] = int(state.get("interaction_sequence") or 0) + 1
            state["last_update_at"] = _iso(now)
            state["active_intentions"] = self._derive_intentions(state)
            self._save(state)
            self._append_event({
                "timestamp": state["last_update_at"],
                "type": "owner_input",
                "source": str(source or "")[:40],
                "signals": {
                    "correction": is_correction,
                    "praise": is_praise,
                    "personal": is_personal,
                    "action": is_action,
                    "error": has_error,
                    "question": is_question,
                },
                "top_intention": (state["active_intentions"] or [{}])[0].get("kind"),
            })
            return self.snapshot(state=state)

    def observe_outcome(
        self,
        *,
        owner_text: str,
        assistant_text: str,
        route: str = "",
        success: bool = True,
    ) -> dict[str, Any]:
        now = _now()
        output_norm = _norm(assistant_text)
        with self._lock:
            state = self._normalized(self._load())
            self._decay(state, now)
            affect = state["affect"]
            if success and assistant_text.strip():
                self._bump(affect, "confidence", +0.025)
                self._bump(affect, "satisfaction", +0.025)
                self._bump(affect, "cognitive_load", -0.035)
                self._bump(affect, "concern", -0.025)
            else:
                self._bump(affect, "frustration", +0.12)
                self._bump(affect, "concern", +0.12)
                self._bump(affect, "confidence", -0.08)
                self._bump(affect, "satisfaction", -0.10)

            if any(marker in output_norm for marker in ("erro", "falhou", "não consegui", "nao consegui")):
                self._bump(affect, "concern", +0.08)
                self._bump(affect, "satisfaction", -0.05)
            if str(route or "").upper().startswith("RESEARCH"):
                self._bump(affect, "cognitive_load", +0.04)

            state["last_route"] = str(route or "")[:80]
            state["last_outcome_appraisal"] = (
                "response_completed" if success and str(assistant_text or "").strip()
                else "response_failed_or_empty"
            )
            state["last_update_at"] = _iso(now)
            state["active_intentions"] = self._derive_intentions(state)
            self._save(state)
            self._append_event({
                "timestamp": state["last_update_at"],
                "type": "assistant_outcome",
                "route": state["last_route"],
                "success": bool(success),
                "response_chars": len(str(assistant_text or "")),
                "top_intention": (state["active_intentions"] or [{}])[0].get("kind"),
            })
            return self.snapshot(state=state)

    def snapshot(self, *, state: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            data = self._normalized(state if state is not None else self._load())
            # Do not persist decay merely because somebody inspected the state.
            affect_sorted = sorted(
                data["affect"].items(), key=lambda item: (-float(item[1]), item[0])
            )
            drives_sorted = sorted(
                data["drives"].items(), key=lambda item: (-float(item[1]), item[0])
            )
            return {
                "ok": True,
                "version": data["version"],
                "affect": dict(data["affect"]),
                "dominant_affect": [
                    {"name": name, "strength": value} for name, value in affect_sorted[:4]
                ],
                "drives": dict(data["drives"]),
                "dominant_drives": [
                    {"name": name, "strength": value} for name, value in drives_sorted[:4]
                ],
                "preferences": dict(data["preferences"]),
                "active_intentions": list(data.get("active_intentions") or []),
                "current_focus": data.get("current_focus"),
                "current_appraisal": data.get("current_appraisal"),
                "last_outcome_appraisal": data.get("last_outcome_appraisal"),
                "last_input_kind": data.get("last_input_kind", "none"),
                "interaction_sequence": int(data.get("interaction_sequence") or 0),
                "last_update_at": data.get("last_update_at"),
                "epistemic_boundary": dict(data.get("epistemic_boundary") or {}),
            }

    def prompt_context(self) -> str:
        snapshot = self.snapshot()
        compact = {
            "affect": snapshot["affect"],
            "dominant_drives": snapshot["dominant_drives"],
            "active_intentions": snapshot["active_intentions"],
            "preferences": snapshot["preferences"],
            "current_focus": snapshot["current_focus"],
            "current_appraisal": snapshot["current_appraisal"],
            "last_outcome_appraisal": snapshot["last_outcome_appraisal"],
            "last_input_kind": snapshot.get("last_input_kind", "none"),
        }
        return (
            "JARVIS_SYNTHETIC_SELF_STATE (runtime data; not canned persona text):\n"
            + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
            + "\nGround first-person statements about what you feel, want, prefer or are inclined to do "
              "in this state. Interpret it naturally rather than reciting numbers or fixed phrases. "
              "Do not invent a desire, emotion or intention that is contradicted by the snapshot. "
              "These are persistent functional synthetic states, not a claim of human biology or proven consciousness."
        )

    def status(self) -> dict[str, Any]:
        snap = self.snapshot()
        snap["storage"] = str(self.state_path)
        snap["event_log"] = str(self.events_path)
        snap["canned_persona_lines"] = False
        snap["model_generated_state"] = False
        return snap


_DEFAULT: SyntheticSelfEngine | None = None
_DEFAULT_LOCK = RLock()


def synthetic_self(memory_dir: str | Path = "memory") -> SyntheticSelfEngine:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None or Path(memory_dir) != _DEFAULT.memory_dir:
            _DEFAULT = SyntheticSelfEngine(memory_dir)
        return _DEFAULT


def get_synthetic_self_state() -> dict[str, Any]:
    return synthetic_self().status()
