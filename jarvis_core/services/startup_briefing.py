from __future__ import annotations

from datetime import datetime
from typing import Any
from jarvis_core.services.user_memory import store
from jarvis_core.tools.environment_tools import get_home_environment, format_environment_summary
from jarvis_core.services.agenda import agenda_store
from jarvis_core.services.security_watch import security_watch_store


def _greeting(hour: int) -> str:
    if 6 <= hour < 12: return "Bom dia"
    if 12 <= hour < 20: return "Boa tarde"
    return "Boa noite"


def build_startup_briefing(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now().astimezone()
    profile = store().profile()
    address = profile.get("address_as") or "Senhor"
    time_text = f"{current.hour} horas e {current.minute:02d} minutos" if current.minute else f"{current.hour} horas"
    env = get_home_environment()
    agenda = agenda_store().briefing()
    watch = security_watch_store().status()
    text = f"{_greeting(current.hour)}, {address}. São {time_text}. {format_environment_summary(env)}"
    if agenda.get("today_count"):
        count = int(agenda["today_count"])
        text += f" Tem {count} compromisso" + ("s" if count != 1 else "") + " na agenda para hoje."
    alerts = [x for x in (watch.get("alerts") or []) if x.get("severity") in {"critical", "attention"}]
    if alerts:
        count = len(alerts)
        text += f" Há {count} alerta" + ("s" if count != 1 else "") + " de segurança pendente" + ("s" if count != 1 else "") + "."
    return {"ok": True, "text": text, "profile": profile, "environment": env, "agenda": agenda, "security_watch": watch}
