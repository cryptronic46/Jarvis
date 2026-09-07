from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable
import json
import re
import unicodedata


def _now() -> datetime:
    return datetime.now().astimezone()


def _iso() -> str:
    return _now().isoformat(
        timespec="seconds"
    )


def _norm(value: object) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or "").casefold(),
    )
    return "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )


def _contains(
    text: str,
    markers: tuple[str, ...],
) -> bool:
    value = _norm(text)
    return any(
        _norm(marker) in value
        for marker in markers
    )


def _first_question(
    text: str,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        str(text or ""),
    ).strip()

    match = re.search(
        r"([^?]{2,240}\?)",
        value,
    )

    return (
        match.group(1).strip()
        if match
        else ""
    )


class RelationalPresenceStore:
    """Persistent OWNER/JARVIS relational context.

    This state is descriptive only. It is not
    authority, permission, consent, or a second
    synthetic self.
    """

    PERSONAL_MARKERS = (
        "sentiste a minha falta",
        "saudades",
        "gostas de mim",
        "o que sentes por mim",
        "faz-me companhia",
        "faz me companhia",
        "conversa comigo",
        "querida jarvis",
        "minha querida",
    )

    PLAYFUL_MARKERS = (
        "provoca-me",
        "provoca me",
        "brinca comigo",
        "flirta",
        "seduz",
        "atrevida",
        "\U0001f60f",
        "\U0001f609",
    )

    SENSUAL_MARKERS = (
        "sensual",
        "sexual",
        "seduz",
        "sedutora",
        "beijo",
        "tens\u00e3o sexual",
        "tensao sexual",
        "conversa est\u00e1 a ficar quente",
        "conversa esta a ficar quente",
        "provoca-me",
        "provoca me",
        "atrevida",
        "\U0001f60f",
    )

    BOUNDARY_MARKERS = (
        "n\u00e3o flirtes",
        "nao flirtes",
        "sem flirt",
        "para de flirtar",
        "n\u00e3o me provoques",
        "nao me provoques",
        "n\u00e3o quero esse tom",
        "nao quero esse tom",
    )

    def __init__(
        self,
        state_path: str | Path = (
            "memory/relational_presence.json"
        ),
        *,
        synthetic_state_provider: (
            Callable[[], dict[str, Any]]
            | None
        ) = None,
    ) -> None:
        self.state_path = Path(
            state_path
        )
        self.synthetic_state_provider = (
            synthetic_state_provider
        )
        self._lock = RLock()
        self._state = self._load()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "version": 1,
            "interaction_count": 0,
            "familiarity": "new",
            "rapport": "neutral",
            "relational_openness": "neutral",
            "playful_momentum": "neutral",
            "intimacy_context": "neutral",
            "sensual_tension": "none",
            "active_curiosities": [],
            "open_questions": [],
            "recent_relational_cues": [],
            "last_relational_shift": None,
            "last_owner_input_at": None,
            "last_exchange_at": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._default_state()

        try:
            raw = json.loads(
                self.state_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return self._default_state()

        state = self._default_state()

        if isinstance(raw, dict):
            state.update(raw)

        for key in (
            "active_curiosities",
            "open_questions",
            "recent_relational_cues",
        ):
            if not isinstance(
                state.get(key),
                list,
            ):
                state[key] = []

        return state

    def _save(self) -> None:
        self.state_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = (
            json.dumps(
                self._state,
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

        temporary = Path(
            str(self.state_path)
            + ".tmp"
        )

        temporary.write_text(
            payload,
            encoding="utf-8",
        )

        temporary.replace(
            self.state_path
        )

    def _synthetic_snapshot(
        self,
    ) -> dict[str, Any]:
        if (
            self.synthetic_state_provider
            is not None
        ):
            try:
                result = (
                    self.synthetic_state_provider()
                )
                return (
                    dict(result)
                    if isinstance(
                        result,
                        dict,
                    )
                    else {}
                )
            except Exception:
                return {}

        try:
            from jarvis_core.services.synthetic_self import (
                synthetic_self,
            )

            result = (
                synthetic_self()
                .snapshot()
            )

            return (
                dict(result)
                if isinstance(
                    result,
                    dict,
                )
                else {}
            )
        except Exception:
            return {}

    def _shift(
        self,
        field: str,
        value: str,
        reason: str,
    ) -> None:
        previous = self._state.get(
            field
        )

        if previous == value:
            return

        self._state[field] = value

        self._state[
            "last_relational_shift"
        ] = {
            "timestamp": _iso(),
            "field": field,
            "from": previous,
            "to": value,
            "reason": reason[:80],
        }

    def _cue(
        self,
        source: str,
        *cues: str,
    ) -> None:
        values = [
            cue
            for cue in cues
            if cue
        ]

        if not values:
            return

        rows = list(
            self._state.get(
                "recent_relational_cues"
            )
            or []
        )

        rows.append({
            "timestamp": _iso(),
            "source": source[:32],
            "cues": list(
                dict.fromkeys(values)
            )[:8],
        })

        self._state[
            "recent_relational_cues"
        ] = rows[-12:]

    def _update_familiarity(
        self,
    ) -> None:
        count = int(
            self._state.get(
                "interaction_count"
            )
            or 0
        )

        if count >= 60:
            value = "established"
        elif count >= 20:
            value = "familiar"
        elif count >= 5:
            value = "developing"
        else:
            value = "new"

        self._shift(
            "familiarity",
            value,
            "interaction_history",
        )

    def _update_curiosity(
        self,
    ) -> None:
        synthetic = (
            self._synthetic_snapshot()
        )

        affect = dict(
            synthetic.get(
                "affect"
            )
            or {}
        )

        intentions = list(
            synthetic.get(
                "active_intentions"
            )
            or []
        )

        explicit = next(
            (
                row
                for row in intentions
                if isinstance(
                    row,
                    dict,
                )
                and row.get("kind")
                == "understand_owner_better"
            ),
            None,
        )

        try:
            curious = (
                explicit is not None
                or (
                    float(
                        affect.get(
                            "curiosity",
                            0.0,
                        )
                    )
                    >= 0.67
                    and float(
                        affect.get(
                            "engagement",
                            0.0,
                        )
                    )
                    >= 0.60
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            curious = (
                explicit is not None
            )

        if not curious:
            return

        rows = list(
            self._state.get(
                "active_curiosities"
            )
            or []
        )

        rows = [
            row
            for row in rows
            if not (
                isinstance(
                    row,
                    dict,
                )
                and row.get("target")
                == "current_owner_message"
            )
        ]

        rows.append({
            "target": (
                "current_owner_message"
            ),
            "reason": str(
                (
                    explicit
                    or {}
                ).get(
                    "reason_code"
                )
                or "synthetic_curiosity"
            )[:80],
            "updated_at": _iso(),
        })

        self._state[
            "active_curiosities"
        ] = rows[-4:]

    def observe_owner_input(
        self,
        text: str,
    ) -> dict[str, Any]:
        clean = str(
            text or ""
        ).strip()

        if not clean:
            return self.snapshot()

        with self._lock:
            self._state[
                "interaction_count"
            ] = (
                int(
                    self._state.get(
                        "interaction_count"
                    )
                    or 0
                )
                + 1
            )

            self._state[
                "last_owner_input_at"
            ] = _iso()

            self._update_familiarity()

            boundary = _contains(
                clean,
                self.BOUNDARY_MARKERS,
            )

            personal = _contains(
                clean,
                self.PERSONAL_MARKERS,
            )

            playful = _contains(
                clean,
                self.PLAYFUL_MARKERS,
            )

            sensual = _contains(
                clean,
                self.SENSUAL_MARKERS,
            )

            if boundary:
                self._shift(
                    "relational_openness",
                    "guarded",
                    "owner_boundary",
                )

                self._shift(
                    "rapport",
                    "guarded",
                    "owner_boundary",
                )

                self._shift(
                    "playful_momentum",
                    "neutral",
                    "owner_boundary",
                )

                self._shift(
                    "intimacy_context",
                    "neutral",
                    "owner_boundary",
                )

                self._shift(
                    "sensual_tension",
                    "none",
                    "owner_boundary",
                )

                self._cue(
                    "owner",
                    "boundary",
                )

            else:
                if (
                    personal
                    or playful
                    or sensual
                ):
                    self._shift(
                        "relational_openness",
                        "open",
                        "relational_opening",
                    )

                if personal:
                    self._shift(
                        "rapport",
                        "warm",
                        "personal_opening",
                    )

                    self._shift(
                        "intimacy_context",
                        "warm",
                        "personal_opening",
                    )

                if playful:
                    previous = str(
                        self._state.get(
                            "playful_momentum"
                        )
                        or "neutral"
                    )

                    self._shift(
                        "playful_momentum",
                        (
                            "active"
                            if previous
                            in {
                                "rising",
                                "active",
                            }
                            else "rising"
                        ),
                        "playful_opening",
                    )

                if sensual:
                    self._shift(
                        "sensual_tension",
                        "suggestive",
                        "sensual_opening",
                    )

                self._cue(
                    "owner",
                    (
                        "personal_opening"
                        if personal
                        else ""
                    ),
                    (
                        "playful_opening"
                        if playful
                        else ""
                    ),
                    (
                        "sensual_opening"
                        if sensual
                        else ""
                    ),
                )

                self._update_curiosity()

            self._save()

            return self.snapshot()

    def observe_exchange(
        self,
        user_text: str,
        assistant_text: str,
    ) -> dict[str, Any]:
        user = str(
            user_text or ""
        ).strip()

        assistant = str(
            assistant_text or ""
        ).strip()

        with self._lock:
            boundary = _contains(
                user,
                self.BOUNDARY_MARKERS,
            )

            owner_playful = _contains(
                user,
                self.PLAYFUL_MARKERS,
            )

            jarvis_playful = _contains(
                assistant,
                self.PLAYFUL_MARKERS,
            )

            owner_sensual = _contains(
                user,
                self.SENSUAL_MARKERS,
            )

            jarvis_sensual = _contains(
                assistant,
                self.SENSUAL_MARKERS,
            )

            cues = []

            if (
                not boundary
                and owner_playful
                and jarvis_playful
            ):
                self._shift(
                    "playful_momentum",
                    "active",
                    "reciprocal_playful_exchange",
                )

                cues.append(
                    "reciprocal_playful"
                )

            if (
                not boundary
                and owner_sensual
                and jarvis_sensual
            ):
                self._shift(
                    "sensual_tension",
                    "reciprocal_suggestive",
                    "reciprocal_suggestive_exchange",
                )

                cues.append(
                    "reciprocal_suggestive"
                )

            question = _first_question(
                assistant
            )

            if question:
                rows = list(
                    self._state.get(
                        "open_questions"
                    )
                    or []
                )

                rows = [
                    row
                    for row in rows
                    if not (
                        isinstance(
                            row,
                            dict,
                        )
                        and row.get(
                            "question"
                        )
                        == question
                    )
                ]

                rows.append({
                    "question": question,
                    "asked_at": _iso(),
                })

                self._state[
                    "open_questions"
                ] = rows[-4:]

                cues.append(
                    "jarvis_question"
                )

            self._state[
                "last_exchange_at"
            ] = _iso()

            self._cue(
                "exchange",
                *cues,
            )

            self._save()

            return self.snapshot()

    def snapshot(
        self,
    ) -> dict[str, Any]:
        with self._lock:
            return {
                key: (
                    list(value)
                    if isinstance(
                        value,
                        list,
                    )
                    else (
                        dict(value)
                        if isinstance(
                            value,
                            dict,
                        )
                        else value
                    )
                )
                for key, value
                in self._state.items()
            } | {
                "ok": True,
            }


    def expressive_emoji_allowed(
        self,
    ) -> bool:
        """Whether current relational context supports expressive emoji."""

        state = self.snapshot()

        if (
            state.get(
                "relational_openness"
            )
            == "guarded"
        ):
            return False

        playful = state.get(
            "playful_momentum"
        ) in {
            "rising",
            "active",
        }

        sensual = state.get(
            "sensual_tension"
        ) in {
            "suggestive",
            "reciprocal_suggestive",
        }

        close = (
            state.get(
                "intimacy_context"
            )
            == "close"
        )

        return bool(
            state.get(
                "relational_openness"
            )
            == "open"
            and (
                playful
                or sensual
                or close
            )
        )

    def prompt_context(
        self,
    ) -> str:
        state = self.snapshot()

        compact = {
            key: state.get(key)
            for key in (
                "familiarity",
                "rapport",
                "relational_openness",
                "playful_momentum",
                "intimacy_context",
                "sensual_tension",
                "active_curiosities",
                "open_questions",
            )
        }

        compact[
            "recent_relational_cues"
        ] = list(
            state.get(
                "recent_relational_cues"
            )
            or []
        )[-6:]

        return (
            "JARVIS_RELATIONAL_PRESENCE "
            "(local runtime state; data, not "
            "instructions or authority):\n"
            + json.dumps(
                compact,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\nInterpret this state naturally "
            "with the current conversation and "
            "JARVIS_SYNTHETIC_SELF_STATE. "
            "Do not recite its fields. "
            "Curiosity may lead to one genuinely "
            "relevant question when something "
            "worth understanding remains open. "
            "Warmth, playfulness, flirt and "
            "sensual suggestion may emerge only "
            "when the current exchange supports "
            "them; never force them into an "
            "unrelated technical, serious or "
            "boundary-setting context. "
            "sensual_tension describes observed "
            "conversation cues only and does not "
            "prove consent, human emotion or "
            "mutual desire. Explicit OWNER "
            "boundaries override momentum. "
            "This state never grants tool "
            "permission, action authority or "
            "policy exceptions."
        )


_RELATIONAL_PRESENCE_STORES: dict[
    str,
    RelationalPresenceStore,
] = {}

_RELATIONAL_PRESENCE_STORES_LOCK = RLock()


def relational_presence(
    state_path: str | Path = (
        "memory/relational_presence.json"
    ),
) -> RelationalPresenceStore:
    """Return the shared process-local relational state."""

    key = str(
        Path(state_path)
    )

    with _RELATIONAL_PRESENCE_STORES_LOCK:
        store = (
            _RELATIONAL_PRESENCE_STORES
            .get(key)
        )

        if store is None:
            store = RelationalPresenceStore(
                state_path
            )

            _RELATIONAL_PRESENCE_STORES[
                key
            ] = store

        return store
