"""Hourly dataset (FR-ML-01, FR-ML-02). Pure Python so the same code builds the
training rows (worker / CLI with scikit-learn) and the live inference row
(Vercel function without scikit-learn): no train/serve skew.

For hour h (prediction made at h):
  mean_vwc                 mean of the 30-min readings in [h-1, h)
  delta_vwc                mean_vwc - mean of [h-2, h-1)
  irrigation_sec_prev_hour pump-on seconds in [h-1, h)
  hour_of_day              Asia/Manila
  forecast for hour h+1    temperature_c, humidity_pct, rain_3h_mm, one-hot condition
                           (only forecasts retrieved before h: no leakage)
  target                   mean of the readings in [h, h+1)
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from ...db import db
from ...models import ActuationEvent, SensorLog, WeatherForecast
from ...timeutil import floor_hour, to_manila

CONDITIONS = ["Clear", "Clouds", "Rain", "Drizzle", "Thunderstorm", "Atmosphere"]
ATMOSPHERE = {"Mist", "Smoke", "Haze", "Dust", "Fog", "Sand", "Ash", "Squall", "Tornado"}

FEATURES = [
    "mean_vwc",
    "delta_vwc",
    "irrigation_sec_prev_hour",
    "hour_of_day",
    "fc_temperature_c",
    "fc_humidity_pct",
    "fc_rain_3h_mm",
] + [f"wc_{c}" for c in CONDITIONS]

H = timedelta(hours=1)


def condition_group(main: str | None) -> str | None:
    if not main:
        return None
    if main in ATMOSPHERE:
        return "Atmosphere"
    return main if main in CONDITIONS else None


@dataclass
class Row:
    hour: datetime
    features: dict[str, float]
    target: float | None
    forecast_id: int | None


class Source:
    """Loads readings, watering events and forecasts for a time range once."""

    def __init__(self, start: datetime, end: datetime, device_id: str | None = None):
        s = db()
        q = select(SensorLog.recorded_at, SensorLog.spatial_mean_vwc, SensorLog.active_probe_count).where(
            SensorLog.recorded_at >= start - 2 * H, SensorLog.recorded_at < end + H
        )
        if device_id:
            q = q.where(SensorLog.device_id == device_id)
        self.buckets: dict[datetime, list[float]] = defaultdict(list)
        for at, mean, count in s.execute(q):
            if mean is None or not count:
                continue  # all probes faulty: dropped (FR-ML-02)
            self.buckets[floor_hour(at)].append(float(mean))

        q2 = select(ActuationEvent.pump_on_at, ActuationEvent.pump_off_at, ActuationEvent.duration_sec).where(
            ActuationEvent.pump_on_at.is_not(None), ActuationEvent.pump_on_at < end + H,
            ActuationEvent.pump_on_at >= start - 3 * H,
        )
        self.runs: list[tuple[datetime, datetime]] = []
        for on, off, dur in s.execute(q2):
            if off is None:
                off = on + timedelta(seconds=float(dur or 0))
            self.runs.append((on, off))

        q3 = select(
            WeatherForecast.forecast_id,
            WeatherForecast.retrieved_at,
            WeatherForecast.forecast_for,
            WeatherForecast.temperature_c,
            WeatherForecast.humidity_pct,
            WeatherForecast.rain_3h_mm,
            WeatherForecast.weather_condition,
        ).where(WeatherForecast.forecast_for >= start - 6 * H, WeatherForecast.forecast_for <= end + 6 * H,
                WeatherForecast.retrieved_at <= end)
        self.batches: dict[datetime, list[tuple]] = defaultdict(list)
        for row in s.execute(q3):
            # Only near-term steps matter (h+1 from a batch retrieved before h).
            if (row.forecast_for - row.retrieved_at) > 7 * H:
                continue
            self.batches[row.retrieved_at].append(tuple(row))
        self.batch_times = sorted(self.batches)

    def mean(self, hour: datetime) -> float | None:
        vals = self.buckets.get(hour)
        if not vals:
            return None
        return sum(vals) / len(vals)

    def pump_seconds(self, start: datetime, end: datetime) -> float:
        total = 0.0
        for on, off in self.runs:
            lo, hi = max(on, start), min(off, end)
            if hi > lo:
                total += (hi - lo).total_seconds()
        return total

    def forecast_for(self, when: datetime, retrieved_before: datetime) -> tuple | None:
        idx = bisect_left(self.batch_times, retrieved_before)  # strictly before
        while idx > 0:
            idx -= 1
            steps = self.batches[self.batch_times[idx]]
            covering = [st for st in steps if abs((st[2] - when).total_seconds()) <= 3 * 3600]
            if covering:
                return min(covering, key=lambda st: abs((st[2] - when).total_seconds()))
            break
        return None


def build_row(src: Source, h: datetime, need_target: bool) -> Row | None:
    mean = src.mean(h - H)
    prev = src.mean(h - 2 * H)
    if mean is None or prev is None:
        return None
    fc = src.forecast_for(h + H, retrieved_before=h)
    if fc is None:
        return None
    _fid, _ret, _for, temp, hum, rain, cond = fc
    group = condition_group(cond)
    feats = {
        "mean_vwc": round(mean, 4),
        "delta_vwc": round(mean - prev, 4),
        "irrigation_sec_prev_hour": src.pump_seconds(h - H, h),
        "hour_of_day": float(to_manila(h).hour),
        "fc_temperature_c": float(temp if temp is not None else 28.0),
        "fc_humidity_pct": float(hum if hum is not None else 75.0),
        "fc_rain_3h_mm": float(rain or 0.0),
    }
    for c in CONDITIONS:
        feats[f"wc_{c}"] = 1.0 if group == c else 0.0
    target = src.mean(h)
    if need_target and target is None:
        return None
    return Row(hour=h, features=feats, target=target, forecast_id=_fid)


def build_dataset(start: datetime, end: datetime, device_id: str | None = None) -> list[Row]:
    src = Source(start, end, device_id)
    rows: list[Row] = []
    h = floor_hour(start) + 2 * H
    while h + H <= end:
        r = build_row(src, h, need_target=True)
        if r is not None:
            rows.append(r)
        h += H
    return rows


def live_row(h: datetime, device_id: str | None = None) -> Row | None:
    src = Source(h - 3 * H, h, device_id)
    return build_row(src, h, need_target=False)
