"""OpenWeatherMap 5-day / 3-hour forecast client (FR-WX-01..03)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx
from flask import current_app

from ..db import db
from ..models import AppState, WeatherForecast
from ..timeutil import iso, utcnow

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


def refresh_forecast(now: datetime | None = None) -> dict:
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


def forecast_status() -> dict:
    st = _state("forecast_status")
    return st.value_json if st else {"ok": None, "retrieved_at": None}
