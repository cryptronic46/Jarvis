from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from jarvis_core import __version__
import json
import time

from jarvis_core.services.user_memory import store

CACHE_PATH = Path(".cache/environment_furadouro.json")
CACHE_TTL_SECONDS = 600
WEATHER_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
MARINE_ENDPOINT = "https://marine-api.open-meteo.com/v1/marine"


def _fetch_json(url: str, timeout: float = 4.0) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": f"JARVIS-Core/{__version__}", "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(128 * 1024)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("Resposta JSON inesperada.")
    return data


def _weather_description(code: int | float | None) -> str:
    try:
        code = int(code)
    except Exception:
        return "condições desconhecidas"
    if code == 0: return "céu limpo e sol"
    if code == 1: return "maioritariamente limpo"
    if code == 2: return "parcialmente nublado"
    if code == 3: return "encoberto"
    if code in {45,48}: return "nevoeiro"
    if code in {51,53,55,56,57}: return "chuvisco"
    if code in {61,63,65,66,67}: return "chuva"
    if code in {71,73,75,77}: return "neve"
    if code in {80,81,82}: return "aguaceiros"
    if code in {85,86}: return "aguaceiros de neve"
    if code in {95,96,99}: return "trovoada"
    return "tempo variável"


def _sea_state(wave_height: float | None, wave_period: float | None) -> str:
    if wave_height is None:
        return "desconhecido"
    h = float(wave_height)
    p = float(wave_period or 0.0)
    if h < 0.5: state = "calmo"
    elif h < 1.0: state = "pouco agitado"
    elif h < 2.0: state = "agitado"
    elif h < 3.0: state = "bravo"
    else: state = "muito bravo"
    if p >= 12.0 and h >= 1.5:
        state += ", com ondulação longa"
    return state


def _home() -> dict[str, Any]:
    return (store().profile().get("home") or {})


def _weather_url(home: dict[str, Any]) -> str:
    return WEATHER_ENDPOINT + "?" + urlencode({
        "latitude": home["latitude"],
        "longitude": home["longitude"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,cloud_cover,precipitation,rain,wind_speed_10m,wind_gusts_10m",
        "timezone": "Europe/Lisbon",
    })


def _marine_url(home: dict[str, Any]) -> str:
    return MARINE_ENDPOINT + "?" + urlencode({
        "latitude": home.get("marine_latitude", home["latitude"]),
        "longitude": home.get("marine_longitude", home["longitude"]),
        "current": "wave_height,wave_period,swell_wave_height,swell_wave_period,sea_surface_temperature",
        "timezone": "Europe/Lisbon",
        "cell_selection": "sea",
    })


def _read_cache() -> dict[str, Any] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        age = time.time() - float(data.get("_cached_at_epoch", 0))
        if age <= CACHE_TTL_SECONDS:
            data["cache_age_seconds"] = round(max(0.0, age), 1)
            return data
    except Exception:
        pass
    return None


def _write_cache(data: dict[str, Any]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cached = dict(data)
        cached["_cached_at_epoch"] = time.time()
        CACHE_PATH.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def get_home_environment(force_refresh: bool = False) -> dict[str, Any]:
    if not force_refresh:
        cached = _read_cache()
        if cached:
            return cached
    home = _home()
    if not {"latitude", "longitude"}.issubset(home):
        return {"ok": False, "error": "HOME_LOCATION_NOT_CONFIGURED"}

    weather_data = None
    marine_data = None
    errors = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        wf = pool.submit(_fetch_json, _weather_url(home), 4.0)
        mf = pool.submit(_fetch_json, _marine_url(home), 4.0)
        try: weather_data = wf.result(timeout=5.0)
        except Exception as exc: errors.append(f"weather:{type(exc).__name__}:{exc}")
        try: marine_data = mf.result(timeout=5.0)
        except Exception as exc: errors.append(f"marine:{type(exc).__name__}:{exc}")

    current = (weather_data or {}).get("current") or {}
    marine = (marine_data or {}).get("current") or {}
    result = {
        "ok": bool(current or marine),
        "location": {"label": home.get("label"), "latitude": home.get("latitude"), "longitude": home.get("longitude"), "source": "configured_coordinates"},
        "weather": {
            "condition": _weather_description(current.get("weather_code")),
            "weather_code": current.get("weather_code"),
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "relative_humidity_percent": current.get("relative_humidity_2m"),
            "cloud_cover_percent": current.get("cloud_cover"),
            "precipitation_mm": current.get("precipitation"),
            "rain_mm": current.get("rain"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "wind_gusts_kmh": current.get("wind_gusts_10m"),
            "time": current.get("time"),
        },
        "marine": {
            "state": _sea_state(marine.get("wave_height"), marine.get("wave_period")),
            "wave_height_m": marine.get("wave_height"),
            "wave_period_s": marine.get("wave_period"),
            "swell_height_m": marine.get("swell_wave_height"),
            "swell_period_s": marine.get("swell_wave_period"),
            "sea_surface_temperature_c": marine.get("sea_surface_temperature"),
            "time": marine.get("time"),
        },
        "source": {"weather": "Open-Meteo Weather API", "marine": "Open-Meteo Marine API"},
        "errors": errors,
        "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if result["ok"]:
        _write_cache(result)
    else:
        result["error"] = "ENVIRONMENT_UNAVAILABLE"
    return result


def format_environment_summary(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return "Não consegui obter o tempo e o estado do mar neste momento."
    loc = (data.get("location") or {}).get("label") or "Furadouro"
    w = data.get("weather") or {}
    m = data.get("marine") or {}
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
