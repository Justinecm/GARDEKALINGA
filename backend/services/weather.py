"""OpenWeatherMap 5-day / 3-hour forecast client (FR-WX-01..03)."""
from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta, timezone

import httpx
from flask import current_app

from ..db import db
from ..models import AppState, WeatherForecast
from ..timeutil import iso, to_manila, utcnow

OWM_URL = "https://api.openweathermap.org/data/2.5/forecast"


class WeatherError(RuntimeError):
    pass


def _state(key: str) -> AppState | None:
    return db().get(AppState, key)


def _set_state(key: str, value: dict) -> None:
    s = db()
    row = s.get(AppState, key)
    if row is None:
        s.add(AppState(key=key, value_json=value, updated_at=utcnow()))
    else:
        row.value_json = value
        row.updated_at = utcnow()


def parse_owm(payload: dict, retrieved_at: datetime) -> list[WeatherForecast]:
    out = []
    for item in payload.get("list", []):
        when = datetime.fromtimestamp(int(item["dt"]), timezone.utc).replace(tzinfo=None)
        main = item.get("main", {})
        weather = (item.get("weather") or [{}])[0]
        out.append(
            WeatherForecast(
                retrieved_at=retrieved_at,
                forecast_for=when,
                temperature_c=main.get("temp"),
                humidity_pct=main.get("humidity"),
                rain_3h_mm=float((item.get("rain") or {}).get("3h", 0.0)),
                weather_condition=weather.get("main"),
                pop_pct=round(float(item.get("pop", 0.0)) * 100.0, 1),
            )
        )
    return out


def fetch_owm(lat: float, lon: float, api_key: str, attempts: int = 3) -> dict:
    delay = 0.5
    last: Exception | None = None
    for _ in range(attempts):
        try:
            r = httpx.get(
                OWM_URL,
                params={"lat": lat, "lon": lon, "units": "metric", "appid": api_key},
                timeout=6.0,
            )
            if r.status_code == 200:
                return r.json()
            last = WeatherError(f"HTTP {r.status_code}")
            if r.status_code in (401, 403):
                break  # wrong key: retrying will not help
        except httpx.HTTPError as e:
            last = e
        time.sleep(delay)
        delay *= 2
    raise WeatherError(str(last))


def synthetic_step(when: datetime, lat: float, force_rain: bool = False) -> dict:
    """Deterministic demo weather for the 3-hour step at `when` (UTC)."""
    local = to_manila(when)
    rng = random.Random(int(when.timestamp()) // 10800 + int(lat * 1000))
    phase = (local.hour - 9) / 24 * 2 * math.pi
    temp = 28.5 + 3.8 * math.sin(phase) + rng.uniform(-0.8, 0.8)
    hum = 78 - 12 * math.sin(phase) + rng.uniform(-4, 4)
    roll = rng.random()
    afternoon = 13 <= local.hour <= 19
    if force_rain:
        cond, pop, rain = "Rain", 85.0 + rng.uniform(0, 10), 2.2 + rng.uniform(0, 3)
    elif roll < (0.2 if afternoon else 0.08):
        cond = "Thunderstorm" if afternoon and roll < 0.07 else "Rain"
        pop, rain = 55 + rng.uniform(0, 40), rng.uniform(0.4, 4.5)
    elif roll < 0.55:
        cond, pop, rain = "Clouds", rng.uniform(5, 45), 0.0
    elif roll < 0.6:
        cond, pop, rain = "Haze", rng.uniform(0, 20), 0.0
    else:
        cond, pop, rain = "Clear", rng.uniform(0, 15), 0.0
    return {
        "temperature_c": round(temp, 1),
        "humidity_pct": round(max(40, min(98, hum))),
        "rain_3h_mm": round(rain, 2),
        "weather_condition": cond,
        "pop_pct": round(min(100, pop)),
    }


def step_time(t: datetime) -> datetime:
    """The 3-hour step (OWM-style, on 00/03/06... UTC) at or after t."""
    base = t.replace(minute=0, second=0, microsecond=0)
    base = base.replace(hour=(base.hour // 3) * 3)
    return base if base >= t else base + timedelta(hours=3)


def synthetic_forecast(lat: float, retrieved_at: datetime, force_rain_until: datetime | None = None, steps: int = 40) -> list[WeatherForecast]:
    """Plausible Manila weather for the demo when no OWM key is configured."""
    out = []
    start = step_time(retrieved_at + timedelta(minutes=1))
    for i in range(steps):
        when = start + timedelta(hours=3 * i)
        forced = force_rain_until is not None and when <= force_rain_until
        out.append(WeatherForecast(retrieved_at=retrieved_at, forecast_for=when, **synthetic_step(when, lat, forced)))
    return out


def refresh_forecast(now: datetime | None = None, force_rain_until: datetime | None = None) -> dict:
    """Fetch and store one forecast batch. Returns a small status dict."""
    from .settings_service import current_settings

    now = now or utcnow()
    st = current_settings()
    cfg = current_app.config["GK"]
    s = db()
    try:
        if cfg.owm_api_key:
            rows = parse_owm(fetch_owm(st.garden_lat, st.garden_lon, cfg.owm_api_key), now)
            source = "openweathermap"
        elif cfg.demo_mode:
            rows = synthetic_forecast(st.garden_lat, now, force_rain_until=force_rain_until or _demo_rain_until())
            source = "demo"
        else:
            raise WeatherError("OWM_API_KEY is not set")
        for r in rows:
            s.add(r)
        s.flush()
        status = {"ok": True, "source": source, "retrieved_at": iso(now), "steps": len(rows), "last_error": None}
    except WeatherError as e:
        prev = (_state("forecast_status").value_json if _state("forecast_status") else {}) or {}
        status = {
            "ok": False,
            "source": prev.get("source"),
            "retrieved_at": prev.get("retrieved_at"),
            "steps": 0,
            "last_error": str(e)[:200],
            "error_at": iso(now),
        }
    _set_state("forecast_status", status)
    return status


def _demo_rain_until() -> datetime | None:
    row = _state("demo")
    if row and (row.value_json or {}).get("force_rain_until"):
        from ..timeutil import parse_iso

        return parse_iso(row.value_json["force_rain_until"])
    return None


def forecast_status() -> dict:
    st = _state("forecast_status")
    return st.value_json if st else {"ok": None, "retrieved_at": None}
