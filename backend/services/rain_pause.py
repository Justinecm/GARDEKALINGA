"""Rain pause (FR-CTL-05, FR-WX-02).

Hold off automatic watering when, over the forecast steps whose time falls within
the next `rain_window_h` hours, the highest chance of rain is at least
`rain_pop_pct` AND the summed rain is at least `rain_mm`. Only a forecast batch
retrieved less than 6 hours ago is used; an older one means no rain pause.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Protocol

from sqlalchemy import func, select

from ..db import db
from ..models import WeatherForecast
from ..timeutil import iso

FORECAST_MAX_AGE = timedelta(hours=6)


class Step(Protocol):
    forecast_for: datetime
    pop_pct: float | None
    rain_3h_mm: float


@dataclass
class RainPause:
    active: bool
    stale: bool
    pop_max: float | None
    rain_mm: float | None
    window_h: int
    retrieved_at: str | None
    steps: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(steps: Iterable[Step], now: datetime, pop_pct: float, rain_mm: float, window_h: int) -> tuple[bool, float, float, list]:
    """Pure rule. Inclusive boundaries: exactly 70% and exactly 2.0 mm pause."""
    end = now + timedelta(hours=window_h)
    chosen = [s for s in steps if now <= s.forecast_for <= end]
    if not chosen:
        return False, 0.0, 0.0, []
    pop_max = max((s.pop_pct or 0.0) for s in chosen)
    rain_sum = round(sum((s.rain_3h_mm or 0.0) for s in chosen), 3)
    active = pop_max >= pop_pct and rain_sum >= rain_mm
    return active, pop_max, rain_sum, chosen


def latest_batch(now: datetime) -> tuple[datetime | None, list[WeatherForecast]]:
    s = db()
    retrieved = s.scalar(select(func.max(WeatherForecast.retrieved_at)).where(WeatherForecast.retrieved_at <= now))
    if retrieved is None:
        return None, []
    rows = list(
        s.scalars(
            select(WeatherForecast).where(WeatherForecast.retrieved_at == retrieved).order_by(WeatherForecast.forecast_for)
        )
    )
    return retrieved, rows


def rain_pause(now: datetime, pop_pct: float, rain_mm_min: float, window_h: int) -> RainPause:
    retrieved, rows = latest_batch(now)
    if retrieved is None or now - retrieved >= FORECAST_MAX_AGE:
        return RainPause(False, True, None, None, window_h, iso(retrieved))
    active, pop_max, rain_sum, chosen = evaluate(rows, now, pop_pct, rain_mm_min, window_h)
    return RainPause(
        active,
        False,
        pop_max,
        rain_sum,
        window_h,
        iso(retrieved),
        [
            {"forecast_id": r.forecast_id, "for": iso(r.forecast_for), "pop": r.pop_pct, "rain_mm": r.rain_3h_mm}
            for r in chosen
        ],
    )
